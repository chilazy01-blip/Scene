"""Durable P019 provider comparison, with separate 2D and TRELLIS stages.

Run from the repository root, for example::

    python -m sage.experiments.codex_trellis_scene_v2.p019_provider_benchmark freeze
    python -m sage.experiments.codex_trellis_scene_v2.p019_provider_benchmark submit-candidates
    python -m sage.experiments.codex_trellis_scene_v2.p019_provider_benchmark poll
    python -m sage.experiments.codex_trellis_scene_v2.p019_provider_benchmark promote
    python -m sage.experiments.codex_trellis_scene_v2.p019_provider_benchmark audit

Only the bridge generates assets. This program never fabricates an image or
starts/stops a model service. The Codex executor fulfils builtin requests outside
this process. A lost POST response is uncertain, never permission to resubmit.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any, Callable, Iterator
import urllib.error
import urllib.request

from .content_chain import build_generation_contract, content_hash, file_binding


DEFAULT_ROOT = Path("/data/wsj/main/scene_runs/codex_trellis_v2/p019_p021_longrun_20260905_v1/p019")
PROVIDERS = ("builtin_imagegen", "flux1-schnell")
STAGES = ("candidate", "trellis")
DIMENSIONS = {
    "sofa": {"width": 1.80, "length": 0.88, "height": 0.86},
    "bookcase": {"width": 0.90, "length": 0.32, "height": 1.60},
    "storage_box": {"width": 0.46, "length": 0.34, "height": 0.28},
}
SHAPE_PROFILES = {"sofa": "upholstered_seating", "bookcase": "open_shelving", "storage_box": "compact_orthogonal"}
JOB_ID = re.compile(r"[A-Za-z0-9_-]+\Z")


def atomic_bytes(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_json(path: Path, value: Any) -> None:
    atomic_bytes(path, (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8"))


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


@contextmanager
def locked(directory: Path) -> Iterator[None]:
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".runner.lock").open("a+b") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def http_request(url: str, payload: dict[str, Any] | None = None, *, method: str = "GET", timeout: float = 60) -> tuple[int, bytes, str]:
    # An explicit POST with payload=None sends an empty body for bridge resume.
    body = json.dumps(payload).encode("utf-8") if payload is not None else (b"" if method == "POST" else None)
    request = urllib.request.Request(url, data=body, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(response.status), response.read(), str(response.headers.get("Content-Type") or "")
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read(), str(exc.headers.get("Content-Type") or "")


def json_body(body: bytes) -> dict[str, Any]:
    try:
        value = json.loads(body)
        return value if isinstance(value, dict) else {"value": value}
    except (ValueError, UnicodeError):
        return {"error": body.decode("utf-8", errors="replace")[:8000]}


def freeze(root: Path) -> dict[str, Any]:
    """Expand, validate and seal the existing preregistration without editing it."""
    with locked(root):
        plan = read_json(root / "frozen_plan.json")
        if set(plan.get("providers", [])) != set(PROVIDERS) or plan.get("replicates_per_spec_provider") != 2:
            raise ValueError("P019 requires the two frozen providers and two replicates")
        specifications = plan.get("specifications", [])
        if len(specifications) != 3 or {item["id"] for item in specifications} != set(DIMENSIONS):
            raise ValueError("P019 requires the frozen sofa, bookcase and storage_box specifications")
        included = None
        if "included_specifications" in plan:
            included = plan["included_specifications"]
            if not isinstance(included, list) or not included or any(not isinstance(value, str) for value in included):
                raise ValueError("included_specifications must be a nonempty list of specification IDs")
            if len(included) != len(set(included)):
                raise ValueError("included_specifications must not contain duplicate IDs")
            if set(included) - {item["id"] for item in specifications}:
                raise ValueError("included_specifications contains unknown IDs")
        expected_control = {"pipeline": "512", "steps": 12, "texture_size": 512, "decimation_target": 300000}
        if plan.get("three_d_control") != expected_control:
            raise ValueError("P019 3D controls differ from the authorized 512/12/512/300000 comparison")
        cases = []
        for specification in specifications:
            prompt = specification["prompt"]
            if hashlib.sha256(prompt.encode("utf-8")).hexdigest() != specification["prompt_sha256"]:
                raise ValueError(f"Frozen prompt hash mismatch: {specification['id']}")
            if included is not None and specification["id"] not in included:
                continue
            for replicate in (1, 2):
                for provider in plan["providers"]:
                    category = specification["id"]
                    cases.append({
                        "id": f"{category}__{provider}__r{replicate}", "category": category,
                        "provider": provider, "replicate": replicate, "prompt": prompt,
                        "prompt_sha256": specification["prompt_sha256"],
                        "seed": int(specification["flux_seed"]) + (replicate - 1) * 10000,
                        "image_seed": int(specification["flux_seed"]) + (replicate - 1) * 10000 if provider == "flux1-schnell" else None,
                        "dimensions": deepcopy(DIMENSIONS[category]),
                        "shape_profile": SHAPE_PROFILES[category],
                        "visual_checks": deepcopy(specification["visual_checks"]),
                    })
        result = {
            "schema": "p019-frozen-cases/v1", "preregistration_hash": content_hash(plan),
            "preregistration_file": file_binding(root / "frozen_plan.json"),
            "three_d_control": expected_control, "cases": cases,
            "sampling": "Every frozen attempt retained; builtin image seed unavailable; TRELLIS seed shared by replicate.",
            "candidate_count": 1, "retry_count": 0,
        }
        # Optional follow-up fields must never change the legacy 12-case
        # serialization or content key when they are absent from the plan.
        if included is not None:
            result["included_specifications"] = deepcopy(included)
        if "followup_to_plan" in plan:
            result["followup_to_plan"] = deepcopy(plan["followup_to_plan"])
        result["content_key"] = content_hash(result)
        path = root / "frozen_cases.json"
        if path.exists():
            if read_json(path) != result:
                raise ValueError("Existing frozen cases differ; refusing to change the experiment")
        else:
            write_json(path, result)
        return result


def candidate_request(case: dict[str, Any], frozen: dict[str, Any]) -> dict[str, Any]:
    return {
        "image_provider": case["provider"], "input_text": case["prompt"],
        "seed": case["seed"], "candidate_only": True,
        "scene_dna_candidate_count": 1,
        "pipeline_type": "512", "preprocess_image": True,
        "sparse_steps": 12, "shape_steps": 12, "tex_steps": 12,
        "texture_size": 512, "decimation_target": 300000,
        "simplify_limit": 1048576, "glb_webp": False,
        "p019_benchmark_case_id": case["id"],
        "p019_benchmark_plan_hash": frozen["content_key"],
    }


def selected_attempt(metadata: dict[str, Any]) -> dict[str, Any]:
    selected = metadata.get("selected_reference_job_id")
    matches = [row for row in metadata.get("reference_attempts", []) if row.get("reference_job_id") == selected]
    if not selected or len(matches) != 1:
        raise ValueError("Expected exactly one selected reference attempt")
    return matches[0]


def measured_stage_times(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Expose reported intervals with their actual scope; never infer GPU time."""
    metadata = metadata or {}
    provider = metadata.get("image_provider_metadata") or {}
    def interval(start: str, end: str) -> float | None:
        values = (provider.get(start), provider.get(end))
        if all(isinstance(value, (int, float)) for value in values):
            return round(max(0.0, values[1] - values[0]), 6)
        return None
    def stage_sum(key: str) -> float | None:
        values = [row.get("elapsed_seconds") for row in metadata.get(key, [])]
        return round(sum(values), 6) if values and all(isinstance(value, (int, float)) for value in values) else None
    return {
        "builtin_request_to_executor_claim_seconds": interval("created_at", "claimed_at"),
        "builtin_executor_claim_to_import_seconds": interval("claimed_at", "completed_at"),
        "builtin_request_to_import_seconds": provider.get("elapsed_seconds"),
        "trellis_pipeline_reported_seconds": stage_sum("pipeline_run_attempts"),
        "trellis_postprocess_reported_seconds": stage_sum("postprocess_attempts"),
        "compute_active_seconds": None, "rmbg_seconds": None,
        "scope_note": "Executor interval includes tool invocation/import overhead; model loading and RMBG are outside the reported TRELLIS pipeline interval.",
    }


