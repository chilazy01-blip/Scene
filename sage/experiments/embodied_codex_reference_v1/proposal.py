"""A model proposes reference timing; deterministic code owns execution and gates."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time

SCHEMA = {
    "type": "object",
    "properties": {
        "schema": {"type": "string", "enum": ["codex-reference-timing/v1"]},
        "place_duration_ticks": {"type": "integer", "minimum": 65, "maximum": 110},
        "retract_duration_ticks": {"type": "integer", "minimum": 40, "maximum": 100},
        "rationale": {"type": "string"},
        "evidence_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "expected_tradeoff": {"type": "string"},
    },
    "required": ["schema", "place_duration_ticks", "retract_duration_ticks", "rationale", "evidence_ids", "expected_tradeoff"],
    "additionalProperties": False,
}


def validate(value, evidence_ids=None):
    if not isinstance(value, dict) or set(value) != set(SCHEMA["required"]):
        raise ValueError("proposal has missing or extra fields")
    if value["schema"] != "codex-reference-timing/v1":
        raise ValueError("unknown proposal schema")
    for key, low, high in (("place_duration_ticks", 65, 110), ("retract_duration_ticks", 40, 100)):
        if type(value[key]) is not int or not low <= value[key] <= high:
            raise ValueError("reference duration outside declared envelope: " + key)
    for key in ("rationale", "expected_tradeoff"):
        if not isinstance(value[key], str) or not value[key].strip():
            raise ValueError("empty explanation: " + key)
    ids = value["evidence_ids"]
    if not isinstance(ids, list) or not ids or any(not isinstance(x, str) or not x for x in ids):
        raise ValueError("evidence identifiers required")
    if evidence_ids is not None and not set(ids) <= set(evidence_ids):
        raise ValueError("proposal cites evidence absent from input")
    return value.copy()


def invoke(context, output, timeout=180):
    """Keep exact request, response, command, usage events and failure; no fallback plan."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output / "SCHEMA.json").write_text(json.dumps(SCHEMA, indent=2) + "\n")
    (output / "CONTEXT.json").write_text(json.dumps(context, indent=2) + "\n")
    prompt = (
        "You are the reference-proposal component in a robot simulation data workflow. "
        "Return ONLY the schema-conforming final JSON. Do not use tools, inspect other files, "
        "edit code, launch agents or run simulations. You must reason from the attached evidence. "
        "Select ONE common timing proposal for both predefined target cases before their outcomes "
        "are known. Goals are complete task success and a larger final stability margin. "
        "You control only place and retract durations. The numerical trajectory compiler uses "
        "quintic interpolation and preserves previous desired origins, endpoints and orientation. "
        "You cannot change physics, solver, finger controls, success gates, stage timeouts, "
        "release logic or the established safe stand-reference handoff. Slower motion is a "
        "hypothesis, not a guarantee. Explain its physical rationale and time-cost tradeoff, "
        "cite only supplied evidence IDs, and never claim an unexecuted improvement.\n\n"
        + json.dumps(context, ensure_ascii=False, indent=2)
    )
    (output / "PROMPT.txt").write_text(prompt)
    command = ["codex", "exec", "--ephemeral", "--sandbox", "read-only", "--skip-git-repo-check",
               "--cd", str(output), "--color", "never", "--json", "--output-schema",
               str(output / "SCHEMA.json"), "--output-last-message", str(output / "RESPONSE.json"), "-"]
    started = time.time()
    timed_out = False
    with (output / "EVENTS.jsonl").open("w") as out, (output / "STDERR.log").open("w") as err:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=out, stderr=err,
                                   text=True, start_new_session=True)
        try:
            process.communicate(prompt, timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
    record = {"command": command, "started_epoch_utc": started, "wall_s": time.time() - started,
              "returncode": process.returncode, "timed_out": timed_out,
              "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
              "model_output_accepted": False, "new_physics_steps": 0}
    response = output / "RESPONSE.json"
    if process.returncode == 0 and response.exists():
        try:
            record["proposal"] = validate(json.loads(response.read_text()), context["evidence"])
            record["model_output_accepted"] = True
        except (ValueError, TypeError) as exc:
            record["validation_error"] = str(exc)
    (output / "INVOCATION.json").write_text(json.dumps(record, indent=2) + "\n")
    return record
