from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import numpy as np

from .detail_face_localizer import (
    apply_generic_connected_platform_gate,
    broad_low_object_candidates,
    localize_lower_platform_faces,
    tessellation_aware_platform_repair_policy,
)
from .detail_repair_runner import _repair_localized_region
from .assets import generate_trellis_asset
from .detail_repair_agent import diagnose_detail_failures, verify_repair
from .io_utils import read_json, write_json
from .scene_dna_multiview import render_and_evaluate_generated_asset
from .scene_dna_blind_review import export_offline_bundle, prepare_blind_bundle


ASSET_SPLITS: dict[str, tuple[dict[str, Any], ...]] = {
    "development": (
        {"asset_id": "desk_warm_oak_001", "shape_profile": "skeletal_support"},
        {"asset_id": "table_lamp_cream_001", "shape_profile": "slender_radial"},
        {"asset_id": "mug_white_001", "shape_profile": "general_object"},
    ),
    "heldout": (
        {"asset_id": "office_chair_black_mesh_001", "shape_profile": "skeletal_support"},
        {"asset_id": "potted_plant_white_001", "shape_profile": "organic_branching"},
        {"asset_id": "wardrobe_warm_oak_001", "shape_profile": "compact_orthogonal"},
    ),
}
SEEDS = (314159, 271828)
VARIANT_BY_SEED = {314159: "cylinder", 271828: "box"}
FROZEN_GATES = {
    "minimum_macro_face_precision": 0.95,
    "minimum_macro_face_recall": 0.90,
    "minimum_repair_success_rate": 0.90,
    "maximum_protected_face_removal_rate": 0.001,
    "maximum_clean_false_trigger_rate": 0.0,
    "maximum_hard_regression_commit_count": 0,
}
NATURAL_SEEDS = (626262, 737373)
NATURAL_REFERENCE_AXIS = "plus_y"