def classify_failure(error: Any) -> dict[str, Any]:
    """Classify only explicit bridge diagnostics; retain unknown-stage failures."""
    message = str(error.get("error") or "") if isinstance(error, dict) else str(error or "")
    lower = message.lower()
    signatures = (
        ("qa_rejected", ("all reference attempts failed white-background isolation qa", "all alpha quality attempts failed", "exposed_support_background_gap_missing")),
        ("infrastructure_failure", ("cuda out of memory", "cuda error: out of memory", "connection refused", "connection reset by peer", "no module named", "no space left on device")),
        ("image_provider_failure", ("builtin image job ", "builtin provider rejected request")),
    )
    for category, markers in signatures:
        matched = [marker for marker in markers if marker in lower]
        if matched:
            return {"failure_class": category, "failure_classification_basis": "explicit_bridge_error_signature", "matched_error_signatures": matched}
    return {"failure_class": "unclassified_failure", "failure_classification_basis": "bridge_did_not_identify_a_known_failure_stage", "matched_error_signatures": []}


def candidate_quality(metadata: dict[str, Any], case: dict[str, Any], job_id: str) -> dict[str, Any]:
    from .asset_source_policy import validate_reference_evidence

    failures = []
    if metadata.get("job_id") != job_id:
        failures.append("candidate_job_binding")
    if metadata.get("image_provider") != case["provider"]:
        failures.append("candidate_provider_binding")
    if metadata.get("input_text") != case["prompt"]:
        failures.append("candidate_specification_binding")
    if metadata.get("status") != "candidate_batch_done" or metadata.get("candidate_only") is not True:
        failures.append("candidate_completion_contract")
    provider_contract = metadata.get("image_provider_contract") or {}
    expected_provider_control = {"provider": case["provider"], "background_mode": "white", "retry_count": 0}
    if case["provider"] == "flux1-schnell":
        expected_provider_control.update(width=1024, height=1024, steps=4, guidance_scale=0.0)
    for key, value in expected_provider_control.items():
        if provider_contract.get(key) != value:
            failures.append(f"provider_control:{key}")
    attempts = metadata.get("reference_attempts", [])
    if len(attempts) != 1:
        failures.append("candidate_count_not_one")
    try:
        selected = selected_attempt(metadata)
    except ValueError as exc:
        return {"ok": False, "failures": failures + [str(exc)]}
    evidence = selected.get("persistent_evidence", {})
    source_gate = validate_reference_evidence(evidence)
    failures.extend(source_gate["failures"])
    for record in (selected, evidence):
        if record.get("image_provider", "flux1-schnell") != case["provider"]:
            failures.append("selected_provider_binding")
    if selected.get("alpha_quality_ok") is not True:
        failures.append("alpha_quality_rejected")
    if selected.get("persistent_evidence") != metadata.get("selected_reference_evidence"):
        failures.append("selected_evidence_binding")
    if evidence.get("parent_job_id") != job_id or evidence.get("reference_job_id") != selected.get("reference_job_id"):
        failures.append("evidence_job_binding")
    prompt = selected.get("prompt")
    if not isinstance(prompt, str) or not prompt:
        failures.append("composed_prompt_missing")
    if case["provider"] == "builtin_imagegen" and selected.get("image_provider_metadata") != metadata.get("image_provider_metadata"):
        failures.append("provider_metadata_binding")
    files = evidence.get("files", {})
    return {
        "ok": not failures, "failures": sorted(set(failures)), "reference_source_gate": source_gate,
        "composed_prompt": prompt,
        "composed_prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest() if isinstance(prompt, str) else None,
        "source_rgb": files.get("source_rgb"), "prepared_rgba": files.get("prepared_rgba"),
        "alpha_metadata": files.get("alpha_metadata"), "evidence_manifest": evidence.get("manifest"),
        "provider_metadata": deepcopy(metadata.get("image_provider_metadata")),
        "provider_contract": deepcopy(provider_contract),
    }


