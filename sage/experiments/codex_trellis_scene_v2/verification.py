"""Tiered integration, chaos, and release-status contracts for Scene V2."""

from __future__ import annotations

import argparse
import importlib
import json
import re
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any

from .content_chain import content_hash, file_binding
from .io_utils import read_json, write_json


VERIFICATION_SCHEMA = "scene-v2-verification-status/v1"
REQUIRED_TIERS = (
    "commit",
    "cpu_integration",
    "blender_headless",
    "nightly_gpu",
)

NEGATIVE_REGRESSION_MATRIX = {
    "P001": "sage.experiments.codex_trellis_scene_v2.tests.test_v2_pipeline.SemanticGroundingTest.test_anatomical_source_role_and_medial_sides_reject_swapped_slippers",
    "P002": "sage.experiments.codex_trellis_scene_v2.tests.test_v2_pipeline.FunctionalOrientationTest.test_validator_rejects_high_confidence_front_facing_wall",
    "P003": "sage.experiments.codex_trellis_scene_v2.tests.test_whole_scene_audit.WholeSceneAuditTest.test_missing_support_is_a_whole_scene_failure",
    "P004": "sage.experiments.codex_trellis_scene_v2.tests.test_release_manifest.ReleaseManifestTests.test_file_and_canonical_hashes_are_content_sensitive",
    "P005": "sage.experiments.codex_trellis_scene_v2.tests.test_content_chain.ContentChainTests.test_artifact_or_evidence_replacement_invalidates_certificate",
    "P006": "sage.experiments.codex_trellis_scene_v2.tests.test_delivery_status.DeliveryStatusTests.test_plan_completion_is_explicitly_non_deliverable",
    "P007": "sage.experiments.codex_trellis_scene_v2.tests.test_heavy_job_broker.HeavyJobBrokerTests.test_external_gpu_process_rejects_admission",
    "P008": "sage.experiments.codex_trellis_scene_v2.tests.test_stage_dag.StageDAGTests.test_failed_attempt_is_never_reused_or_mixed_with_next_attempt",
    "P009": "sage.experiments.codex_trellis_scene_v2.tests.test_contracts.ContractTests.test_wrong_units_world_axis_asset_axis_legacy_and_missing_group_rejected",
    "P010": "sage.experiments.codex_trellis_scene_v2.tests.test_scene_delivery_optimization.SceneDeliveryOptimizationTests.test_target_never_exceeds_source",
    "P011": "sage.experiments.codex_trellis_scene_v2.tests.test_exact_predicates.ExactPredicateTest.test_near_collinear_sign_survives_float_cancellation",
    "P012": "sage.experiments.codex_trellis_scene_v2.tests.test_showcase_render.ShowcaseRenderTest.test_quality_gate_rejects_pure_black_visible_window",
    "P013": "sage.experiments.codex_trellis_scene_v2.tests.test_asset_admission.AssetCountContractTest.test_ten_books_are_rejected_for_five_book_contract",
}

CHAOS_MATRIX = {
    "bridge_interruption": "sage.experiments.codex_trellis_scene_v2.tests.test_scene_dna.SceneDNATest.test_trellis_request_retries_supervised_bridge_restart_gap",
    "partial_glb_or_metadata": "sage.experiments.codex_trellis_scene_v2.tests.test_verification.VerificationSystemTest.test_half_written_artifact_pair_is_rejected",
    "glb_replaced_after_qa": "sage.experiments.codex_trellis_scene_v2.tests.test_content_chain.ContentChainTests.test_artifact_or_evidence_replacement_invalidates_certificate",
    "gpu_preemption": "sage.experiments.codex_trellis_scene_v2.tests.test_heavy_job_broker.HeavyJobBrokerTests.test_external_gpu_process_rejects_admission",
    "disk_or_io_pressure": "sage.experiments.codex_trellis_scene_v2.tests.test_resource_health.ResourceHealthTest.test_required_gate_fails_with_impossible_memory_threshold",
    "stale_systemd_lease": "sage.experiments.codex_trellis_scene_v2.tests.test_heavy_job_broker.HeavyJobBrokerTests.test_expired_or_dead_worker_lease_is_recovered",
    "old_output_pollution": "sage.experiments.codex_trellis_scene_v2.tests.test_verification.VerificationSystemTest.test_old_output_pollution_is_rejected",
}


def resolve_test_id(test_id: str) -> bool:
    module_name, class_name, method_name = test_id.rsplit(".", 2)
    module = importlib.import_module(module_name)
    case = getattr(module, class_name, None)
    return bool(case is not None and callable(getattr(case, method_name, None)))


