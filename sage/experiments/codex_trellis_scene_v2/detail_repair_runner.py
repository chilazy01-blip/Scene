from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any

from .assets import generate_trellis_asset
from .detail_repair_agent import (
    build_repair_plan,
    diagnose_detail_failures,
    rank_repair_references,
    verify_repair,
)
from .detail_face_localizer import (
    apply_generic_connected_platform_gate,
    localize_lower_platform_faces,
    tessellation_aware_platform_repair_policy,
)
from .io_utils import extract_json, read_json, write_json
from .scene_dna_feasibility import assess_3d_feasibility
from .scene_dna_multiview import (
    evaluate_multiview_manifest,
    render_and_evaluate_generated_asset,
    structure_profile_for_object,
)
from .scene_dna_semantic import Siglip2SemanticScorer


def _method_metadata(case_dir: Path, method: str) -> dict[str, Any]:
    return read_json(case_dir / method / "generation_metadata.json")


def _reference_path(metadata: dict[str, Any]) -> Path:
    request = metadata.get("request") if isinstance(metadata.get("request"), dict) else {}
    path = Path(str(request.get("reference_image_path") or "")).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"frozen reference image is missing: {path}")
    return path


def _object_from_control(case_dir: Path, method: str, case_id: str) -> dict[str, Any]:
    plan = read_json(case_dir / method / "multiview" / "scene_dna_multiview_plan.json")
    row = next(
        (
            item
            for item in plan.get("objects", [])
            if isinstance(item, dict) and str(item.get("id") or "") == case_id
        ),
        None,
    )
    if row is None:
        raise ValueError(f"{case_id}: control turntable plan has no object row")
    metadata = _method_metadata(case_dir, method)
    request = metadata.get("request") if isinstance(metadata.get("request"), dict) else {}
    obj = deepcopy(row)
    obj["id"] = case_id
    obj["category"] = str(obj.get("category") or "object")
    obj["asset_prompt"] = str(request.get("input_text") or obj["category"])
    return obj


def _generation_parameters(metadata: dict[str, Any]) -> dict[str, Any]:
    request = metadata.get("request") if isinstance(metadata.get("request"), dict) else {}
    return {
        "seed": int(request["seed"]),
        "steps": int(request.get("shape_steps", request.get("sparse_steps", 8)) or 8),
        "texture_size": int(request.get("texture_size", 1024) or 1024),
        "decimation_target": int(request.get("decimation_target", 100_000) or 100_000),
        "pipeline_type": str(request.get("pipeline_type") or "512"),
    }