class Benchmark:
    def __init__(self, args: argparse.Namespace, *, transport: Callable[..., tuple[int, bytes, str]] = http_request) -> None:
        self.args = args
        self.root = args.root.expanduser().resolve()
        self.frozen = freeze(self.root)
        self.transport = transport
        self.bridge_url = args.bridge_url.rstrip("/")

    def directory(self, case: dict[str, Any], stage: str | None = None) -> Path:
        path = self.root / "cases" / case["id"]
        return path / stage if stage else path

    def cases(self) -> list[dict[str, Any]]:
        rows = [case for case in self.frozen["cases"] if (not self.args.provider or case["provider"] == self.args.provider)
                and (not self.args.case_id or case["id"] in self.args.case_id)]
        if self.args.case_id and set(self.args.case_id) - {case["id"] for case in rows}:
            raise ValueError("Unknown case ID or case/provider filter conflict")
        return rows

    def stage_result(self, case: dict[str, Any], stage: str) -> dict[str, Any] | None:
        path = self.directory(case, stage) / "result.json"
        return read_json(path) if path.exists() else None

    def failure_evidence(self, job_id: str) -> list[dict[str, Any]]:
        """Link rejected attempts by their explicit parent job, without admitting them."""
        evidence_root = self.args.evidence_root or self.root / "evidence"
        records = []
        for path in sorted((evidence_root / job_id / "attempts").glob("*.json")):
            try:
                manifest = read_json(path)
                if manifest.get("parent_job_id") != job_id:
                    continue
                files = manifest.get("files", {})
                bindings_ok = True
                for record in files.values():
                    actual = file_binding(Path(record["path"]))
                    bindings_ok &= all(actual[key] == record.get(key) for key in ("bytes", "sha256"))
                records.append({"manifest": {"path": str(path), **file_binding(path)}, "reference_job_id": manifest.get("reference_job_id"),
                                "files": files, "content_binding_ok": bindings_ok, "admitted": False})
            except (OSError, ValueError, TypeError, KeyError) as exc:
                records.append({"manifest_path": str(path), "content_binding_ok": False, "admitted": False, "error": str(exc)})
        return records

    def checkpoint(self, directory: Path, status: str, **fields: Any) -> dict[str, Any]:
        record = {"status": status, "updated_at": time.time(), **fields}
        write_json(directory / "state.json", record)
        return record

    def _accepted(self, directory: Path, envelope: dict[str, Any]) -> dict[str, Any] | None:
        path = directory / "accepted.json"
        if path.exists():
            accepted = read_json(path)
            if accepted.get("request_hash") != envelope["request_hash"] or accepted.get("bridge_url") != envelope["bridge_url"]:
                raise ValueError("Accepted job no longer matches its persisted request/bridge")
            return accepted
        return None

    def _reconcile(self, directory: Path, envelope: dict[str, Any], job_id: str | None = None) -> dict[str, Any] | None:
        store = self.args.bridge_job_dir
        if not store:
            return None
        paths = [store / f"{job_id}.json"] if job_id else sorted(store.glob("*.json"))
        matches = [(path.stem, read_json(path)) for path in paths if path.is_file()]
        def matches_request(value: dict[str, Any]) -> bool:
            stored = deepcopy(value.get("request"))
            if not isinstance(stored, dict):
                return False
            # This field is bound and added by the server after admission.
            if "image_provider_contract" not in envelope["payload"]:
                stored.pop("image_provider_contract", None)
            return stored == envelope["payload"]
        matches = [(identifier, value) for identifier, value in matches if matches_request(value)]
        if len(matches) > 1:
            raise ValueError("Multiple bridge jobs match this frozen stage; refusing to choose")
        if not matches:
            return None
        identifier, record = matches[0]
        accepted = {"job_id": identifier, "bridge_url": envelope["bridge_url"], "request_hash": envelope["request_hash"],
                    "accepted_at": record.get("created_at"), "reconciled_at": time.time(),
                    "recovered_from": str(store / f"{identifier}.json"),
                    "server_image_provider_contract": record.get("request", {}).get("image_provider_contract")}
        write_json(directory / "accepted.json", accepted)
        return accepted

    def submit(self, case: dict[str, Any], stage: str, payload: dict[str, Any]) -> dict[str, Any]:
        directory = self.directory(case, stage)
        with locked(directory):
            envelope = {"schema": "p019-stage-request/v1", "case_id": case["id"], "stage": stage,
                        "bridge_url": self.bridge_url, "payload": payload, "request_hash": content_hash(payload)}
            path = directory / "request.json"
            if path.exists():
                if read_json(path) != envelope:
                    raise ValueError("Stage request changed after it was frozen")
            else:
                write_json(path, envelope)
            result = self.stage_result(case, stage)
            if result:
                return result
            accepted = self._accepted(directory, envelope)
            if accepted:
                return {"status": "already_submitted", **accepted}
            state_path = directory / "state.json"
            state = read_json(state_path) if state_path.exists() else {}
            if state.get("status") in {"submitting", "submission_uncertain"}:
                accepted = self._reconcile(directory, envelope)
                if accepted:
                    return self.checkpoint(directory, "accepted", **accepted)
                return self.checkpoint(directory, "submission_uncertain", error="POST may have been accepted; reconcile the original job before continuing")
            started = time.time()
            self.checkpoint(directory, "submitting", submission_started_at=started)
            try:
                code, body, content_type = self.transport(
                    f"{self.bridge_url}/providers/{case['provider']}/generate", payload, method="POST", timeout=self.args.http_timeout)
            except (OSError, TimeoutError, ConnectionError) as exc:
                return self.checkpoint(directory, "submission_uncertain", error=f"{type(exc).__name__}: {exc}", submission_started_at=started)
            response = json_body(body)
            if code == 202 and JOB_ID.fullmatch(str(response.get("job_id") or "")):
                # This is intentionally the first durable action after parsing
                # a successful POST: no logging, metadata GET or polling first.
                accepted = {"job_id": response["job_id"], "bridge_url": self.bridge_url,
                            "request_hash": envelope["request_hash"], "accepted_at": time.time(),
                            "submission_started_at": started, "response": response}
                write_json(directory / "accepted.json", accepted)
                return self.checkpoint(directory, "accepted", **accepted)
            history = directory / "submission_responses"
            write_json(history / f"{time.time_ns()}.json", {"http_status": code, "response": response, "content_type": content_type})
            if code in {429, 503}:
                return self.checkpoint(directory, "pending_not_submitted", http_status=code, response=response)
            if code >= 500 or code == 202:
                return self.checkpoint(directory, "submission_uncertain", http_status=code, response=response)
            result = {"status": "submission_rejected", "ok": False, "http_status": code, "response": response, "completed_at": time.time()}
            write_json(directory / "result.json", result)
            return self.checkpoint(directory, **result)

    def _resume(self, case: dict[str, Any], stage: str, accepted: dict[str, Any]) -> dict[str, Any]:
        directory = self.directory(case, stage)
        try:
            code, body, _ = self.transport(f"{accepted['bridge_url']}/job/{accepted['job_id']}/resume", None,
                                           method="POST", timeout=self.args.http_timeout)
            response = json_body(body)
        except (OSError, TimeoutError, ConnectionError) as exc:
            return self.checkpoint(directory, "resume_uncertain", job_id=accepted["job_id"], error=str(exc))
        event = {"at": time.time(), "http_status": code, "response": response, "job_id": accepted["job_id"]}
        write_json(directory / "resume_events" / f"{time.time_ns()}.json", event)
        if code == 202 and response.get("job_id") != accepted["job_id"]:
            raise ValueError("Resume returned a different job ID")
        return self.checkpoint(directory, "processing" if code == 202 else "resume_pending", **event)

    def poll_one(self, case: dict[str, Any], stage: str) -> dict[str, Any]:
        directory = self.directory(case, stage)
        with locked(directory):
            result = self.stage_result(case, stage)
            if result:
                return result
            request_path = directory / "request.json"
            if not request_path.exists():
                return {"status": "not_submitted"}
            envelope = read_json(request_path)
            accepted = self._accepted(directory, envelope) or self._reconcile(directory, envelope)
            if not accepted:
                state_path = directory / "state.json"
                return read_json(state_path) if state_path.exists() else {"status": "not_submitted"}
            job_id = accepted["job_id"]
            base = f"{accepted['bridge_url']}/providers/{case['provider']}/job/{job_id}"
            try:
                code, body, content_type = self.transport(base, timeout=self.args.http_timeout)
            except (OSError, TimeoutError, ConnectionError) as exc:
                return self.checkpoint(directory, "poll_unavailable", job_id=job_id, error=str(exc))
            if code == 410:
                write_json(directory / "last_bridge_status.json", json_body(body))
                if self.args.resume_interrupted:
                    return self._resume(case, stage, accepted)
                return self.checkpoint(directory, "interrupted", job_id=job_id)
            if code == 202:
                response = json_body(body)
                write_json(directory / "last_bridge_status.json", response)
                if response.get("status") == "waiting_for_image_provider" and self.args.resume_pending:
                    return self._resume(case, stage, accepted)
                return self.checkpoint(directory, response.get("status") or "processing", job_id=job_id)
            if code not in {200, 500}:
                return self.checkpoint(directory, "poll_unavailable", job_id=job_id, http_status=code, response=json_body(body))
            completed_at = time.time()
            first_completion_path = directory / "completion_observed.json"
            if not first_completion_path.exists():
                write_json(first_completion_path, {"at": completed_at, "http_status": code})
            completed_at = read_json(first_completion_path)["at"]
            if stage == "candidate" and code == 200:
                metadata = json_body(body)
                write_json(directory / "bridge_metadata.json", metadata)
            else:
                if code == 200:
                    glb_path = self.directory(case) / "assets" / f"{case['id']}.glb"
                    atomic_bytes(glb_path, body)
                else:
                    write_json(directory / "bridge_error.json", json_body(body))
                try:
                    meta_code, meta_body, _ = self.transport(base + "/metadata", timeout=self.args.http_timeout)
                except (OSError, TimeoutError, ConnectionError):
                    meta_code, meta_body = 0, b""
                metadata = json_body(meta_body) if meta_code == 200 else None
                if metadata is not None:
                    write_json(directory / "bridge_metadata.json", metadata)
                elif code == 200:
                    return self.checkpoint(directory, "waiting_for_metadata", job_id=job_id)
            if code == 500:
                error = json_body(body)
                result = {"status": "bridge_failed", "ok": False, "error": error, **classify_failure(error),
                          "rejected_attempt_evidence": self.failure_evidence(job_id)}
            elif stage == "candidate":
                quality = candidate_quality(metadata, case, job_id)
                write_json(directory / "candidate_qa.json", quality)
                result = {"status": "candidate_accepted" if quality["ok"] else "candidate_rejected", "ok": quality["ok"],
                          "candidate_qa_path": str(directory / "candidate_qa.json"), "qa": quality}
            else:
                valid = body[:4] == b"glTF" and metadata.get("status") == "done" and metadata.get("job_id") == job_id and metadata.get("image_provider") == case["provider"]
                result = {"status": "generated" if valid else "generation_response_rejected", "ok": valid,
                          "glb_path": str(glb_path), "glb_binding": file_binding(glb_path)}
            result.update({"job_id": job_id, "completed_at": completed_at,
                           "accepted_at": accepted.get("accepted_at"), "http_status": code,
                           "bridge_metadata_path": str(directory / "bridge_metadata.json") if metadata is not None else None,
                           "client_accepted_to_completion_seconds": completed_at - accepted["accepted_at"] if accepted.get("accepted_at") else None,
                           "client_submission_seconds": accepted["accepted_at"] - accepted["submission_started_at"] if accepted.get("submission_started_at") else None,
                           "active_generation_seconds": None, "resource_peaks": None,
                           "stage_times": measured_stage_times(metadata),
                           "measurement_note": "Client elapsed includes provider waiting and local processing; compute-active time and remote resources are not inferred."})
            write_json(directory / "result.json", result)
            return self.checkpoint(directory, **result)

    def promotion_request(self, case: dict[str, Any]) -> dict[str, Any]:
        result = self.stage_result(case, "candidate")
        if not result or not result.get("ok"):
            raise ValueError("Only accepted frozen candidates can be promoted")
        metadata = read_json(self.directory(case, "candidate") / "bridge_metadata.json")
        quality = candidate_quality(metadata, case, result["job_id"])
        if not quality["ok"]:
            raise ValueError(f"Candidate evidence changed before promotion: {quality['failures']}")
        source = quality["source_rgb"]
        payload = candidate_request(case, self.frozen)
        payload.update(candidate_only=False, reference_image_path=source["path"],
                       image_provider_contract=deepcopy(quality["provider_contract"]))
        return payload

    def all_candidates_terminal(self) -> bool:
        return all(self.stage_result(case, "candidate") is not None for case in self.frozen["cases"])

    def submit_stage(self, stage: str) -> dict[str, Any]:
        if stage == "trellis" and not self.all_candidates_terminal():
            raise ValueError("Finish and retain every frozen 2D attempt before promoting any candidate")
        submitted = 0
        for case in self.cases():
            if self.stage_result(case, stage):
                continue
            if stage == "trellis" and not self.stage_result(case, "candidate").get("ok"):
                write_json(self.directory(case, stage) / "result.json", {"status": "skipped_candidate_rejected", "ok": False, "completed_at": time.time()})
                continue
            payload = candidate_request(case, self.frozen) if stage == "candidate" else self.promotion_request(case)
            result = self.submit(case, stage, payload)
            print(json.dumps({"case_id": case["id"], "stage": stage, **result}, ensure_ascii=False), flush=True)
            if result["status"] in {"pending_not_submitted", "submission_uncertain"}:
                break
            submitted += 1
            if self.args.wait and result["status"] in {"accepted", "already_submitted"}:
                deadline = time.monotonic() + self.args.timeout
                while self.stage_result(case, stage) is None and time.monotonic() < deadline:
                    self.poll_one(case, stage)
                    if self.stage_result(case, stage) is None:
                        time.sleep(self.args.interval)
                if self.stage_result(case, stage) is None:
                    break
            if submitted >= self.args.limit:
                break
        return self.summary()

    def poll(self) -> dict[str, Any]:
        stages = STAGES if self.args.stage == "all" else (self.args.stage,)
        deadline = time.monotonic() + self.args.timeout
        while True:
            active = False
            for case in self.cases():
                for stage in stages:
                    result = self.poll_one(case, stage)
                    active |= (self.directory(case, stage) / "accepted.json").exists() and self.stage_result(case, stage) is None
                    print(json.dumps({"case_id": case["id"], "stage": stage, "status": result["status"]}), flush=True)
            summary = self.summary()
            if not self.args.watch or not active or time.monotonic() >= deadline:
                return summary
            time.sleep(self.args.interval)

    def summary(self) -> dict[str, Any]:
        rows = []
        for case in self.frozen["cases"]:
            row = {"case_id": case["id"], "provider": case["provider"], "category": case["category"], "replicate": case["replicate"]}
            for stage in STAGES:
                directory = self.directory(case, stage)
                result = self.stage_result(case, stage)
                state = read_json(directory / "state.json") if (directory / "state.json").exists() else {}
                row[stage] = result or state or {"status": "not_submitted"}
                if result and result.get("status") == "bridge_failed":
                    row[stage].update(classify_failure(result.get("error")))
                    row[stage]["rejected_attempt_evidence"] = self.failure_evidence(result["job_id"])
                if result and "stage_times" not in result and (directory / "bridge_metadata.json").exists():
                    row[stage]["stage_times"] = measured_stage_times(read_json(directory / "bridge_metadata.json"))
                row[f"{stage}_terminal"] = result is not None
            audit_path = self.directory(case) / "audit.json"
            row["audit"] = read_json(audit_path) if audit_path.exists() else None
            rows.append(row)
        by_provider = {}
        for provider in PROVIDERS:
            subset = [row for row in rows if row["provider"] == provider]
            by_provider[provider] = {
                "planned": len(subset), "candidate_terminal": sum(row["candidate_terminal"] for row in subset),
                "candidate_accepted": sum(row["candidate"].get("ok") is True for row in subset),
                "candidate_qa_rejected": sum(row["candidate"].get("failure_class") == "qa_rejected" for row in subset),
                "candidate_infrastructure_failure": sum(row["candidate"].get("failure_class") == "infrastructure_failure" for row in subset),
                "candidate_image_provider_failure": sum(row["candidate"].get("failure_class") == "image_provider_failure" for row in subset),
                "candidate_unclassified_failure": sum(row["candidate"].get("failure_class") == "unclassified_failure" for row in subset),
                "trellis_generated": sum(row["trellis"].get("status") == "generated" for row in subset),
                "automated_3d_accepted": sum(bool(row["audit"] and row["audit"].get("automated_accepted")) for row in subset),
                "visually_accepted": sum(bool(row["audit"] and row["audit"].get("accepted")) for row in subset),
            }
        prompt_comparison = {}
        for category in dict.fromkeys(row["category"] for row in rows):
            subset = [row for row in rows if row["category"] == category]
            hashes = [row["candidate"].get("qa", {}).get("composed_prompt_sha256") for row in subset]
            available = [value for value in hashes if value]
            prompt_comparison[category] = {"observed_composed_prompt_hashes": sorted(set(available)),
                                           "observed_cases": len(available), "planned_cases": len(subset),
                                           "all_observed_prompts_equal": bool(available) and len(set(available)) == 1,
                                           "all_case_prompts_observed": len(available) == len(subset)}
        summary = {"schema": "p019-provider-benchmark-progress/v1", "frozen_cases_key": self.frozen["content_key"],
                   "planned_case_count": len(rows), "all_candidates_terminal": all(row["candidate_terminal"] for row in rows),
                   "all_trellis_terminal": all(row["trellis_terminal"] for row in rows),
                   "by_provider": by_provider, "composed_prompt_comparison": prompt_comparison, "results": rows,
                   "scene_assembly_acceptance": "external_evidence_required", "updated_at": time.time()}
        write_json(self.root / "benchmark_progress.json", summary)
        return summary

    def generation_contract(self, case: dict[str, Any], metadata: dict[str, Any], source: Path) -> dict[str, Any]:
        candidate_metadata = read_json(self.directory(case, "candidate") / "bridge_metadata.json")
        attempt = selected_attempt(candidate_metadata)
        code_path = Path(__file__).resolve()
        contract = build_generation_contract(
            category=case["category"], prompt=attempt["prompt"], target_dimensions_m=case["dimensions"],
            seed=case["seed"], model_fingerprint=self.args.trellis_model_fingerprint or str(metadata.get("trellis_model") or "bridge_model_identity_unreported"),
            rmbg_fingerprint=self.args.rmbg_model_fingerprint or "bridge_rmbg_identity_unreported",
            pipeline_type="512", steps=12, texture_size=512, decimation_target=300000,
            preprocess_image=True, code_version=f"p019-provider-benchmark/v1:{file_binding(code_path)['sha256']}", reference_image=source)
        contract.pop("content_key")
        contract.update({"image_provider": case["provider"], "image_seed": case["image_seed"],
                         "image_provider_metadata": candidate_metadata.get("image_provider_metadata"),
                         "image_provider_contract": candidate_metadata.get("image_provider_contract"),
                         "candidate_evidence_manifest": deepcopy(attempt["persistent_evidence"]["manifest"]),
                         "candidate_job_id": candidate_metadata["job_id"], "trellis_job_id": metadata["job_id"],
                         "bridge_metadata_hash": content_hash(metadata),
                         "frozen_cases_key": self.frozen["content_key"], "case_id": case["id"],
                         "generation_request_hash": read_json(self.directory(case, "trellis") / "request.json")["request_hash"]})
        contract["content_key"] = content_hash(contract)
        return contract

    def audit_one(self, case: dict[str, Any]) -> dict[str, Any]:
        from .asset_source_policy import audit_asset_source_policy
        from .content_chain import make_artifact_certificate, verify_artifact_certificate
        from .scene_dna_multiview import VIEW_AXES, render_and_evaluate_generated_asset
        from .white_background_real_batch import LOW_UNDER_AXES, _contract, _inspect_glb, _object, render_low_under

        directory = self.directory(case)
        with locked(directory / "audit_lock"):
            result = self.stage_result(case, "trellis")
            if result is None or result.get("status") != "generated":
                report = {"case_id": case["id"], "provider": case["provider"], "status": "no_generated_glb",
                          "accepted": False, "automated_accepted": False, "trellis_result": result,
                          "standard_views": {}, "low_under_views": {}}
                write_json(directory / "audit.json", report)
                return report
            glb_path = Path(result["glb_path"])
            candidate = self.stage_result(case, "candidate")
            candidate_meta = read_json(self.directory(case, "candidate") / "bridge_metadata.json")
            quality = candidate_quality(candidate_meta, case, candidate["job_id"])
            metadata_path = self.directory(case, "trellis") / "bridge_metadata.json"
            metadata = read_json(metadata_path)
            request = read_json(self.directory(case, "trellis") / "request.json")
            generation = {"job_id": result["job_id"], "image_provider": case["provider"], "request": request["payload"], "bridge_metadata": metadata}
            source_gate = audit_asset_source_policy({"mode": "generate", "results": [{"object_id": case["id"], "category": case["category"], "status": "generated", "metadata": generation}]})
            write_json(directory / "source_policy_report.json", source_gate)
            failures = []
            if not quality["ok"]:
                failures.append("candidate_evidence_no_longer_valid")
            if not source_gate["ok"]:
                failures.append("generation_source_gate_rejected")
            if file_binding(glb_path) != result["glb_binding"]:
                failures.append("downloaded_glb_content_changed")
            if request["request_hash"] != content_hash(request["payload"]) or request["payload"] != self.promotion_request(case):
                failures.append("promotion_request_binding")
            selected = selected_attempt(metadata)
            upstream_source = selected["persistent_evidence"]["files"]["source_rgb"]
            if upstream_source.get("sha256") != quality["source_rgb"].get("sha256"):
                failures.append("promotion_used_different_source_rgb")
            if metadata.get("image_provider") != case["provider"]:
                failures.append("promotion_changed_provider")
            control_failures = []
            if metadata.get("pipeline_type") != "512" or metadata.get("requested_pipeline_type") != "512":
                control_failures.append("promotion_pipeline_control")
            successful_postprocess = [attempt for attempt in metadata.get("postprocess_attempts", []) if attempt.get("ok") is True]
            if len(successful_postprocess) != 1 or any(successful_postprocess[0].get(key) != expected for key, expected in (("texture_size", 512), ("decimation_target", 300000))):
                control_failures.append("promotion_effective_postprocess_control")
            if failures:
                report = {"case_id": case["id"], "provider": case["provider"], "status": "provenance_rejected", "accepted": False,
                          "automated_accepted": False, "failures": failures, "glb_path": str(glb_path),
                          "source_policy_report": str(directory / "source_policy_report.json"), "standard_views": {}, "low_under_views": {}}
                write_json(directory / "audit.json", report)
                return report
            contract = self.generation_contract(case, metadata, Path(quality["source_rgb"]["path"]))
            write_json(directory / "generation_contract.json", contract)
            obj = _object(case)
            obj.update(asset_generation_contract=contract, asset_generation_key=contract["content_key"])
            write_json(directory / "asset_object.json", obj)
            generation.update(generation_contract=contract, generation_key=contract["content_key"])
            write_json(directory / "generation.json", generation)
            glb = _inspect_glb(glb_path)
            write_json(directory / "glb_inspection.json", glb)
            standard_dir, low_dir = directory / "standard_multiview", directory / "low_under_multiview"
            audit_case = deepcopy(case)
            # The frozen descriptive name maps to the established QA profile.
            if audit_case["shape_profile"] == "open_shelving":
                audit_case["shape_profile"] = "open_repeated_frame"
            script = Path(__file__).resolve().parents[2] / "scripts" / "blender_render_asset_turntables.py"
            upstream = {"generation_contract": contract, "generation_key": contract["content_key"]}
            capture_rules = {"schema": "p019-capture-cache/v1", "resolution": self.args.resolution,
                             "renderer_binary": file_binding(self.args.blender.resolve()), "renderer_script": file_binding(script),
                             "scene_dna_contract": _contract(audit_case), "geometry_evidence": True}
            def cached_capture(capture_dir: Path, report_name: str, axes: tuple[str, ...]) -> dict[str, Any] | None:
                report_path = capture_dir / report_name
                certificate_path = capture_dir / "capture_certificate.json"
                manifest = capture_dir / "asset_turntable_manifest.json"
                if not all(path.is_file() for path in (report_path, certificate_path, manifest)):
                    return None
                try:
                    paths = read_json(manifest).get("views", {}).get(case["id"], {})
                    if set(paths) != set(axes):
                        return None
                    evidence = {axis: Path(path) for axis, path in paths.items()}
                    evidence.update(report=report_path, manifest=manifest)
                    report = read_json(report_path)
                    contact = report.get("contact_sheet_path") or report.get("contact_sheet")
                    if contact:
                        evidence["contact_sheet"] = Path(contact)
                    valid, _ = verify_artifact_certificate(read_json(certificate_path), glb_path, upstream=upstream,
                                                           rules={**capture_rules, "axes": list(axes)}, evidence=evidence)
                    return report if valid else None
                except (OSError, ValueError, TypeError, KeyError):
                    return None
            def certify_capture(capture_dir: Path, report_name: str, axes: tuple[str, ...]) -> None:
                manifest = capture_dir / "asset_turntable_manifest.json"
                if not manifest.is_file():
                    return
                paths = read_json(manifest).get("views", {}).get(case["id"], {})
                if set(paths) != set(axes) or not all(Path(path).is_file() for path in paths.values()):
                    return
                evidence = {axis: Path(path) for axis, path in paths.items()}
                evidence.update(report=capture_dir / report_name, manifest=manifest)
                report = read_json(capture_dir / report_name)
                contact = report.get("contact_sheet_path") or report.get("contact_sheet")
                if contact:
                    if not Path(contact).is_file():
                        return
                    evidence["contact_sheet"] = Path(contact)
                write_json(capture_dir / "capture_certificate.json", make_artifact_certificate(
                    glb_path, upstream=upstream, rules={**capture_rules, "axes": list(axes)}, evidence=evidence))
            standard = cached_capture(standard_dir, "scene_dna_multiview_report.json", VIEW_AXES)
            if standard is None:
                standard = render_and_evaluate_generated_asset(
                    blender_bin=self.args.blender.resolve(), asset_dir=glb_path.parent, output_dir=standard_dir,
                    obj=obj, contract=_contract(audit_case), reference_image_path=Path(quality["prepared_rgba"]["path"]),
                    resolution=self.args.resolution, geometry_evidence=True)
                write_json(standard_dir / "scene_dna_multiview_report.json", standard)
                certify_capture(standard_dir, "scene_dna_multiview_report.json", VIEW_AXES)
            low = cached_capture(low_dir, "low_under_multiview_report.json", LOW_UNDER_AXES)
            if low is None:
                low = render_low_under(blender=self.args.blender.resolve(), script=script, asset_dir=glb_path.parent,
                                      output_dir=low_dir, case=case, resolution=self.args.resolution)
                write_json(low_dir / "low_under_multiview_report.json", low)
                certify_capture(low_dir, "low_under_multiview_report.json", LOW_UNDER_AXES)
            manifest_path = standard_dir / "asset_turntable_manifest.json"
            standard_paths = read_json(manifest_path).get("views", {}).get(case["id"], {}) if manifest_path.exists() else {}
            low_paths = low.get("views", {})
            standard_complete = set(standard_paths) == set(VIEW_AXES) and all(Path(path).is_file() for path in standard_paths.values())
            low_complete = set(low_paths) == set(LOW_UNDER_AXES) and all(Path(path).is_file() for path in low_paths.values())
            evidence = {f"standard_{axis}": Path(path) for axis, path in standard_paths.items() if Path(path).is_file()}
            evidence.update({f"low_under_{axis}": Path(path) for axis, path in low_paths.items() if Path(path).is_file()})
            evidence.update({"bridge_metadata": metadata_path, "source_policy": directory / "source_policy_report.json",
                             "standard_report": standard_dir / "scene_dna_multiview_report.json", "low_under_report": low_dir / "low_under_multiview_report.json"})
            for name, value in (("standard_contact_sheet", standard.get("contact_sheet_path")), ("low_under_contact_sheet", low.get("contact_sheet"))):
                if value and Path(value).is_file():
                    evidence[name] = Path(value)
            certificate = make_artifact_certificate(glb_path, upstream={"generation_contract": contract, "generation_key": contract["content_key"]},
                                                   rules={"schema": "p019-asset-audit/v1", "resolution": self.args.resolution, "standard_axes": list(VIEW_AXES), "low_under_axes": list(LOW_UNDER_AXES)}, evidence=evidence)
            write_json(directory / "audit_certificate.json", certificate)
            automated = bool(glb["ok"] and standard.get("hard_geometry_gate_passed") and low.get("ok") and standard_complete and low_complete and not control_failures)
            visual_path = directory / "visual_review.json"
            visual = read_json(visual_path) if visual_path.exists() else None
            visual_bound = bool(visual and visual.get("generation_key") == contract["content_key"] and visual.get("glb_sha256") == result["glb_binding"]["sha256"]
                                and visual.get("reviewer") and isinstance(visual.get("requirement_compliance_passed"), bool)
                                and isinstance(visual.get("geometry_multiview_passed"), bool))
            visual_passed = bool(visual_bound and visual["requirement_compliance_passed"] and visual["geometry_multiview_passed"])
            report = {"schema": "p019-case-audit/v1", "case_id": case["id"], "provider": case["provider"],
                      "status": ("accepted" if visual_passed else ("visually_rejected" if visual_bound else "visual_review_required")) if automated else "generated_but_rejected",
                      "automated_accepted": automated, "accepted": automated and visual_passed,
                      "source_policy_ok": source_gate["ok"], "glb_ok": glb["ok"], "hard_geometry_gate_passed": standard.get("hard_geometry_gate_passed", False),
                      "generation_key": contract["content_key"], "generation_contract_path": str(directory / "generation_contract.json"),
                      "glb_path": str(glb_path), "glb_sha256": result["glb_binding"]["sha256"],
                      "source_rgb": quality["source_rgb"], "prepared_rgba": quality["prepared_rgba"], "alpha_metadata": quality["alpha_metadata"],
                      "bridge_metadata_path": str(metadata_path), "source_policy_report": str(directory / "source_policy_report.json"),
                      "effective_postprocess": successful_postprocess[0] if len(successful_postprocess) == 1 else None,
                      "frozen_three_d_control_passed": not control_failures, "control_failures": control_failures,
                      "stage_times": measured_stage_times(metadata),
                      "standard_views": standard_paths, "low_under_views": low_paths,
                      "standard_camera_count": len(standard_paths), "low_under_camera_count": len(low_paths),
                      "standard_contact_sheet": standard.get("contact_sheet_path"), "low_under_contact_sheet": low.get("contact_sheet"),
                      "standard_qa_path": str(standard_dir / "scene_dna_multiview_report.json"), "low_under_qa_path": str(low_dir / "low_under_multiview_report.json"),
                      "audit_certificate_path": str(directory / "audit_certificate.json"), "visual_review_path": str(visual_path) if visual else None,
                      "visual_review_binding_ok": visual_bound, "visual_review_passed": visual_passed, "visual_checks": case["visual_checks"]}
            write_json(directory / "audit.json", report)
            return report

    def audit(self) -> dict[str, Any]:
        for case in self.cases():
            try:
                report = self.audit_one(case)
            except Exception as exc:
                report = {"case_id": case["id"], "provider": case["provider"], "status": "audit_failed", "accepted": False,
                          "automated_accepted": False, "error": f"{type(exc).__name__}: {exc}"}
                write_json(self.directory(case) / "audit.json", report)
            print(json.dumps({"case_id": case["id"], "status": report["status"]}), flush=True)
        summary = self.summary()
        write_json(self.root / "validation_summary.json", summary)
        return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--bridge-url", default="http://127.0.0.1:18082")
    parser.add_argument("--bridge-job-dir", type=Path, help="Optional bridge JobStore directory for safe lost-response reconciliation")
    parser.add_argument("--evidence-root", type=Path, help="Bridge persistent evidence directory; defaults to ROOT/evidence")
    parser.add_argument("--provider", choices=PROVIDERS)
    parser.add_argument("--case-id", action="append", help="Frozen ID; repeat to select several cases")
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--http-timeout", type=float, default=60)
    parser.add_argument("--timeout", type=float, default=86400)
    parser.add_argument("--interval", type=float, default=4)
    parser.add_argument("--wait", action="store_true", help="Sequentially wait for submitted stages before advancing")
    parser.add_argument("--watch", action="store_true", help="Poll accepted jobs until terminal or timeout")
    parser.add_argument("--stage", choices=("candidate", "trellis", "all"), default="all")
    parser.add_argument("--resume-pending", action="store_true", help="Resume provider-waiting jobs after the executor has fulfilled their image")
    parser.add_argument("--no-resume-interrupted", dest="resume_interrupted", action="store_false", default=True)
    parser.add_argument("--blender", type=Path, default=Path("/data/wsj/tools/blender-4.3.2-linux-x64/blender"))
    parser.add_argument("--resolution", type=int, default=420)
    parser.add_argument("--trellis-model-fingerprint", default=None)
    parser.add_argument("--rmbg-model-fingerprint", default=None)
    parser.add_argument("--job-id", help="Original bridge job to adopt, checked against --bridge-job-dir")
    parser.add_argument("command", choices=("freeze", "submit-candidates", "poll", "promote", "audit", "status", "adopt"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.limit < 1 or args.interval <= 0 or args.interval > 60 or args.timeout <= 0 or args.http_timeout <= 0:
        raise ValueError("Positive limits/timeouts required; interval must be at most 60 seconds")
    runner = Benchmark(args)
    if args.command == "freeze":
        result = runner.frozen
    elif args.command == "submit-candidates":
        result = runner.submit_stage("candidate")
    elif args.command == "promote":
        result = runner.submit_stage("trellis")
    elif args.command == "poll":
        result = runner.poll()
    elif args.command == "audit":
        result = runner.audit()
    elif args.command == "adopt":
        if len(runner.cases()) != 1 or args.stage not in STAGES or not args.job_id or not JOB_ID.fullmatch(args.job_id) or not args.bridge_job_dir:
            raise ValueError("Adopt requires one --case-id, --stage candidate|trellis, --job-id and --bridge-job-dir")
        directory = runner.directory(runner.cases()[0], args.stage)
        with locked(directory):
            envelope = read_json(directory / "request.json")
            result = runner._accepted(directory, envelope) or runner._reconcile(directory, envelope, args.job_id)
            if result is None:
                raise ValueError("The specified original job does not match this frozen stage request")
    else:
        result = runner.summary()
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
