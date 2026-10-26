"""Build a read-only S0 admission report for full-body controller candidates.

The audit intentionally does not download software, import candidate runtimes, load
weights, or run physics.  It records what is locally present, what is pinned, and
what must be resolved before native reproduction can start.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


REPORT_NAMES = (
    "CANDIDATE_INVENTORY.json",
    "LICENSE_AUDIT.json",
    "CONTROL_CONTRACT_GAPS.json",
    "RESOURCE_PREFLIGHT.json",
    "S0_GATE.json",
)
TOKEN = re.compile(r"\$\{([A-Z0-9_]+)\}")


class AuditConfigurationError(ValueError):
    """Raised when the frozen S0 input package is internally inconsistent."""


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise AuditConfigurationError(f"expected a JSON object: {path}")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def expand_path(value: str, variables: Mapping[str, str]) -> Path:
    missing = sorted({name for name in TOKEN.findall(value) if name not in variables})
    if missing:
        raise AuditConfigurationError(f"unknown path variable(s) {missing}: {value}")
    expanded = TOKEN.sub(lambda match: variables[match.group(1)], value)
    if TOKEN.search(expanded):
        raise AuditConfigurationError(f"unresolved path variable: {value}")
    path = Path(expanded)
    if not path.is_absolute():
        raise AuditConfigurationError(f"candidate paths must be absolute: {expanded}")
    return path


def json_pointer(value: Any, pointer: str) -> Any:
    if pointer == "":
        return value
    if not pointer.startswith("/"):
        raise AuditConfigurationError(f"invalid JSON pointer: {pointer}")
    current = value
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            try:
                current = current[int(token)]
            except (ValueError, IndexError) as exc:
                raise KeyError(pointer) from exc
        elif isinstance(current, dict) and token in current:
            current = current[token]
        else:
            raise KeyError(pointer)
    return current


def _read_text(path: Path, limit: int = 4 * 1024 * 1024) -> str:
    with path.open("rb") as stream:
        return stream.read(limit).decode("utf-8", errors="replace")


def inspect_artifact(
    artifact: Mapping[str, Any], variables: Mapping[str, str]
) -> dict[str, Any]:
    path = expand_path(str(artifact["path"]), variables)
    expected_type = artifact.get("type", "file")
    follows_symlink = path.is_symlink()
    exists = path.exists()
    type_ok = exists and (
        (expected_type == "file" and path.is_file())
        or (expected_type == "directory" and path.is_dir())
    )
    report: dict[str, Any] = {
        "id": artifact["id"],
        "kind": artifact["kind"],
        "path": str(path),
        "required_for": artifact.get("required_for", []),
        "expected_type": expected_type,
        "exists": exists,
        "type_ok": type_ok,
        "is_symlink": follows_symlink,
        "status": "missing" if not exists else "wrong_type" if not type_ok else "present",
    }
    if not type_ok:
        return report

    if path.is_file():
        report["size_bytes"] = path.stat().st_size
        report["sha256"] = sha256_file(path)
        expected_hash = artifact.get("expected_sha256")
        if expected_hash:
            report["expected_sha256"] = expected_hash
            report["hash_matches"] = report["sha256"] == expected_hash
            if not report["hash_matches"]:
                report["status"] = "hash_mismatch"
        assertions = artifact.get("json_assertions", {})
        if assertions:
            try:
                payload = read_json(path)
            except (OSError, json.JSONDecodeError, AuditConfigurationError) as exc:
                report["status"] = "invalid_json"
                report["json_error"] = str(exc)
            else:
                assertion_results = []
                for pointer, expected in sorted(assertions.items()):
                    try:
                        actual = json_pointer(payload, pointer)
                        passed = actual == expected
                    except KeyError:
                        actual, passed = None, False
                    assertion_results.append(
                        {"pointer": pointer, "expected": expected, "actual": actual, "passed": passed}
                    )
                report["json_assertions"] = assertion_results
                if not all(row["passed"] for row in assertion_results):
                    report["status"] = "content_mismatch"
    return report


def validate_inputs(
    candidates: Mapping[str, Any],
    matrix: Mapping[str, Any],
    contract_schema: Mapping[str, Any],
    contract_template: Mapping[str, Any],
    budget: Mapping[str, Any],
) -> None:
    candidate_rows = candidates.get("candidates")
    if not isinstance(candidate_rows, list) or not candidate_rows:
        raise AuditConfigurationError("candidates.json must contain a non-empty candidates list")
    candidate_ids = [row.get("id") for row in candidate_rows]
    if None in candidate_ids or len(candidate_ids) != len(set(candidate_ids)):
        raise AuditConfigurationError("candidate ids must be present and unique")
    case_ids = [row.get("id") for row in matrix.get("cases", [])]
    if not case_ids or None in case_ids or len(case_ids) != len(set(case_ids)):
        raise AuditConfigurationError("capability case ids must be present and unique")
    leaf_paths = contract_schema.get("x-required-leaf-paths")
    if not isinstance(leaf_paths, list) or not leaf_paths:
        raise AuditConfigurationError("control schema needs x-required-leaf-paths")
    if set(contract_template.get("required_leaf_paths", [])) != set(leaf_paths):
        raise AuditConfigurationError("contract template and schema leaf paths differ")
    s0 = budget.get("s0_audit")
    if not isinstance(s0, dict) or s0.get("physics_attempts") != 0 or s0.get("network_allowed") is not False:
        raise AuditConfigurationError("S0 audit must prohibit physics and network access")


def build_inventory(
    config: Mapping[str, Any], variables: Mapping[str, str], observed_at: str
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    rows = []
    artifacts_by_candidate: dict[str, list[dict[str, Any]]] = {}
    for candidate in config["candidates"]:
        artifacts = [inspect_artifact(item, variables) for item in candidate.get("artifacts", [])]
        artifacts_by_candidate[candidate["id"]] = artifacts
        missing_by_gate: dict[str, list[str]] = {}
        bad = {"missing", "wrong_type", "hash_mismatch", "invalid_json", "content_mismatch"}
        for artifact in artifacts:
            if artifact["status"] not in bad:
                continue
            for gate in artifact["required_for"]:
                missing_by_gate.setdefault(gate, []).append(artifact["id"])
        source = candidate["source"]
        pinned = bool(source.get("repository") and source.get("commit"))
        s0_ready = not missing_by_gate.get("s0_inventory") and pinned
        native_ready = not missing_by_gate.get("s1_native_reproduction") and pinned
        declared_license = candidate["distribution"]["declared_status"]
        if not s0_ready:
            status = "s0_blocked"
        elif declared_license != "reviewed_redistributable":
            status = "internal_only"
        elif not native_ready:
            status = "s1_blocked"
        else:
            status = "ready"
        rows.append(
            {
                "id": candidate["id"],
                "display_name": candidate["display_name"],
                "role": candidate["role"],
                "source": source,
                "source_identity_pinned": pinned,
                "artifacts": artifacts,
                "missing_or_invalid_by_gate": missing_by_gate,
                "s0_inventory_ready": s0_ready,
                "s1_native_reproduction_ready": native_ready,
                "distribution_status": declared_license,
                "status": status,
                "historical_claim_boundary": candidate.get("historical_claim_boundary"),
            }
        )
    return (
        {
            "schema": "embodied-s0-candidate-inventory/v1",
            "observed_at": observed_at,
            "read_only_audit": True,
            "network_accessed": False,
            "physics_attempts": 0,
            "candidates": rows,
        },
        artifacts_by_candidate,
    )


def build_license_audit(
    config: Mapping[str, Any], variables: Mapping[str, str], observed_at: str
) -> dict[str, Any]:
    rows = []
    for candidate in config["candidates"]:
        scopes = []
        for item in candidate.get("licenses", []):
            path = expand_path(item["evidence_path"], variables)
            exists = path.is_file()
            text = _read_text(path) if exists else ""
            markers = [
                {"marker": marker, "found": marker.casefold() in text.casefold()}
                for marker in item.get("expected_markers", [])
            ]
            evidence_status = (
                "absent"
                if not exists
                else "markers_matched"
                if markers and all(row["found"] for row in markers)
                else "present_unverified"
            )
            scopes.append(
                {
                    "scope": item["scope"],
                    "evidence_path": str(path),
                    "evidence_exists": exists,
                    "evidence_sha256": sha256_file(path) if exists else None,
                    "markers": markers,
                    "evidence_status": evidence_status,
                    "declared_status": item["declared_status"],
                    "manual_review_required": item.get("manual_review_required", True),
                    "notes": item.get("notes"),
                }
            )
        distribution = candidate["distribution"]
        rows.append(
            {
                "candidate_id": candidate["id"],
                "scopes": scopes,
                "declared_distribution_status": distribution["declared_status"],
                "redistribution_ready": distribution["declared_status"] == "reviewed_redistributable",
                "decision_basis": distribution["decision_basis"],
            }
        )
    return {
        "schema": "embodied-s0-license-audit/v1",
        "observed_at": observed_at,
        "legal_conclusion": False,
        "policy": "Evidence presence never upgrades a license decision automatically.",
        "candidates": rows,
    }


def _evidence_result(
    evidence: Mapping[str, Any], variables: Mapping[str, str]
) -> dict[str, Any]:
    path = expand_path(evidence["path"], variables)
    result = {
        "path": str(path),
        "pointer": evidence.get("pointer", ""),
        "exists": path.is_file(),
        "status": "missing",
    }
    if not path.is_file():
        return result
    result["sha256"] = sha256_file(path)
    try:
        payload = read_json(path)
        actual = json_pointer(payload, evidence.get("pointer", ""))
    except (OSError, json.JSONDecodeError, AuditConfigurationError, KeyError) as exc:
        result["status"] = "unreadable_or_pointer_missing"
        result["error"] = str(exc)
        return result
    result["status"] = "present"
    result["value_type"] = type(actual).__name__
    result["nonempty"] = actual not in (None, "", [], {})
    if not result["nonempty"]:
        result["status"] = "empty"
    return result


def build_contract_gaps(
    config: Mapping[str, Any],
    contract_schema: Mapping[str, Any],
    variables: Mapping[str, str],
    observed_at: str,
) -> dict[str, Any]:
    required = contract_schema["x-required-leaf-paths"]
    rows = []
    for candidate in config["candidates"]:
        declared = candidate.get("contract_evidence", {})
        fields = []
        for field in required:
            evidence_rows = [
                _evidence_result(item, variables) for item in declared.get(field, [])
            ]
            complete = bool(evidence_rows) and all(row["status"] == "present" for row in evidence_rows)
            fields.append(
                {
                    "field": field,
                    "complete": complete,
                    "evidence": evidence_rows,
                }
            )
        missing = [row["field"] for row in fields if not row["complete"]]
        rows.append(
            {
                "candidate_id": candidate["id"],
                "complete_field_count": len(required) - len(missing),
                "required_field_count": len(required),
                "contract_complete": not missing,
                "missing_fields": missing,
                "fields": fields,
            }
        )
    return {
        "schema": "embodied-s0-control-contract-gaps/v1",
        "observed_at": observed_at,
        "required_leaf_paths": required,
        "candidates": rows,
    }


def _meminfo() -> dict[str, int]:
    values: dict[str, int] = {}
    try:
        lines = Path("/proc/meminfo").read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        key, _, tail = line.partition(":")
        fields = tail.strip().split()
        if fields and fields[0].isdigit():
            multiplier = 1024 if len(fields) > 1 and fields[1].lower() == "kb" else 1
            values[key] = int(fields[0]) * multiplier
    return values


def build_resource_preflight(
    budget: Mapping[str, Any], output_dir: Path, observed_at: str
) -> dict[str, Any]:
    probe = output_dir if output_dir.exists() else output_dir.parent
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    disk = os.statvfs(probe)
    memory = _meminfo()
    return {
        "schema": "embodied-s0-resource-preflight/v1",
        "observed_at": observed_at,
        "host_snapshot_is_not_a_reservation": True,
        "cpu_logical_count": os.cpu_count(),
        "memory": {
            "total_bytes": memory.get("MemTotal"),
            "available_bytes": memory.get("MemAvailable"),
        },
        "filesystem": {
            "probe_path": str(probe),
            "total_bytes": disk.f_blocks * disk.f_frsize,
            "available_bytes": disk.f_bavail * disk.f_frsize,
        },
        "gpu": {
            "queried": False,
            "reason": "S0 is metadata-only; live GPU admission belongs immediately before S1 execution.",
        },
        "budget": budget,
        "s0_budget_valid": (
            budget["s0_audit"]["physics_attempts"] == 0
            and budget["s0_audit"]["network_allowed"] is False
            and budget["s0_audit"]["gpu_required"] is False
        ),
    }


def build_gate(
    inventory: Mapping[str, Any],
    licenses: Mapping[str, Any],
    gaps: Mapping[str, Any],
    resources: Mapping[str, Any],
    matrix: Mapping[str, Any],
    input_bindings: Mapping[str, str],
    observed_at: str,
) -> dict[str, Any]:
    candidates = inventory["candidates"]
    s0_ready = [row["id"] for row in candidates if row["s0_inventory_ready"]]
    s0_blocked = [row["id"] for row in candidates if not row["s0_inventory_ready"]]
    native_ready = [row["id"] for row in candidates if row["s1_native_reproduction_ready"]]
    native_blocked = [row["id"] for row in candidates if not row["s1_native_reproduction_ready"]]
    license_explicit = all(
        row["declared_distribution_status"]
        in {"reviewed_redistributable", "internal_only", "unresolved_internal_only"}
        for row in licenses["candidates"]
    )
    matrix_ready = bool(matrix.get("cases")) and all(
        case.get("budget", {}).get("max_attempts", 0) > 0 for case in matrix["cases"]
    )
    pass_conditions = {
        "all_candidate_identities_pinned": all(row["source_identity_pinned"] for row in candidates),
        "all_s0_inventory_artifacts_ready": not s0_blocked,
        "license_status_explicit_for_every_candidate": license_explicit,
        "capability_matrix_frozen_and_bounded": matrix_ready,
        "control_contract_template_defined": bool(gaps["required_leaf_paths"]),
        "s0_resource_policy_valid": resources["s0_budget_valid"],
    }
    next_actions = []
    for row in candidates:
        if not row["source_identity_pinned"]:
            next_actions.append(
                {"candidate_id": row["id"], "action": "select_and_record_a_pinned_upstream_commit"}
            )
        if not row["s0_inventory_ready"]:
            next_actions.append(
                {
                    "candidate_id": row["id"],
                    "action": "stage_missing_s0_admission_artifacts",
                    "missing": row["missing_or_invalid_by_gate"].get("s0_inventory", []),
                }
            )
        if not row["s1_native_reproduction_ready"]:
            next_actions.append(
                {
                    "candidate_id": row["id"],
                    "action": "stage_missing_native_artifacts_without_running_physics",
                    "missing": row["missing_or_invalid_by_gate"].get("s1_native_reproduction", []),
                }
            )
    for row in gaps["candidates"]:
        if not row["contract_complete"]:
            next_actions.append(
                {
                    "candidate_id": row["candidate_id"],
                    "action": "extract_control_contract_from_native_source",
                    "missing_fields": row["missing_fields"],
                }
            )
    return {
        "schema": "embodied-s0-gate/v1",
        "observed_at": observed_at,
        "audit_implemented": True,
        "s0_exit_passed": all(pass_conditions.values()),
        "pass_conditions": pass_conditions,
        "s0_inventory_ready_candidates": s0_ready,
        "s0_inventory_blocked_candidates": s0_blocked,
        "native_reproduction_ready_candidates": native_ready,
        "native_reproduction_blocked_candidates": native_blocked,
        "next_actions": next_actions,
        "input_bindings": dict(input_bindings),
        "reports": list(REPORT_NAMES[:-1]),
        "physics_attempts": 0,
        "network_accessed_during_audit": False,
        "network_scope_note": "Candidate acquisition is a separate, recorded staging step.",
        "long_run_authorized_or_started": False,
        "production_accepted": False,
        "learning_validated": False,
    }


def write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def copy_file_atomic(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    with source.open("rb") as input_stream, temporary.open("wb") as output_stream:
        shutil.copyfileobj(input_stream, output_stream)
        output_stream.flush()
        os.fsync(output_stream.fileno())
    os.replace(temporary, destination)


def run_audit(
    config_dir: Path, output_dir: Path, observed_at: str | None = None
) -> dict[str, dict[str, Any]]:
    paths = {
        "candidates": config_dir / "candidates.json",
        "matrix": config_dir / "capability_matrix.json",
        "contract_schema": config_dir / "control_contract.schema.json",
        "contract_template": config_dir / "control_contract.template.json",
        "budget": config_dir / "resource_budget.json",
    }
    payloads = {name: read_json(path) for name, path in paths.items()}
    validate_inputs(
        payloads["candidates"],
        payloads["matrix"],
        payloads["contract_schema"],
        payloads["contract_template"],
        payloads["budget"],
    )
    variables = dict(payloads["candidates"].get("path_variables", {}))
    variables.setdefault("S0_RUN", str(output_dir))
    stamp = observed_at or datetime.now(timezone.utc).isoformat()
    input_bindings = {str(path): sha256_file(path) for path in paths.values()}
    frozen_input_paths = {}
    for name, source in paths.items():
        destination = output_dir / "inputs" / source.name
        copy_file_atomic(source, destination)
        frozen_hash = sha256_file(destination)
        if frozen_hash != input_bindings[str(source)]:
            raise RuntimeError(f"frozen input copy differs from source: {source}")
        frozen_input_paths[name] = {"path": str(destination), "sha256": frozen_hash}
    inventory, _ = build_inventory(payloads["candidates"], variables, stamp)
    licenses = build_license_audit(payloads["candidates"], variables, stamp)
    gaps = build_contract_gaps(
        payloads["candidates"], payloads["contract_schema"], variables, stamp
    )
    resources = build_resource_preflight(payloads["budget"], output_dir, stamp)
    gate = build_gate(
        inventory,
        licenses,
        gaps,
        resources,
        payloads["matrix"],
        input_bindings,
        stamp,
    )
    gate["frozen_inputs"] = frozen_input_paths
    reports = {
        REPORT_NAMES[0]: inventory,
        REPORT_NAMES[1]: licenses,
        REPORT_NAMES[2]: gaps,
        REPORT_NAMES[3]: resources,
        REPORT_NAMES[4]: gate,
    }
    for name, report in reports.items():
        report["content_sha256_excluding_this_field"] = canonical_sha256(report)
        write_json_atomic(output_dir / name, report)
    emitted_paths = [output_dir / name for name in REPORT_NAMES]
    emitted_paths.extend(output_dir / "inputs" / path.name for path in paths.values())
    output_bytes = sum(path.stat().st_size for path in emitted_paths)
    if output_bytes > payloads["budget"]["s0_audit"]["max_output_bytes"]:
        raise RuntimeError(
            f"S0 output exceeds frozen limit: {output_bytes} > "
            f"{payloads['budget']['s0_audit']['max_output_bytes']}"
        )
    return reports


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    default_configs = Path(__file__).resolve().parent / "configs"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-dir", type=Path, default=default_configs)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--observed-at")
    parser.add_argument(
        "--require-s0-pass",
        action="store_true",
        help="return a nonzero status when candidate staging is incomplete",
    )
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    reports = run_audit(args.config_dir, args.output_dir, args.observed_at)
    passed = reports["S0_GATE.json"]["s0_exit_passed"]
    print(
        json.dumps(
            {
                "output_dir": str(args.output_dir),
                "s0_exit_passed": passed,
                "native_reproduction_ready_candidates": reports["S0_GATE.json"][
                    "native_reproduction_ready_candidates"
                ],
                "native_reproduction_blocked_candidates": reports["S0_GATE.json"][
                    "native_reproduction_blocked_candidates"
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 2 if args.require_s0_pass and not passed else 0


if __name__ == "__main__":
    raise SystemExit(main())