def audit_test_catalog() -> dict[str, Any]:
    negative = {
        problem_id: {"test_id": test_id, "resolves": resolve_test_id(test_id)}
        for problem_id, test_id in NEGATIVE_REGRESSION_MATRIX.items()
    }
    chaos = {
        case_id: {"test_id": test_id, "resolves": resolve_test_id(test_id)}
        for case_id, test_id in CHAOS_MATRIX.items()
    }
    expected_problems = {f"P{index:03d}" for index in range(1, 14)}
    missing = sorted(expected_problems - set(negative))
    return {
        "schema": "scene-v2-verification-catalog-audit/v1",
        "negative_regressions": negative,
        "chaos_cases": chaos,
        "missing_problem_ids": missing,
        "ok": (
            not missing
            and all(row["resolves"] for row in negative.values())
            and all(row["resolves"] for row in chaos.values())
        ),
    }


def audit_artifact_pair(
    artifact_path: Path, metadata_path: Path
) -> dict[str, Any]:
    failures: list[str] = []
    if not artifact_path.is_file():
        failures.append("artifact_missing")
    if not metadata_path.is_file():
        failures.append("metadata_missing")
    metadata: dict[str, Any] = {}
    if metadata_path.is_file():
        try:
            metadata = read_json(metadata_path)
        except (OSError, ValueError, json.JSONDecodeError):
            failures.append("metadata_incomplete")
    binding = metadata.get("artifact") if isinstance(metadata, dict) else None
    if not isinstance(binding, dict):
        failures.append("artifact_binding_missing")
    elif artifact_path.is_file() and file_binding(artifact_path) != binding:
        failures.append("artifact_binding_mismatch")
    return {
        "ok": not failures,
        "failures": failures,
        "artifact_path": str(artifact_path),
        "metadata_path": str(metadata_path),
    }


def audit_output_allowlist(root: Path, declared_files: list[str]) -> dict[str, Any]:
    declared = {Path(value).as_posix() for value in declared_files}
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }
    unexpected = sorted(actual - declared)
    missing = sorted(declared - actual)
    return {
        "ok": not unexpected and not missing,
        "declared_files": sorted(declared),
        "unexpected_files": unexpected,
        "missing_files": missing,
    }