def _blind_row(
    case_id: str,
    category: str,
    control_sheet: str,
    repair_sheet: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    repair_on_a = hashlib.sha256(case_id.encode("utf-8")).digest()[0] % 2 == 0
    left = repair_sheet if repair_on_a else control_sheet
    right = control_sheet if repair_on_a else repair_sheet
    public = {
        "trial_id": f"{case_id}_detail_loop",
        "case_id": case_id,
        "category": category,
        "question": "哪个模型的结构细节更正确，同时整体外观没有明显退化？",
        "A": {"image_path": left},
        "B": {"image_path": right},
        "choices": ["A", "B", "差不多", "两者都不可用"],
    }
    key = {
        "trial_id": public["trial_id"],
        "repair_side": "A" if repair_on_a else "B",
        "control_side": "B" if repair_on_a else "A",
    }
    return public, key


def _attempt_review_priority(attempt: dict[str, Any]) -> tuple[Any, ...]:
    """Prefer the strongest proposal for calibration, even when it was rolled back."""

    verification = attempt.get("verification") or {}
    gates = verification.get("regression_gates") or {}
    return (
        bool(verification.get("accepted")),
        not bool(verification.get("introduced_hard_failures")),
        bool(verification.get("after_usable")),
        len(verification.get("resolved_hard_failures") or []),
        sum(bool(value) for value in gates.values()),
        float(verification.get("style_delta", 0.0) or 0.0),
        float(verification.get("semantic_delta", 0.0) or 0.0),
        float(verification.get("automated_score_delta", 0.0) or 0.0),
    )


def summarize_detail_repair_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Return auditable branch metrics without treating rejected attempts as wins."""

    completed = [row for row in results if row.get("status") != "failed"]
    attempts = [
        attempt
        for row in completed
        for attempt in (
            list(row.get("local_mesh_repair_attempts") or [])
            + list(row.get("attempts") or [])
        )
    ]
    verifications = [attempt.get("verification") or {} for attempt in attempts]
    return {
        "completed_case_count": len(completed),
        "failed_case_count": len(results) - len(completed),
        "verified_repair_count": sum(
            row.get("status") == "verified_repair" for row in completed
        ),
        "rolled_back_case_count": sum(
            bool(row.get("rollback_enforced")) for row in completed
        ),
        "local_mesh_attempt_count": sum(
            int(row.get("local_mesh_repair_attempt_count", 0) or 0)
            for row in completed
        ),
        "generation_attempt_count": sum(
            int(row.get("generation_attempt_count", 0) or 0)
            for row in completed
        ),
        "total_intervention_attempt_count": len(attempts),
        "attempts_resolving_at_least_one_hard_failure": sum(
            bool(verification.get("resolved_hard_failures"))
            for verification in verifications
        ),
        "attempts_rejected_by_semantic_gate": sum(
            not bool((verification.get("regression_gates") or {}).get("semantic", True))
            for verification in verifications
        ),
        "attempts_rejected_by_style_gate": sum(
            not bool((verification.get("regression_gates") or {}).get("style", True))
            for verification in verifications
        ),
        "attempts_introducing_hard_failure": sum(
            bool(verification.get("introduced_hard_failures"))
            for verification in verifications
        ),
        "hard_regression_commit_count": sum(
            bool(verification.get("accepted"))
            and bool(verification.get("introduced_hard_failures"))
            for verification in verifications
        ),
    }


def _trim_lower_platform(
    *,
    blender_bin: Path,
    input_glb: Path,
    output_glb: Path,
    footprint_expand: float,
    trim_mode: str = "outside_upper_footprint",
    lower_cutoff_ratio: float = 0.34,
    audit_dir: Path,
) -> dict[str, Any]:
    script = Path(__file__).resolve().parents[2] / "scripts" / "blender_trim_forbidden_lower_platform.py"
    command = [
        str(blender_bin),
        "--background",
        "--python-exit-code",
        "1",
        "--python",
        str(script),
        "--",
        "--input-glb",
        str(input_glb),
        "--output-glb",
        str(output_glb),
        "--footprint-expand",
        str(float(footprint_expand)),
        "--trim-mode",
        str(trim_mode),
        "--lower-cutoff-ratio",
        str(float(lower_cutoff_ratio)),
    ]
    completed = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=900,
        check=False,
    )
    audit_dir.mkdir(parents=True, exist_ok=True)
    (audit_dir / "blender_trim_stdout.txt").write_text(completed.stdout, encoding="utf-8")
    (audit_dir / "blender_trim_stderr.txt").write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(
            f"local platform trim failed with code {completed.returncode}: "
            f"{completed.stderr[-1000:]}"
        )
    report = extract_json(completed.stdout)
    write_json(audit_dir / "mesh_edit_report.json", report)
    return report


def _repair_localized_region(
    *,
    blender_bin: Path,
    input_glb: Path,
    localization_path: Path,
    output_glb: Path,
    audit_dir: Path,
) -> dict[str, Any]:
    script = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "blender_repair_localized_region.py"
    )
    command = [
        str(blender_bin),
        "--background",
        "--python-exit-code",
        "1",
        "--python",
        str(script),
        "--",
        "--input-glb",
        str(input_glb),
        "--localization",
        str(localization_path),
        "--output-glb",
        str(output_glb),
    ]
    completed = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=900,
        check=False,
    )
    audit_dir.mkdir(parents=True, exist_ok=True)
    (audit_dir / "blender_localized_repair_stdout.txt").write_text(
        completed.stdout, encoding="utf-8"
    )
    (audit_dir / "blender_localized_repair_stderr.txt").write_text(
        completed.stderr, encoding="utf-8"
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"localized mesh repair failed with code {completed.returncode}: "
            f"{completed.stderr[-1000:]}"
        )
    report = extract_json(completed.stdout)
    write_json(audit_dir / "mesh_edit_report.json", report)
    return report


def _align_long_horizontal_axis(
    obj: dict[str, Any], mesh_edit: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply a 90-degree metadata correction when raw and requested long axes disagree."""

    aligned = deepcopy(obj)
    extents = mesh_edit.get("output_extents_xyz")
    dimensions = obj.get("requested_dimensions") or obj.get("dimensions") or {}
    if not isinstance(extents, list) or len(extents) != 3:
        return aligned, {"applied": False, "reason": "mesh_extents_unavailable"}
    raw_x, raw_y = float(extents[0]), float(extents[1])
    target_x = float(dimensions.get("width", 0.0) or 0.0)
    target_y = float(dimensions.get("length", 0.0) or 0.0)
    raw_long = "x" if raw_x > raw_y else "y"
    target_long = "x" if target_x > target_y else "y"
    confidence = max(raw_x, raw_y) / max(min(raw_x, raw_y), 1e-8)
    applied = bool(raw_long != target_long and confidence >= 1.20)
    if applied:
        aligned["asset_local_yaw_offset_degrees"] = (
            float(aligned.get("asset_local_yaw_offset_degrees", 0.0) or 0.0)
            + 90.0
        ) % 360.0
    return aligned, {
        "applied": applied,
        "method": "raw_long_axis_to_requested_long_axis",
        "raw_long_axis": raw_long,
        "requested_long_axis": target_long,
        "raw_axis_ratio": round(confidence, 6),
        "asset_local_yaw_offset_degrees": float(
            aligned.get("asset_local_yaw_offset_degrees", 0.0) or 0.0
        ),
    }


def _semantic_rescore_existing_multiview(
    *,
    multiview_dir: Path,
    obj: dict[str, Any],
    contract: dict[str, Any],
    reference_image_path: Path,
    semantic_scorer: Any,
) -> dict[str, Any]:
    object_id = str(obj["id"])
    manifest_path = multiview_dir / "asset_turntable_manifest.json"
    report = evaluate_multiview_manifest(
        read_json(manifest_path),
        contract,
        object_id=object_id,
        category=str(obj.get("category") or "object"),
        reference_image_path=reference_image_path,
        structure_profile=structure_profile_for_object(
            obj,
            contract.get("object_profiles", {})
            .get(object_id, {})
            .get("semantic_form_contract", {}),
        ),
        semantic_scorer=semantic_scorer,
    )
    report["manifest_path"] = str(manifest_path)
    report["contact_sheet_path"] = str(
        multiview_dir / "scene_dna_multiview_contact_sheet.png"
    )
    report_path = multiview_dir / "scene_dna_multiview_report.json"
    write_json(report_path, report)
    report["report_path"] = str(report_path)
    return report


def run_detail_repair_branch(
    source_3d_root: Path,
    candidate_root: Path,
    output_dir: Path,
    *,
    trellis_url: str,
    blender_bin: Path,
    case_ids: set[str] | None = None,
    control_method: str = "proposed",
    maximum_generation_attempts: int = 2,
    timeout: float = 1800.0,
    resolution: int = 420,
    semantic_model: str | None = None,
    semantic_device: str = "cpu",
) -> dict[str, Any]:
    """Run an opt-in control-versus-detail-agent branch without touching control data."""

    source_3d_root = source_3d_root.resolve()
    candidate_root = candidate_root.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    semantic_scorer = (
        Siglip2SemanticScorer(semantic_model, device=semantic_device)
        if semantic_model
        else None
    )
    benchmark = read_json(source_3d_root / "paired_3d_benchmark_results.json")
    seed_by_case = {
        str(row.get("case_id") or ""): int(row.get("same_trellis_seed", 0) or 0)
        for row in benchmark.get("results", [])
        if isinstance(row, dict)
    }
    available = sorted(
        path.name
        for path in source_3d_root.glob("case_*")
        if path.is_dir() and (path / control_method).is_dir()
    )
    selected_cases = [case for case in available if not case_ids or case in case_ids]
    results: list[dict[str, Any]] = []
    blind_trials: list[dict[str, Any]] = []
    blind_key: list[dict[str, Any]] = []
    for case_id in selected_cases:
        case_dir = source_3d_root / case_id
        branch_case = output_dir / case_id
        try:
            contract = read_json(case_dir / "scene_dna_contract.json")
            obj = _object_from_control(case_dir, control_method, case_id)
            category = str(obj.get("category") or "object")
            metadata = _method_metadata(case_dir, control_method)
            control_reference = _reference_path(metadata)
            control_asset_dir = case_dir / control_method / "assets"
            original_report = read_json(
                case_dir
                / control_method
                / "multiview"
                / "scene_dna_multiview_report.json"
            )
            original_diagnosis = diagnose_detail_failures(original_report)

            # Re-acquire evidence with fixed adaptive framing.  This changes no GLB
            # and is mandatory before spending a generation attempt.
            control_report = render_and_evaluate_generated_asset(
                blender_bin=blender_bin,
                asset_dir=control_asset_dir,
                output_dir=branch_case / "control_reassessment",
                obj=obj,
                contract=contract,
                reference_image_path=control_reference,
                resolution=resolution,
                semantic_scorer=None,
                geometry_evidence=True,
                evidence_resolution=128,
            )
            control_report = apply_generic_connected_platform_gate(control_report)
            control_semantic_ready = False
            if (
                semantic_scorer is not None
                and assess_3d_feasibility(control_report)["usable_for_scene_assembly"]
            ):
                control_report = _semantic_rescore_existing_multiview(
                    multiview_dir=branch_case / "control_reassessment",
                    obj=obj,
                    contract=contract,
                    reference_image_path=control_reference,
                    semantic_scorer=semantic_scorer,
                )
                control_semantic_ready = True
            diagnosis = diagnose_detail_failures(control_report)
            batch = read_json(candidate_root / case_id / "candidate_batch_result.json")
            excluded = [control_reference]
            for method in ("baseline", "proposed"):
                candidate_metadata = case_dir / method / "generation_metadata.json"
                if candidate_metadata.is_file():
                    excluded.append(_reference_path(read_json(candidate_metadata)))
            ranked = rank_repair_references(batch, diagnosis, excluded_paths=excluded)
            plan = build_repair_plan(
                case_id,
                diagnosis,
                ranked,
                max_generation_attempts=maximum_generation_attempts,
            )
            localization: dict[str, Any] | None = None
            localization_error: str | None = None
            if any(
                action.get("action") == "localize_and_repair_defect_faces"
                for action in plan["actions"]
            ):
                try:
                    control_manifest = read_json(
                        branch_case
                        / "control_reassessment"
                        / "asset_turntable_manifest.json"
                    )
                    repair_policy = tessellation_aware_platform_repair_policy(
                        control_report
                    )
                    localization = localize_lower_platform_faces(
                        control_manifest,
                        object_id=case_id,
                        output_dir=branch_case / "face_localization",
                        maximum_removed_face_fraction=float(
                            repair_policy["maximum_removed_face_fraction"]
                        ),
                        repair_policy_evidence=repair_policy,
                    )
                except Exception as exc:
                    localization_error = f"{type(exc).__name__}: {exc}"
            plan["face_localization"] = (
                {
                    "path": str(
                        branch_case / "face_localization" / "face_localization.json"
                    ),
                    "accepted_for_automatic_repair": bool(
                        localization
                        and localization.get("accepted_for_automatic_repair")
                    ),
                    "supporting_views": list(
                        (localization or {}).get("supporting_views") or []
                    ),
                    "seed_face_count": int(
                        (localization or {}).get("seed_face_count", 0) or 0
                    ),
                    "error": localization_error,
                }
                if localization is not None or localization_error
                else None
            )
            plan["frozen_control"] = {
                "method": control_method,
                "glb_path": str((control_asset_dir / f"{case_id}.glb").resolve()),
                "reference_image_path": str(control_reference),
                "seed": seed_by_case.get(case_id),
            }
            plan["initial_evidence_action"] = {
                "action": "rerender_same_asset_with_safe_framing",
                "mutates_asset": False,
                "before_findings": original_diagnosis["findings"],
                "after_findings": diagnosis["findings"],
            }
            write_json(branch_case / "detail_repair_plan.json", plan)
            generation = _generation_parameters(metadata)
            if seed_by_case.get(case_id):
                generation["seed"] = seed_by_case[case_id]
            attempts: list[dict[str, Any]] = []
            local_attempts: list[dict[str, Any]] = []
            accepted_local: dict[str, Any] | None = None
            accepted_attempt: dict[str, Any] | None = None
            if localization and localization.get("accepted_for_automatic_repair"):
                attempt_dir = branch_case / "localized_mesh_repair_01"
                asset_dir = attempt_dir / "assets"
                glb_path = asset_dir / f"{case_id}.glb"
                mesh_edit = _repair_localized_region(
                    blender_bin=blender_bin,
                    input_glb=control_asset_dir / f"{case_id}.glb",
                    localization_path=(
                        branch_case / "face_localization" / "face_localization.json"
                    ),
                    output_glb=glb_path,
                    audit_dir=attempt_dir,
                )
                local_obj, orientation_patch = _align_long_horizontal_axis(obj, mesh_edit)
                local_report = render_and_evaluate_generated_asset(
                    blender_bin=blender_bin,
                    asset_dir=asset_dir,
                    output_dir=attempt_dir / "multiview",
                    obj=local_obj,
                    contract=contract,
                    reference_image_path=control_reference,
                    resolution=resolution,
                    semantic_scorer=None,
                )
                local_report = apply_generic_connected_platform_gate(local_report)
                if (
                    semantic_scorer is not None
                    and assess_3d_feasibility(local_report)["usable_for_scene_assembly"]
                ):
                    if not control_semantic_ready:
                        control_report = _semantic_rescore_existing_multiview(
                            multiview_dir=branch_case / "control_reassessment",
                            obj=obj,
                            contract=contract,
                            reference_image_path=control_reference,
                            semantic_scorer=semantic_scorer,
                        )
                        control_semantic_ready = True
                    local_report = _semantic_rescore_existing_multiview(
                        multiview_dir=attempt_dir / "multiview",
                        obj=local_obj,
                        contract=contract,
                        reference_image_path=control_reference,
                        semantic_scorer=semantic_scorer,
                    )
                verification = verify_repair(
                    control_report,
                    local_report,
                    edit_certificate=mesh_edit,
                )
                localized_result = {
                    "attempt": 1,
                    "action": "localize_and_repair_defect_faces",
                    "localization_path": str(
                        branch_case / "face_localization" / "face_localization.json"
                    ),
                    "mesh_edit": mesh_edit,
                    "orientation_metadata_patch": orientation_patch,
                    "glb_path": str(glb_path),
                    "contact_sheet_path": str(
                        local_report.get("contact_sheet_path") or ""
                    ),
                    "diagnosis_after": diagnose_detail_failures(local_report),
                    "verification": verification,
                }
                local_attempts.append(localized_result)
                write_json(attempt_dir / "verification.json", verification)
                if verification["accepted"]:
                    accepted_local = localized_result
            local_actions = [
                action
                for action in plan["actions"]
                if action.get("action") == "trim_forbidden_lower_platform"
            ]
            for action in local_actions:
                if accepted_local is not None:
                    break
                for ordinal, variant in enumerate(
                    action.get("mesh_repair_variants", []),
                    start=(2 if local_attempts else 1),
                ):
                    attempt_dir = branch_case / f"local_mesh_repair_{ordinal:02d}"
                    asset_dir = attempt_dir / "assets"
                    glb_path = asset_dir / f"{case_id}.glb"
                    mesh_edit = _trim_lower_platform(
                        blender_bin=blender_bin,
                        input_glb=control_asset_dir / f"{case_id}.glb",
                        output_glb=glb_path,
                        footprint_expand=float(variant.get("footprint_expand", 1.45)),
                        trim_mode=str(
                            variant.get("trim_mode") or "outside_upper_footprint"
                        ),
                        lower_cutoff_ratio=float(
                            variant.get("lower_cutoff_ratio", 0.34)
                        ),
                        audit_dir=attempt_dir,
                    )
                    local_obj, orientation_patch = _align_long_horizontal_axis(
                        obj, mesh_edit
                    )
                    local_report = render_and_evaluate_generated_asset(
                        blender_bin=blender_bin,
                        asset_dir=asset_dir,
                        output_dir=attempt_dir / "multiview",
                        obj=local_obj,
                        contract=contract,
                        reference_image_path=control_reference,
                        resolution=resolution,
                        semantic_scorer=None,
                    )
                    local_report = apply_generic_connected_platform_gate(local_report)
                    if (
                        semantic_scorer is not None
                        and assess_3d_feasibility(local_report)[
                            "usable_for_scene_assembly"
                        ]
                    ):
                        if not control_semantic_ready:
                            control_report = _semantic_rescore_existing_multiview(
                                multiview_dir=branch_case / "control_reassessment",
                                obj=obj,
                                contract=contract,
                                reference_image_path=control_reference,
                                semantic_scorer=semantic_scorer,
                            )
                            control_semantic_ready = True
                        local_report = _semantic_rescore_existing_multiview(
                            multiview_dir=attempt_dir / "multiview",
                            obj=local_obj,
                            contract=contract,
                            reference_image_path=control_reference,
                            semantic_scorer=semantic_scorer,
                        )
                    verification = verify_repair(control_report, local_report)
                    local_result = {
                        "attempt": ordinal,
                        "action": "trim_forbidden_lower_platform",
                        "variant": deepcopy(variant),
                        "mesh_edit": mesh_edit,
                        "orientation_metadata_patch": orientation_patch,
                        "glb_path": str(glb_path),
                        "contact_sheet_path": str(local_report.get("contact_sheet_path") or ""),
                        "diagnosis_after": diagnose_detail_failures(local_report),
                        "verification": verification,
                    }
                    local_attempts.append(local_result)
                    write_json(attempt_dir / "verification.json", verification)
                    if verification["accepted"]:
                        accepted_local = local_result
                        break
                if accepted_local:
                    break
            generation_actions = [
                action
                for action in plan["actions"]
                if action.get("action") == "switch_reference_and_regenerate_single_asset"
            ]
            for ordinal, action in enumerate(generation_actions, start=1):
                if accepted_local is not None:
                    break
                attempt_dir = branch_case / f"repair_attempt_{ordinal:02d}"
                asset_dir = attempt_dir / "assets"
                glb_path = asset_dir / f"{case_id}.glb"
                reference = Path(str(action["reference_image_path"]))
                generation_metadata = generate_trellis_asset(
                    obj,
                    glb_path,
                    trellis_url=trellis_url,
                    seed=int(generation["seed"]),
                    timeout=timeout,
                    steps=int(generation["steps"]),
                    texture_size=int(generation["texture_size"]),
                    decimation_target=int(generation["decimation_target"]),
                    pipeline_type=str(generation["pipeline_type"]),
                    preprocess_image=False,
                    reference_image_path=reference,
                )
                write_json(attempt_dir / "generation_metadata.json", generation_metadata)
                repair_report = render_and_evaluate_generated_asset(
                    blender_bin=blender_bin,
                    asset_dir=asset_dir,
                    output_dir=attempt_dir / "multiview",
                    obj=obj,
                    contract=contract,
                    reference_image_path=reference,
                    resolution=resolution,
                    semantic_scorer=None,
                )
                repair_report = apply_generic_connected_platform_gate(repair_report)
                if (
                    semantic_scorer is not None
                    and assess_3d_feasibility(repair_report)[
                        "usable_for_scene_assembly"
                    ]
                ):
                    if not control_semantic_ready:
                        control_report = _semantic_rescore_existing_multiview(
                            multiview_dir=branch_case / "control_reassessment",
                            obj=obj,
                            contract=contract,
                            reference_image_path=control_reference,
                            semantic_scorer=semantic_scorer,
                        )
                        control_semantic_ready = True
                    repair_report = _semantic_rescore_existing_multiview(
                        multiview_dir=attempt_dir / "multiview",
                        obj=obj,
                        contract=contract,
                        reference_image_path=reference,
                        semantic_scorer=semantic_scorer,
                    )
                verification = verify_repair(control_report, repair_report)
                attempt_result = {
                    "attempt": ordinal,
                    "action": deepcopy(action),
                    "same_frozen_seed": int(generation["seed"]),
                    "glb_path": str(glb_path),
                    "multiview_report_path": str(
                        attempt_dir / "multiview" / "scene_dna_multiview_report.json"
                    ),
                    "contact_sheet_path": str(repair_report.get("contact_sheet_path") or ""),
                    "diagnosis_after": diagnose_detail_failures(repair_report),
                    "verification": verification,
                }
                attempts.append(attempt_result)
                write_json(attempt_dir / "verification.json", verification)
                if verification["accepted"]:
                    accepted_attempt = attempt_result
                    break

            review_candidates = local_attempts + attempts
            final_attempt = (
                accepted_local
                or accepted_attempt
                or (
                    max(review_candidates, key=_attempt_review_priority)
                    if review_candidates
                    else None
                )
            )
            accepted_result = accepted_local or accepted_attempt
            status = "verified_repair" if accepted_result else (
                "unresolved_rolled_back"
                if attempts or local_attempts
                else "no_eligible_repair_reference"
            )
            result = {
                "case_id": case_id,
                "category": category,
                "status": status,
                "control_immutable": True,
                "control_glb_path": str(control_asset_dir / f"{case_id}.glb"),
                "control_report_path": str(
                    branch_case / "control_reassessment" / "scene_dna_multiview_report.json"
                ),
                "original_diagnosis": original_diagnosis,
                "reassessed_diagnosis": diagnosis,
                "local_mesh_repair_attempt_count": len(local_attempts),
                "local_mesh_repair_attempts": local_attempts,
                "generation_attempt_count": len(attempts),
                "attempts": attempts,
                "accepted_repair_glb_path": (
                    accepted_result["glb_path"] if accepted_result else None
                ),
                "accepted_repair_method": (
                    "local_mesh_repair" if accepted_local else (
                        "reference_switch_regeneration" if accepted_attempt else None
                    )
                ),
                "accepted_object_metadata_patch": (
                    accepted_local.get("orientation_metadata_patch")
                    if accepted_local
                    else None
                ),
                "rollback_enforced": accepted_result is None,
            }
            results.append(result)
            write_json(branch_case / "detail_repair_result.json", result)
            if final_attempt is not None:
                trial, key = _blind_row(
                    case_id,
                    category,
                    str(control_report.get("contact_sheet_path") or ""),
                    str(final_attempt["contact_sheet_path"]),
                )
                blind_trials.append(trial)
                blind_key.append(key)
        except Exception as exc:
            results.append(
                {
                    "case_id": case_id,
                    "status": "failed",
                    "control_immutable": True,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        write_json(
            output_dir / "detail_repair_branch_results.json",
            {
                "schema": "scene_detail_repair_branch_v1",
                "independent_opt_in_branch": True,
                "results": results,
            },
        )
    metrics = summarize_detail_repair_results(results)
    verified = int(metrics["verified_repair_count"])
    report = {
        "schema": "scene_detail_repair_branch_v1",
        "independent_opt_in_branch": True,
        "control_method": control_method,
        "control_artifacts_modified": False,
        "whole_scene_regeneration_used": False,
        "requested_case_count": len(selected_cases),
        "completed_case_count": int(metrics["completed_case_count"]),
        "verified_repair_count": verified,
        "verified_repair_rate": round(verified / max(1, len(selected_cases)), 6),
        "quality_metrics": metrics,
        "hard_regression_commit_count": int(metrics["hard_regression_commit_count"]),
        "results": results,
        "limitations": [
            "pilot failures and existing candidate pools are development evidence, not held-out efficacy evidence",
            "zero-shot semantic/style gates still require hidden-label human calibration",
        ],
    }
    write_json(output_dir / "detail_repair_branch_results.json", report)
    write_json(
        output_dir / "blind_review_trials.json",
        {"schema": "scene_detail_repair_blind_trials_v1", "trials": blind_trials},
    )
    write_json(
        output_dir / "private_blind_key.json",
        {"schema": "scene_detail_repair_blind_key_v1", "keys": blind_key},
    )
    if semantic_scorer is not None:
        semantic_scorer.close()
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-3d-root", required=True, type=Path)
    parser.add_argument("--candidate-root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--trellis-url", default="http://127.0.0.1:8082")
    parser.add_argument("--blender", required=True, type=Path)
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--control-method", choices=("baseline", "proposed"), default="proposed")
    parser.add_argument("--maximum-generation-attempts", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=1800.0)
    parser.add_argument("--resolution", type=int, default=420)
    parser.add_argument("--semantic-model")
    parser.add_argument("--semantic-device", default="cpu")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_detail_repair_branch(
        args.source_3d_root,
        args.candidate_root,
        args.output_dir,
        trellis_url=str(args.trellis_url),
        blender_bin=args.blender,
        case_ids={str(item) for item in args.case_id} or None,
        control_method=str(args.control_method),
        maximum_generation_attempts=int(args.maximum_generation_attempts),
        timeout=float(args.timeout),
        resolution=int(args.resolution),
        semantic_model=args.semantic_model,
        semantic_device=str(args.semantic_device),
    )
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "requested_case_count",
                    "completed_case_count",
                    "verified_repair_count",
                )
            },
            indent=2,
        )
    )
    return 0 if report["completed_case_count"] == report["requested_case_count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