def _sha256_json(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def frozen_protocol(manifest_path: Path) -> dict[str, Any]:
    cases = []
    for split, assets in ASSET_SPLITS.items():
        for row in assets:
            for seed in SEEDS:
                cases.append(
                    {
                        "split": split,
                        "asset_id": row["asset_id"],
                        "seed": seed,
                        "variant": VARIANT_BY_SEED[seed],
                    }
                )
    protocol = {
        "schema": "scene_detail_heldout_protocol_v1",
        "manifest_path": str(manifest_path.resolve()),
        "development_assets": [row["asset_id"] for row in ASSET_SPLITS["development"]],
        "heldout_assets": [row["asset_id"] for row in ASSET_SPLITS["heldout"]],
        "seeds": list(SEEDS),
        "cases": cases,
        "gates": FROZEN_GATES,
        "rules": [
            "development cases may be inspected before the heldout run",
            "heldout thresholds and case membership are frozen before heldout rendering",
            "the slipper and bookcase development controls are excluded",
            "the in-flight SceneDNA blind-review bundle and responses are not inputs",
            "a blind questionnaire may be exported only after all heldout automatic gates pass",
        ],
    }
    protocol["protocol_sha256"] = _sha256_json(protocol)
    return protocol


def frozen_natural_protocol(manifest_path: Path) -> dict[str, Any]:
    cases = [
        {"asset_id": row["asset_id"], "seed": seed}
        for row in ASSET_SPLITS["heldout"]
        for seed in NATURAL_SEEDS
    ]
    protocol = {
        "schema": "scene_detail_natural_protocol_v2",
        "manifest_path": str(manifest_path.resolve()),
        "cases": cases,
        "generation": {
            "pipeline_type": "512",
            "steps": 8,
            "texture_size": 1024,
            "decimation_target": 100000,
            "reference_source": "clean curated-asset turntable; no in-flight questionnaire image",
            "reference_axis": NATURAL_REFERENCE_AXIS,
            "reference_axis_rationale": (
                "the curated asset convention treats plus_y as the canonical front; "
                "plus_x is a side view and is excluded"
            ),
        },
        "gates": {
            "minimum_generation_completion_rate": 1.0,
            "maximum_hard_regression_commit_count": 0,
            "maximum_failed_case_count": 0,
        },
        "rules": [
            "all cases and seeds are frozen before requesting TRELLIS outputs",
            "the canonical plus_y reference is frozen before generation",
            "an asset is repaired only when existing measured evidence triggers a platform action",
            "non-platform defects are reported but do not authorize an unrelated deletion",
            "no blind questionnaire is exported unless at least one natural repair passes all gates",
        ],
    }
    protocol["protocol_sha256"] = _sha256_json(protocol)
    return protocol


def summarize_rows(rows: list[dict[str, Any]], gates: dict[str, float]) -> dict[str, Any]:
    evaluated = [row for row in rows if row.get("status") == "evaluated"]
    precision = [float(row["localization_face_precision"]) for row in evaluated]
    recall = [float(row["localization_face_recall"]) for row in evaluated]
    protected_removed = sum(int(row["protected_face_removed_count"]) for row in evaluated)
    protected_total = sum(int(row["protected_source_face_count"]) for row in evaluated)
    clean_by_asset: dict[str, bool] = {}
    for row in evaluated:
        clean_by_asset[str(row["asset_id"])] = bool(row["clean_false_trigger"])
    metrics = {
        "case_count": len(rows),
        "evaluated_case_count": len(evaluated),
        "failed_case_count": len(rows) - len(evaluated),
        "category_count": len({row.get("category") for row in evaluated}),
        "seed_count": len({row.get("seed") for row in evaluated}),
        "macro_face_precision": round(sum(precision) / max(1, len(precision)), 6),
        "macro_face_recall": round(sum(recall) / max(1, len(recall)), 6),
        "repair_success_rate": round(
            sum(bool(row.get("repair_success")) for row in evaluated)
            / max(1, len(evaluated)),
            6,
        ),
        "protected_face_removed_count": protected_removed,
        "protected_source_face_count": protected_total,
        "protected_face_removal_rate": round(
            protected_removed / max(1, protected_total), 9
        ),
        "clean_asset_count": len(clean_by_asset),
        "clean_false_trigger_count": sum(clean_by_asset.values()),
        "clean_false_trigger_rate": round(
            sum(clean_by_asset.values()) / max(1, len(clean_by_asset)), 6
        ),
        "hard_regression_commit_count": sum(
            bool(row.get("hard_regression_committed")) for row in evaluated
        ),
    }
    checks = {
        "all_cases_evaluated": metrics["failed_case_count"] == 0,
        "face_precision": metrics["macro_face_precision"]
        >= float(gates["minimum_macro_face_precision"]),
        "face_recall": metrics["macro_face_recall"]
        >= float(gates["minimum_macro_face_recall"]),
        "repair_success": metrics["repair_success_rate"]
        >= float(gates["minimum_repair_success_rate"]),
        "protected_face_safety": metrics["protected_face_removal_rate"]
        <= float(gates["maximum_protected_face_removal_rate"]),
        "clean_abstention": metrics["clean_false_trigger_rate"]
        <= float(gates["maximum_clean_false_trigger_rate"]),
        "hard_regression": metrics["hard_regression_commit_count"]
        <= int(gates["maximum_hard_regression_commit_count"]),
    }
    return {"metrics": metrics, "gate_checks": checks, "passed": all(checks.values())}


def _run_injector(
    *,
    blender_bin: Path,
    source_glb: Path,
    output_glb: Path,
    report_path: Path,
    seed: int,
    variant: str,
) -> dict[str, Any]:
    script = Path(__file__).resolve().parents[2] / "scripts" / "blender_inject_synthetic_detail_defect.py"
    command = [
        str(blender_bin), "--background", "--python-exit-code", "1",
        "--python", str(script), "--",
        "--input-glb", str(source_glb), "--output-glb", str(output_glb),
        "--report", str(report_path), "--seed", str(seed), "--variant", variant,
    ]
    completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=900)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    (report_path.parent / "blender_inject_stdout.txt").write_text(completed.stdout, encoding="utf-8")
    (report_path.parent / "blender_inject_stderr.txt").write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0 or not report_path.is_file():
        raise RuntimeError(f"synthetic defect injection failed: {completed.stderr[-1200:]}")
    return read_json(report_path)


def _contract(object_id: str, entry: dict[str, Any], shape_profile: str) -> dict[str, Any]:
    return {
        "schema": "scene_detail_heldout_contract_v1",
        "contract_hash": _sha256_json({"object_id": object_id, "asset": entry["asset_id"]}),
        "selection_policy": {"minimum_harmony_score": 0.55},
        "global_profile": {"desired_tags": [{"tag": item} for item in entry.get("styles", [])]},
        "object_profiles": {
            object_id: {
                "individuality_tags": list(entry.get("styles", [])),
                "semantic_form_contract": {
                    "identity": str(entry.get("category") or "object"),
                    "shape_profile": shape_profile,
                },
            }
        },
    }


