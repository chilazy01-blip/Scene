"""Finite prefixes and all3fixed cases; never rerun a failed or completed episode."""

import argparse
from pathlib import Path
import os
import resource
import subprocess
import sys
import time
from .audit import audit
from sage.experiments.embodied_native_walk_v1.motion_gate import require_motion_protocol
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def run(root):
    p = require_motion_protocol(root)
    output = root / "motion_v1"
    output.mkdir(exist_ok=False)
    resource.setrlimit(resource.RLIMIT_AS, (16 * 1024**3, 16 * 1024**3))
    os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:8])
    started = time.monotonic()
    outcomes = []
    qualified = []
    error = None
    stop = False
    reserved_unknown = 0
    try:
        for case in p["conditions"]:
            cid = case["id"]
            folder = output / cid
            folder.mkdir()
            previous = None
            for ticks in (0, *p["active_budgets_ticks"]):
                episode = folder / (
                    "admission" if ticks == 0 else f"active_{ticks:04d}"
                )
                consumed = sum(x["physics_steps"] for x in outcomes) + reserved_unknown
                ceiling = 440 if ticks == 0 else 240 + 4 * ticks
                if consumed + ceiling > p["max_total_physics_steps"]:
                    raise RuntimeError(
                        "global physics budget exhausted before child launch"
                    )
                args = [
                    sys.executable,
                    "-B",
                    "-m",
                    "sage.experiments.embodied_native_walk_motion_v1.engine",
                    "--root",
                    str(root),
                    "--case",
                    cid,
                    "--output",
                    str(episode),
                    "--ticks",
                    str(ticks or 100),
                ]
                if ticks:
                    args += ["--admission", str(folder / "admission/REPORT.json")]
                if ticks > 100:
                    args += ["--previous", str(previous)]
                save(
                    output / "LIVE_CHILD.json",
                    {
                        "case": cid,
                        "ticks": ticks,
                        "episode": str(episode),
                        "reserved_max_steps": ceiling,
                        "known_consumed_steps": consumed,
                    },
                )
                try:
                    with episode.with_suffix(".log").open("w") as log:
                        child = subprocess.run(
                            args,
                            stdout=log,
                            stderr=subprocess.STDOUT,
                            timeout=p["per_process_wall_s"],
                        )
                except subprocess.TimeoutExpired:
                    reserved_unknown += ceiling
                    raise RuntimeError(
                        "child wall-time exceeded; reserved full step ceiling charged, no retry"
                    )
                if not (episode / "REPORT.json").is_file():
                    reserved_unknown += ceiling
                    raise RuntimeError(
                        f"child engineering failure exit={child.returncode}; inspect {episode.with_suffix('.log')}"
                    )
                r = read_bound_json(episode / "REPORT.json")
                a = audit(root, episode)
                outcomes.append(
                    {
                        "case": cid,
                        "stage": episode.name,
                        "physics_steps": r["physics_steps"],
                        "control_passed": a["control_passed"],
                        "task_passed": a["task_passed"],
                        "stop_reason": r["stop_reason"],
                        "final_phase": r["final_phase"],
                        "report": _file_binding(episode / "REPORT.json"),
                        "audit": _file_binding(episode / "AUDIT.json"),
                    }
                )
                save(
                    output / "PROGRESS.json",
                    {
                        "outcomes": outcomes,
                        "qualified": qualified,
                        "physics_steps": sum(x["physics_steps"] for x in outcomes),
                        "wall_s": time.monotonic() - started,
                    },
                )
                print(outcomes[-1], flush=True)
                if not a["control_passed"]:
                    stop = True
                    break
                if a["task_passed"]:
                    qualified.append(cid)
                    break
                if ticks:
                    previous = episode / "REPORT.json"
            if stop or cid not in qualified:
                break
    except Exception as exc:
        error = type(exc).__name__ + ": " + str(exc)
    result = {
        "schema": "native-walk-bounded-attempt/v1",
        "task_passed": len(qualified) == 3,
        "qualified_conditions": qualified,
        "outcomes": outcomes,
        "error": error,
        "physics_steps": sum(x["physics_steps"] for x in outcomes),
        "unresolved_child_conservative_step_charge": reserved_unknown,
        "wall_s": time.monotonic() - started,
        "protocol": _file_binding(root / "MOTION_PROTOCOL.json"),
        "implementation": _file_binding(Path(__file__)),
        "all_failed_or_completed_runs_preserved": True,
    }
    save(output / "RESULT.json", result)
    print(
        {
            k: result[k]
            for k in ("task_passed", "qualified_conditions", "physics_steps", "error")
        },
        flush=True,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    run(p.parse_args().root)