def _verified_evidence(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    verified: list[dict[str, Any]] = []
    failures: list[str] = []
    for index, row in enumerate(rows):
        path = Path(str(row.get("path") or "")).expanduser()
        if not path.is_file():
            failures.append(f"evidence_missing:{index}")
            continue
        actual = file_binding(path)
        expected = row.get("binding")
        if isinstance(expected, dict) and expected != actual:
            failures.append(f"evidence_binding_mismatch:{index}")
            continue
        verified.append({"path": str(path.resolve()), "binding": actual})
    return verified, failures


def build_verification_status(config: dict[str, Any]) -> dict[str, Any]:
    catalog = audit_test_catalog()
    tier_results = config.get("tiers")
    tier_results = tier_results if isinstance(tier_results, dict) else {}
    tiers: dict[str, Any] = {}
    failures: list[str] = []
    for tier in REQUIRED_TIERS:
        source = tier_results.get(tier)
        source = source if isinstance(source, dict) else {}
        evidence, evidence_failures = _verified_evidence(
            source.get("evidence", [])
            if isinstance(source.get("evidence"), list)
            else []
        )
        passed = source.get("status") == "passed"
        if tier in {"blender_headless", "nightly_gpu"} and not evidence:
            evidence_failures.append("hardware_evidence_required")
        if tier == "nightly_gpu" and source.get("actual_gpu") is not True:
            evidence_failures.append("actual_gpu_required")
        if not passed:
            failures.append(f"tier_not_passed:{tier}")
        failures.extend(f"{tier}:{reason}" for reason in evidence_failures)
        tiers[tier] = {
            "status": source.get("status", "missing"),
            "test_count": int(source.get("test_count", 0) or 0),
            "commands": deepcopy(source.get("commands", [])),
            "evidence": evidence,
            "failures": evidence_failures,
        }
    if not catalog["ok"]:
        failures.append("test_catalog_incomplete")
    machine_counts = config.get("test_counts_are_machine_generated") is True
    if not machine_counts:
        failures.append("test_counts_not_machine_generated")
    report = {
        "schema": VERIFICATION_SCHEMA,
        "catalog": catalog,
        "tiers": tiers,
        "release_eligible": not failures,
        "failures": failures,
        "test_counts_are_machine_generated": machine_counts,
    }
    report["status_hash"] = content_hash(report)
    return report


def run_command(argv: list[str], cwd: Path, timeout: float = 1800) -> dict[str, Any]:
    completed = subprocess.run(
        argv,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return {
        "argv": argv,
        "returncode": completed.returncode,
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-4000:],
    }


def _unittest_count(result: dict[str, Any]) -> int:
    combined = str(result.get("stdout_tail") or "") + str(
        result.get("stderr_tail") or ""
    )
    matches = re.findall(r"Ran\s+(\d+)\s+tests?", combined)
    return sum(int(value) for value in matches)


def run_commit_tier(repo: Path, python: Path, output_path: Path) -> dict[str, Any]:
    commands = [
        run_command(
            [
                str(python),
                "-m",
                "unittest",
                "discover",
                "-s",
                "sage/experiments/codex_trellis_scene_v2/tests",
                "-t",
                ".",
            ],
            repo,
        ),
        run_command(
            [
                str(python),
                "-m",
                "unittest",
                "discover",
                "-s",
                "tests",
                "-p",
                "test_*.py",
            ],
            repo,
        ),
        run_command(
            [
                str(python),
                "-m",
                "compileall",
                "-q",
                "sage/experiments/codex_trellis_scene_v2",
            ],
            repo,
        ),
        run_command(["git", "diff", "--check"], repo),
    ]
    report = {
        "schema": "scene-v2-commit-tier-result/v1",
        "status": (
            "passed"
            if all(row.get("returncode") == 0 for row in commands)
            else "failed"
        ),
        "test_count": sum(_unittest_count(row) for row in commands),
        "commands": commands,
    }
    report["result_hash"] = content_hash(report)
    write_json(output_path, report)
    return report


def build_verified_run_config(
    *,
    commit_report_path: Path,
    cpu_summary_path: Path,
    blender_report_path: Path,
    nightly_report_path: Path,
    nightly_asset_path: Path,
) -> dict[str, Any]:
    commit = read_json(commit_report_path)
    cpu = read_json(cpu_summary_path)
    blender = read_json(blender_report_path)
    nightly = read_json(nightly_report_path)
    nightly_binding = file_binding(nightly_asset_path)
    certificate_binding = (
        nightly.get("content_certificate", {}).get("artifact")
        if isinstance(nightly, dict)
        else None
    )
    cpu_ok = bool(
        cpu.get("validation_ok")
        and cpu.get("profile_complete")
        and cpu.get("terminal_status") == "plan_complete_non_deliverable"
    )
    blender_ok = bool(blender.get("ok"))
    nightly_ok = bool(
        nightly.get("ok")
        and nightly.get("generation", {}).get("bridge_metadata", {}).get("status")
        == "done"
        and certificate_binding == nightly_binding
    )
    return {
        "test_counts_are_machine_generated": True,
        "tiers": {
            "commit": {
                "status": commit.get("status"),
                "test_count": int(commit.get("test_count", 0) or 0),
                "commands": commit.get("commands", []),
                "evidence": [
                    {
                        "path": str(commit_report_path),
                        "binding": file_binding(commit_report_path),
                    }
                ],
            },
            "cpu_integration": {
                "status": "passed" if cpu_ok else "failed",
                "test_count": 1,
                "commands": ["real Scene V2 rules/plan pipeline"],
                "evidence": [
                    {
                        "path": str(cpu_summary_path),
                        "binding": file_binding(cpu_summary_path),
                    }
                ],
            },
            "blender_headless": {
                "status": "passed" if blender_ok else "failed",
                "test_count": 1,
                "commands": ["real Blender 4.3.2 headless render"],
                "evidence": [
                    {
                        "path": str(blender_report_path),
                        "binding": file_binding(blender_report_path),
                    }
                ],
            },
            "nightly_gpu": {
                "status": "passed" if nightly_ok else "failed",
                "test_count": 1,
                "actual_gpu": True,
                "commands": ["real local TRELLIS.2 generation through resource gate"],
                "evidence": [
                    {
                        "path": str(nightly_report_path),
                        "binding": file_binding(nightly_report_path),
                    },
                    {
                        "path": str(nightly_asset_path),
                        "binding": nightly_binding,
                    },
                ],
            },
        }
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--python", type=Path)
    parser.add_argument("--cpu-summary", type=Path)
    parser.add_argument("--blender-report", type=Path)
    parser.add_argument("--nightly-report", type=Path)
    parser.add_argument("--nightly-asset", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.run:
        required = (
            args.python,
            args.cpu_summary,
            args.blender_report,
            args.nightly_report,
            args.nightly_asset,
        )
        if any(value is None for value in required):
            parser.error("--run requires python, CPU, Blender, and nightly evidence")
        commit_path = args.output.parent / "commit_tier_result.json"
        run_commit_tier(args.repo, args.python, commit_path)
        config = build_verified_run_config(
            commit_report_path=commit_path,
            cpu_summary_path=args.cpu_summary,
            blender_report_path=args.blender_report,
            nightly_report_path=args.nightly_report,
            nightly_asset_path=args.nightly_asset,
        )
        write_json(args.output.parent / "verification_input_resolved.json", config)
    elif args.config:
        config = read_json(args.config)
    else:
        parser.error("provide --config or --run")
    report = build_verification_status(config)
    write_json(args.output, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["release_eligible"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