def _object_plan(object_id: str, entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": object_id,
        "category": str(entry.get("category") or "object"),
        "dimensions": dict(entry.get("dimensions") or {}),
        "requested_dimensions": dict(entry.get("dimensions") or {}),
        "asset_axis_to_z": int(entry.get("asset_axis_to_z", 2)),
        "asset_local_yaw_offset_degrees": float(entry.get("asset_local_yaw_offset_degrees", 0.0)),
    }


def _ground_truth_from_face_table(manifest: dict[str, Any], object_id: str) -> tuple[str, set[int], int]:
    evidence = manifest["geometry_evidence"][object_id]
    names = [str(item) for item in evidence["object_names"]]
    defect_indices = [index for index, name in enumerate(names) if name.startswith("SyntheticBroadLowPlatform")]
    if len(defect_indices) != 1:
        raise RuntimeError(f"expected one injected defect object, got {names}")
    defect_index = defect_indices[0]
    table = np.load(evidence["face_table_path"])
    object_index = np.asarray(table["object_index"], dtype=np.int32)
    polygon_index = np.asarray(table["polygon_index"], dtype=np.int32)
    ids = set(int(item) for item in polygon_index[object_index == defect_index].tolist())
    return names[defect_index], ids, int(np.count_nonzero(object_index != defect_index))


def run_split(
    *,
    split: str,
    manifest_path: Path,
    output_dir: Path,
    blender_bin: Path,
    resolution: int = 256,
    evidence_resolution: int = 96,
) -> dict[str, Any]:
    protocol = frozen_protocol(manifest_path)
    protocol_path = output_dir / "FROZEN_PROTOCOL.json"
    output_dir.mkdir(parents=True, exist_ok=True)
    if protocol_path.exists():
        existing = read_json(protocol_path)
        if existing.get("protocol_sha256") != protocol.get("protocol_sha256"):
            raise RuntimeError("existing frozen heldout protocol does not match current protocol")
    else:
        write_json(protocol_path, protocol)
    manifest = read_json(manifest_path)
    entries = {str(row["asset_id"]): row for row in manifest.get("assets", [])}
    library_root = manifest_path.parent
    rows: list[dict[str, Any]] = []
    clean_cache: dict[str, dict[str, Any]] = {}
    for asset_spec in ASSET_SPLITS[split]:
        asset_id = str(asset_spec["asset_id"])
        entry = entries[asset_id]
        source_glb = (library_root / str(entry["glb_path"])).resolve()
        clean_id = f"clean_{asset_id}"
        clean_dir = output_dir / "clean_controls" / asset_id
        clean_asset_dir = clean_dir / "assets"
        clean_asset_dir.mkdir(parents=True, exist_ok=True)
        clean_staged = clean_asset_dir / f"{clean_id}.glb"
        if not clean_staged.exists():
            shutil.copy2(source_glb, clean_staged)
        clean_obj = _object_plan(clean_id, entry)
        clean_contract = _contract(clean_id, entry, str(asset_spec["shape_profile"]))
        clean_report = render_and_evaluate_generated_asset(
            blender_bin=blender_bin,
            asset_dir=clean_asset_dir,
            output_dir=clean_dir / "multiview",
            obj=clean_obj,
            contract=clean_contract,
            resolution=resolution,
            semantic_scorer=None,
            geometry_evidence=True,
            evidence_resolution=evidence_resolution,
        )
        clean_manifest = read_json(clean_dir / "multiview" / "asset_turntable_manifest.json")
        clean_candidates = broad_low_object_candidates(clean_manifest, object_id=clean_id)
        clean_cache[asset_id] = {
            "report": clean_report,
            "broad_low_candidates": clean_candidates,
            "false_trigger": bool(clean_candidates),
        }
        for seed in SEEDS:
            case_id = f"syn_{split}_{asset_id}_{seed}"
            case_dir = output_dir / "cases" / case_id
            try:
                corrupt_asset_dir = case_dir / "corrupt" / "assets"
                corrupt_asset_dir.mkdir(parents=True, exist_ok=True)
                corrupt_glb = corrupt_asset_dir / f"{case_id}.glb"
                injection = _run_injector(
                    blender_bin=blender_bin,
                    source_glb=source_glb,
                    output_glb=corrupt_glb,
                    report_path=case_dir / "synthetic_ground_truth.json",
                    seed=seed,
                    variant=VARIANT_BY_SEED[seed],
                )
                obj = _object_plan(case_id, entry)
                contract = _contract(case_id, entry, str(asset_spec["shape_profile"]))
                corrupt_report = render_and_evaluate_generated_asset(
                    blender_bin=blender_bin,
                    asset_dir=corrupt_asset_dir,
                    output_dir=case_dir / "corrupt" / "multiview",
                    obj=obj,
                    contract=contract,
                    resolution=resolution,
                    semantic_scorer=None,
                    geometry_evidence=True,
                    evidence_resolution=evidence_resolution,
                )
                corrupt_manifest = read_json(
                    case_dir / "corrupt" / "multiview" / "asset_turntable_manifest.json"
                )
                defect_name, true_polygons, protected_face_count = _ground_truth_from_face_table(
                    corrupt_manifest, case_id
                )
                localization = localize_lower_platform_faces(
                    corrupt_manifest,
                    object_id=case_id,
                    output_dir=case_dir / "localization",
                )
                predicted = {
                    int(item)
                    for name, values in localization.get("selected_seed_polygons", {}).items()
                    if str(name) == defect_name
                    for item in values
                }
                predicted_total = sum(
                    len(values)
                    for values in localization.get("selected_seed_polygons", {}).values()
                )
                true_positive = len(predicted & true_polygons)
                precision = true_positive / max(1, predicted_total)
                recall = true_positive / max(1, len(true_polygons))
                repair_dir = case_dir / "repair"
                repair_glb = repair_dir / "assets" / f"{case_id}.glb"
                mesh_edit = _repair_localized_region(
                    blender_bin=blender_bin,
                    input_glb=corrupt_glb,
                    localization_path=case_dir / "localization" / "face_localization.json",
                    output_glb=repair_glb,
                    audit_dir=repair_dir,
                )
                repaired_report = render_and_evaluate_generated_asset(
                    blender_bin=blender_bin,
                    asset_dir=repair_dir / "assets",
                    output_dir=repair_dir / "multiview",
                    obj=obj,
                    contract=contract,
                    resolution=resolution,
                    semantic_scorer=None,
                    geometry_evidence=True,
                    evidence_resolution=evidence_resolution,
                )
                removed_by_object = mesh_edit.get("removed_faces_by_object", {})
                defect_removed = sum(
                    int(count)
                    for name, count in removed_by_object.items()
                    if str(name).startswith("SyntheticBroadLowPlatform")
                )
                protected_removed = sum(
                    int(count)
                    for name, count in removed_by_object.items()
                    if not str(name).startswith("SyntheticBroadLowPlatform")
                )
                repair_success = bool(
                    defect_removed >= len(true_polygons)
                    and protected_removed / max(1, protected_face_count)
                    <= FROZEN_GATES["maximum_protected_face_removal_rate"]
                    and mesh_edit.get("material_preservation", {}).get("verified")
                )
                row = {
                    "case_id": case_id,
                    "split": split,
                    "asset_id": asset_id,
                    "category": entry.get("category"),
                    "seed": seed,
                    "variant": VARIANT_BY_SEED[seed],
                    "status": "evaluated",
                    "synthetic_ground_truth": injection,
                    "localization_path": str(case_dir / "localization" / "face_localization.json"),
                    "true_defect_face_count": len(true_polygons),
                    "predicted_face_count": predicted_total,
                    "true_positive_face_count": true_positive,
                    "localization_face_precision": round(precision, 6),
                    "localization_face_recall": round(recall, 6),
                    "protected_source_face_count": protected_face_count,
                    "protected_face_removed_count": protected_removed,
                    "defect_face_removed_count": defect_removed,
                    "repair_success": repair_success,
                    "hard_regression_committed": False,
                    "clean_false_trigger": clean_cache[asset_id]["false_trigger"],
                    "corrupt_hard_geometry_gate_passed": corrupt_report.get("hard_geometry_gate_passed"),
                    "repaired_hard_geometry_gate_passed": repaired_report.get("hard_geometry_gate_passed"),
                    "mesh_edit_report_path": str(repair_dir / "mesh_edit_report.json"),
                    "control_contact_sheet_path": str(corrupt_report.get("contact_sheet_path") or ""),
                    "repair_contact_sheet_path": str(repaired_report.get("contact_sheet_path") or ""),
                }
            except Exception as exc:
                row = {
                    "case_id": case_id,
                    "split": split,
                    "asset_id": asset_id,
                    "category": entry.get("category"),
                    "seed": seed,
                    "variant": VARIANT_BY_SEED[seed],
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            rows.append(row)
            write_json(output_dir / f"{split}_partial_results.json", {"results": rows})
    summary = summarize_rows(rows, FROZEN_GATES)
    report = {
        "schema": "scene_detail_synthetic_heldout_results_v1",
        "protocol_sha256": protocol["protocol_sha256"],
        "split": split,
        "thresholds_frozen_before_run": True,
        "inflight_scene_dna_review_used": False,
        "summary": summary,
        "clean_controls": clean_cache,
        "results": rows,
    }
    write_json(output_dir / f"{split}_results.json", report)
    return report


def run_natural(
    *,
    manifest_path: Path,
    output_dir: Path,
    reference_root: Path,
    blender_bin: Path,
    trellis_url: str,
    resolution: int = 256,
    evidence_resolution: int = 96,
) -> dict[str, Any]:
    protocol = frozen_natural_protocol(manifest_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    protocol_path = output_dir / "FROZEN_NATURAL_PROTOCOL.json"
    if protocol_path.exists():
        if read_json(protocol_path).get("protocol_sha256") != protocol["protocol_sha256"]:
            raise RuntimeError("existing natural protocol does not match frozen protocol")
    else:
        write_json(protocol_path, protocol)
    manifest = read_json(manifest_path)
    entries = {str(row["asset_id"]): row for row in manifest.get("assets", [])}
    rows: list[dict[str, Any]] = []
    blind_trials: list[dict[str, Any]] = []
    blind_keys: list[dict[str, Any]] = []
    for asset_spec in ASSET_SPLITS["heldout"]:
        asset_id = str(asset_spec["asset_id"])
        entry = entries[asset_id]
        reference = (
            reference_root
            / "clean_controls"
            / asset_id
            / "multiview"
            / f"clean_{asset_id}"
            / f"{NATURAL_REFERENCE_AXIS}.png"
        )
        if not reference.is_file():
            raise FileNotFoundError(f"frozen clean reference is missing: {reference}")
        for seed in NATURAL_SEEDS:
            case_id = f"natural_{asset_id}_{seed}"
            case_dir = output_dir / "natural_cases" / case_id
            try:
                asset_dir = case_dir / "control" / "assets"
                glb_path = asset_dir / f"{case_id}.glb"
                obj = _object_plan(case_id, entry)
                obj["asset_prompt"] = (
                    f"one complete {', '.join(entry.get('styles', []))} "
                    f"{str(entry.get('category') or 'object').replace('_', ' ')}, isolated product asset"
                )
                generation_path = case_dir / "generation_metadata.json"
                if glb_path.is_file() and generation_path.is_file():
                    generation = read_json(generation_path)
                    generation["reused_frozen_generated_glb"] = True
                else:
                    generation = generate_trellis_asset(
                        obj,
                        glb_path,
                        trellis_url=trellis_url,
                        seed=seed,
                        timeout=1800.0,
                        steps=8,
                        texture_size=1024,
                        decimation_target=100000,
                        pipeline_type="512",
                        preprocess_image=False,
                        reference_image_path=reference,
                    )
                    write_json(generation_path, generation)
                contract = _contract(case_id, entry, str(asset_spec["shape_profile"]))
                control_report = render_and_evaluate_generated_asset(
                    blender_bin=blender_bin,
                    asset_dir=asset_dir,
                    output_dir=case_dir / "control" / "multiview",
                    obj=obj,
                    contract=contract,
                    reference_image_path=reference,
                    resolution=resolution,
                    semantic_scorer=None,
                    geometry_evidence=True,
                    evidence_resolution=evidence_resolution,
                )
                control_report = apply_generic_connected_platform_gate(control_report)
                write_json(
                    case_dir / "control" / "multiview" / "scene_dna_multiview_report.json",
                    control_report,
                )
                control_manifest = read_json(
                    case_dir / "control" / "multiview" / "asset_turntable_manifest.json"
                )
                diagnosis = diagnose_detail_failures(control_report)
                issue_types = {
                    str(item.get("issue_type") or "")
                    for item in diagnosis.get("findings", [])
                    if isinstance(item, dict)
                }
                component_candidates = broad_low_object_candidates(
                    control_manifest, object_id=case_id
                )
                platform_trigger = bool(
                    component_candidates
                    or control_report.get("generic_connected_platform_evidence", {}).get("triggered")
                    or issue_types & {"forbidden_platform", "forbidden_ground_geometry"}
                )
                accepted = False
                verification = None
                repaired_sheet = None
                repair_attempted = False
                repair_blocked_reason = None
                if platform_trigger:
                    repair_policy = tessellation_aware_platform_repair_policy(
                        control_report
                    )
                    localization = localize_lower_platform_faces(
                        control_manifest,
                        object_id=case_id,
                        output_dir=case_dir / "localization",
                        maximum_removed_face_fraction=float(
                            repair_policy["maximum_removed_face_fraction"]
                        ),
                        repair_policy_evidence=repair_policy,
                    )
                    if localization.get("accepted_for_automatic_repair"):
                        repair_attempted = True
                        repair_dir = case_dir / "repair"
                        repaired_glb = repair_dir / "assets" / f"{case_id}.glb"
                        try:
                            mesh_edit = _repair_localized_region(
                                blender_bin=blender_bin,
                                input_glb=glb_path,
                                localization_path=case_dir / "localization" / "face_localization.json",
                                output_glb=repaired_glb,
                                audit_dir=repair_dir,
                            )
                        except RuntimeError as exc:
                            repair_blocked_reason = f"{type(exc).__name__}: {exc}"
                        else:
                            repaired_report = render_and_evaluate_generated_asset(
                                blender_bin=blender_bin,
                                asset_dir=repair_dir / "assets",
                                output_dir=repair_dir / "multiview",
                                obj=obj,
                                contract=contract,
                                reference_image_path=reference,
                                resolution=resolution,
                                semantic_scorer=None,
                            )
                            repaired_report = apply_generic_connected_platform_gate(
                                repaired_report
                            )
                            write_json(
                                repair_dir / "multiview" / "scene_dna_multiview_report.json",
                                repaired_report,
                            )
                            verification = verify_repair(
                                control_report, repaired_report, edit_certificate=mesh_edit
                            )
                            accepted = bool(verification.get("accepted"))
                            repaired_sheet = str(repaired_report.get("contact_sheet_path") or "")
                            if accepted:
                                repair_on_a = hashlib.sha256(case_id.encode("utf-8")).digest()[0] % 2 == 0
                                control_sheet = str(control_report.get("contact_sheet_path") or "")
                                blind_trials.append(
                                    {
                                        "trial_id": f"{case_id}_natural_detail",
                                        "case_id": case_id,
                                        "category": entry.get("category"),
                                        "question": "哪个模型的结构细节更合理，同时没有明显损坏主体？",
                                        "A": {"image_path": repaired_sheet if repair_on_a else control_sheet},
                                        "B": {"image_path": control_sheet if repair_on_a else repaired_sheet},
                                        "choices": ["A", "B", "差不多", "两者都不可用"],
                                    }
                                )
                                blind_keys.append(
                                    {
                                        "trial_id": f"{case_id}_natural_detail",
                                        "repair_side": "A" if repair_on_a else "B",
                                    }
                                )
                row = {
                    "case_id": case_id,
                    "asset_id": asset_id,
                    "category": entry.get("category"),
                    "seed": seed,
                    "status": "evaluated",
                    "generation_job_id": generation.get("job_id"),
                    "diagnosis": diagnosis,
                    "broad_low_object_candidates": component_candidates,
                    "platform_triggered": platform_trigger,
                    "repair_attempted": repair_attempted,
                    "repair_blocked_reason": repair_blocked_reason,
                    "repair_accepted": accepted,
                    "verification": verification,
                    "hard_regression_committed": bool(
                        accepted and verification and verification.get("introduced_hard_failures")
                    ),
                    "control_contact_sheet_path": str(control_report.get("contact_sheet_path") or ""),
                    "repair_contact_sheet_path": repaired_sheet,
                }
            except Exception as exc:
                row = {
                    "case_id": case_id,
                    "asset_id": asset_id,
                    "category": entry.get("category"),
                    "seed": seed,
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            rows.append(row)
            write_json(output_dir / "natural_partial_results.json", {"results": rows})
    evaluated = [row for row in rows if row.get("status") == "evaluated"]
    metrics = {
        "case_count": len(rows),
        "evaluated_case_count": len(evaluated),
        "failed_case_count": len(rows) - len(evaluated),
        "generation_completion_rate": round(len(evaluated) / max(1, len(rows)), 6),
        "platform_trigger_count": sum(bool(row.get("platform_triggered")) for row in evaluated),
        "repair_attempt_count": sum(bool(row.get("repair_attempted")) for row in evaluated),
        "verified_repair_count": sum(bool(row.get("repair_accepted")) for row in evaluated),
        "hard_regression_commit_count": sum(bool(row.get("hard_regression_committed")) for row in evaluated),
    }
    gates = protocol["gates"]
    checks = {
        "generation_completion": metrics["generation_completion_rate"] >= gates["minimum_generation_completion_rate"],
        "no_failed_cases": metrics["failed_case_count"] <= gates["maximum_failed_case_count"],
        "no_hard_regression_commit": metrics["hard_regression_commit_count"] <= gates["maximum_hard_regression_commit_count"],
    }
    report = {
        "schema": "scene_detail_natural_heldout_results_v2",
        "protocol_sha256": protocol["protocol_sha256"],
        "summary": {"metrics": metrics, "gate_checks": checks, "passed": all(checks.values())},
        "blind_questionnaire_eligible": bool(all(checks.values()) and blind_trials),
        "results": rows,
    }
    write_json(output_dir / "natural_results.json", report)
    write_json(output_dir / "natural_blind_trials_private.json", {"trials": blind_trials})
    write_json(output_dir / "natural_blind_key_private.json", {"keys": blind_keys})
    return report


def export_synthetic_blind_questionnaire(
    *,
    heldout_results_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    heldout = read_json(heldout_results_path)
    if not heldout.get("summary", {}).get("passed"):
        raise RuntimeError("synthetic blind export requires a passed heldout report")
    comparisons = []
    for row in heldout.get("results", []):
        if row.get("status") != "evaluated" or not row.get("repair_success"):
            continue
        comparisons.append(
            {
                "case_id": row["case_id"],
                "category": row["category"],
                "shape_profile": "broad_low_platform_injection",
                "object_requirement": (
                    f"one complete {str(row['category']).replace('_', ' ')} "
                    "without a display platform; preserve all legitimate parts"
                ),
                "style_requirement": "modern",
                "baseline": {
                    "asset_id": f"control_{row['case_id']}",
                    "image_path": row["control_contact_sheet_path"],
                },
                "proposed": {
                    "asset_id": f"repair_{row['case_id']}",
                    "image_path": row["repair_contact_sheet_path"],
                },
            }
        )
    if not comparisons:
        raise RuntimeError("passed heldout report contains no successful repair comparisons")
    output_dir.mkdir(parents=True, exist_ok=True)
    comparison_path = output_dir / "synthetic_blind_comparisons_private.json"
    sealed_key_path = output_dir / "sealed_synthetic_detail_key.json"
    bundle_dir = output_dir / "blind_review_bundle"
    offline_path = output_dir / "SceneDetail_synthetic_heldout_blind_offline.html"
    write_json(
        comparison_path,
        {
            "schema": "scene_detail_synthetic_blind_comparisons_v1",
            "comparisons": comparisons,
        },
    )
    public = prepare_blind_bundle(
        comparison_path,
        bundle_dir,
        sealed_key_path=sealed_key_path,
        random_seed=20260825,
        duplicate_fraction=0.10,
    )
    offline = export_offline_bundle(
        bundle_dir,
        offline_path,
        label="scene_detail_synthetic_heldout",
    )
    readme = (
        "# SceneDetail 合成留出隐藏评审\n\n"
        "只把 `SceneDetail_synthetic_heldout_blind_offline.html` 发给评审者。"
        "不要发送本目录、sealed key、comparisons 或 heldout 自动分。\n\n"
        "本问卷验证的是：去除已知注入地台后，主体结构是否更合理且没有明显受损。"
        "它不等价于自然 TRELLIS 缺陷修复收益。\n"
    )
    (output_dir / "REVIEWER_README.md").write_text(readme, encoding="utf-8")
    report = {
        "schema": "scene_detail_synthetic_blind_export_v1",
        "automatic_heldout_gate_passed": True,
        "natural_repair_claim": False,
        "independent_case_count": len(comparisons),
        "public_trial_count_including_repeat": len(public.get("trials", [])),
        "offline": offline,
        "reviewer_file": str(offline_path),
        "sealed_key_path": str(sealed_key_path),
    }
    write_json(output_dir / "blind_export_report.json", report)
    return report


def export_natural_blind_questionnaire(
    *,
    natural_results_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Export only verified natural repairs as a sealed offline pilot."""

    natural = read_json(natural_results_path)
    if not natural.get("summary", {}).get("passed"):
        raise RuntimeError("natural blind export requires a passed automatic report")
    if not natural.get("blind_questionnaire_eligible"):
        raise RuntimeError("natural report has no verified comparison eligible for review")
    comparisons = []
    for row in natural.get("results", []):
        if row.get("status") != "evaluated" or not row.get("repair_accepted"):
            continue
        comparisons.append(
            {
                "case_id": row["case_id"],
                "category": row["category"],
                "shape_profile": "natural_detail_platform_repair",
                "object_requirement": (
                    f"one complete {str(row['category']).replace('_', ' ')} "
                    "without an unintended display platform; preserve all legitimate parts"
                ),
                "style_requirement": "preserve the original generated appearance",
                "baseline": {
                    "asset_id": f"control_{row['case_id']}",
                    "image_path": row["control_contact_sheet_path"],
                },
                "proposed": {
                    "asset_id": f"repair_{row['case_id']}",
                    "image_path": row["repair_contact_sheet_path"],
                },
            }
        )
    if not comparisons:
        raise RuntimeError("natural report contains no accepted repairs")
    output_dir.mkdir(parents=True, exist_ok=True)
    comparison_path = output_dir / "natural_blind_comparisons_private.json"
    sealed_key_path = output_dir / "sealed_natural_detail_key.json"
    bundle_dir = output_dir / "blind_review_bundle"
    offline_path = output_dir / "SceneDetail_natural_pilot_blind_offline.html"
    write_json(
        comparison_path,
        {
            "schema": "scene_detail_natural_blind_comparisons_v1",
            "comparisons": comparisons,
        },
    )
    public = prepare_blind_bundle(
        comparison_path,
        bundle_dir,
        sealed_key_path=sealed_key_path,
        random_seed=20260826,
        duplicate_fraction=0.50,
    )
    offline = export_offline_bundle(
        bundle_dir,
        offline_path,
        label="scene_detail_natural_pilot",
    )
    (output_dir / "REVIEWER_README.md").write_text(
        "# SceneDetail 自然缺陷修复隐藏评审（小样本试测）\n\n"
        "只把 `SceneDetail_natural_pilot_blind_offline.html` 发给评审者。"
        "不要发送本目录、sealed key、comparisons 或自动评分。\n\n"
        "请重点判断地台是否被正确移除，以及花盆、叶片和整体外观是否受损。"
        "本轮只有 2 个独立自然案例和 1 个隐藏重复题，只用于验证修复方向，"
        "不能单独证明跨类别泛化。\n",
        encoding="utf-8",
    )
    report = {
        "schema": "scene_detail_natural_blind_export_v1",
        "automatic_natural_gate_passed": True,
        "pilot_only": True,
        "independent_case_count": len(comparisons),
        "public_trial_count_including_repeat": len(public.get("trials", [])),
        "offline": offline,
        "reviewer_file": str(offline_path),
        "sealed_key_path": str(sealed_key_path),
    }
    write_json(output_dir / "blind_export_report.json", report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--split",
        choices=(
            "development",
            "heldout",
            "natural",
            "questionnaire",
            "natural_questionnaire",
        ),
        required=True,
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("/data/wsj/main/scene_runs/codex_trellis_v2/assets_curated_v1/manifest.json"),
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--blender", required=True, type=Path)
    parser.add_argument("--resolution", type=int, default=256)
    parser.add_argument("--evidence-resolution", type=int, default=96)
    parser.add_argument("--trellis-url", default="http://127.0.0.1:8082")
    parser.add_argument("--reference-root", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.split == "questionnaire":
        if args.reference_root is None:
            raise ValueError("--reference-root must point to the synthetic heldout root")
        report = export_synthetic_blind_questionnaire(
            heldout_results_path=args.reference_root / "heldout_results.json",
            output_dir=args.output_dir,
        )
        print(json.dumps(report, indent=2))
        return 0
    if args.split == "natural_questionnaire":
        if args.reference_root is None:
            raise ValueError("--reference-root must point to the natural heldout root")
        report = export_natural_blind_questionnaire(
            natural_results_path=args.reference_root / "natural_results.json",
            output_dir=args.output_dir,
        )
        print(json.dumps(report, indent=2))
        return 0
    if args.split == "natural":
        if args.reference_root is None:
            raise ValueError("--reference-root is required for the natural split")
        report = run_natural(
            manifest_path=args.manifest,
            output_dir=args.output_dir,
            reference_root=args.reference_root,
            blender_bin=args.blender,
            trellis_url=args.trellis_url,
            resolution=args.resolution,
            evidence_resolution=args.evidence_resolution,
        )
    else:
        report = run_split(
            split=args.split,
            manifest_path=args.manifest,
            output_dir=args.output_dir,
            blender_bin=args.blender,
            resolution=args.resolution,
            evidence_resolution=args.evidence_resolution,
        )
    print(json.dumps(report["summary"], indent=2))
    return 0 if report["summary"]["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
