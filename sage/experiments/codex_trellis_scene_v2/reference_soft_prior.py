from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any

from .architecture import plan_architecture
from .brief import expand_prompt
from .io_utils import (
    read_json,
    run_codex_image_json,
    run_codex_json,
    write_json,
)
from .orientation import apply_facing_constraints, apply_relation_facing_constraints
from .planner import (
    _layout_prompt,
    _normalize_codex_layout,
    codex_layout,
    rules_layout,
)
from .repair import deterministic_repair
from .scene_graph import build_typed_scene_graph, materialize_scene_graph
from .validator import footprint, validate_layout


SOFT_PRIOR_SCHEMA = "codex_trellis_reference_soft_layout_prior_v1"
EXPERIMENT_SCHEMA = "codex_trellis_reference_soft_prior_ab_v1"


def build_reference_prompt(brief: dict[str, Any]) -> str:
    objects = [
        (
            f"{obj['id']} ({obj['category']}), "
            f"wall={obj.get('preferred_wall') or 'free'}, "
            f"facing={str((obj.get('facing_constraint') or {}).get('mode') or 'free')}"
        )
        for obj in brief.get("objects", [])
        if obj.get("placement_type") != "support"
    ]
    hard_relations = [
        f"{relation[0]} {relation[1]} {relation[2]}"
        if isinstance(relation, list) and len(relation) >= 3
        else (
            f"{relation.get('source')} {relation.get('type')} "
            f"{relation.get('target')}"
        )
        for relation in brief.get("relations", [])
        if isinstance(relation, (list, dict))
    ]
    architecture = brief.get("architecture", {})
    doors = [
        (
            f"{door.get('id')} on {door.get('wall')} wall, "
            f"center={door.get('center')}m, width={door.get('width')}m"
        )
        for door in architecture.get("doors", [])
        if isinstance(door, dict)
    ]
    windows = [
        (
            f"{window.get('id')} on {window.get('wall')} wall, "
            f"center={window.get('center')}m, width={window.get('width')}m"
        )
        for window in architecture.get("windows", [])
        if isinstance(window, dict)
    ]
    spatial_contract = {
        "room_m": {
            "width": brief.get("room", {}).get("width"),
            "length": brief.get("room", {}).get("length"),
            "height": brief.get("room", {}).get("height"),
        },
        "exact_objects": objects,
        "relations": hard_relations,
        "doors": doors,
        "windows": windows,
    }
    return (
        "Photorealistic eye-level room reference. Camera: centered at south wall and looks due north; "
        "west=image-left, east=image-right. Wide lens, no fisheye.\n"
        f"Spatial contract: {json.dumps(spatial_contract, ensure_ascii=False)}\n"
        "Obey the exact object count, wall sides, door, window, and relation. Keep the entry clear "
        "and every object recognizable with low occlusion. No extra or duplicate furniture.\n"
        f"Style and scene: {brief['expanded_description']}"
    )


def build_observer_prompt(brief: dict[str, Any]) -> str:
    catalog = [
        {
            "id": obj["id"],
            "category": obj["category"],
            "placement_type": obj.get("placement_type"),
        }
        for obj in brief.get("objects", [])
        if obj.get("placement_type") != "support"
    ]
    return f"""
Inspect the attached generated room image as uncertain visual evidence.
The camera was requested at the south wall looking north, so image-left approximately means west,
image-right approximately means east, and greater inferred depth approximately means farther north.

Exact scene object catalog:
{json.dumps(catalog, indent=2, ensure_ascii=False)}

Return only JSON:
{{
  "schema": "{SOFT_PRIOR_SCHEMA}",
  "objects": [
    {{
      "id": "exact catalog id",
      "visible": true,
      "confidence": 0.0,
      "bbox_normalized": [x_min, y_min, x_max, y_max],
      "room_position_hint": {{
        "x_fraction": 0.0,
        "y_fraction": 0.0,
        "confidence": 0.0
      }},
      "evidence": "short visual evidence"
    }}
  ],
  "warnings": ["ambiguity or generated-image failure"]
}}

Rules:
- This is a soft observation, not permission to change the scene specification.
- Use only exact catalog ids. Never add, delete, merge, rename, or resize an object.
- Include an entry only when the object can be matched with useful confidence.
- All normalized coordinates and confidence values must lie in [0, 1].
- bbox_normalized uses image coordinates: x grows right and y grows down.
- room_position_hint is an approximate floor position, not the bbox center.
- If duplicate-looking instances cannot be distinguished, omit them and add a warning.
- Do not infer room dimensions, architecture, hard relations, or asset identity.
- Do not include markdown or text outside JSON.
""".strip()


def validate_soft_prior(
    raw: Any,
    brief: dict[str, Any],
    *,
    minimum_confidence: float = 0.45,
) -> dict[str, Any]:
    expected = {
        str(obj["id"]): obj
        for obj in brief.get("objects", [])
        if obj.get("placement_type") != "support"
    }
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen: set[str] = set()
    items = raw.get("objects", []) if isinstance(raw, dict) else []
    if not isinstance(items, list):
        items = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            rejected.append({"index": index, "reason": "not_an_object"})
            continue
        object_id = str(item.get("id") or "")
        if object_id not in expected:
            rejected.append(
                {"index": index, "id": object_id, "reason": "unknown_object_id"}
            )
            continue
        if object_id in seen:
            rejected.append(
                {"index": index, "id": object_id, "reason": "duplicate_object_id"}
            )
            continue
        confidence = float(item.get("confidence", 0.0) or 0.0)
        hint = item.get("room_position_hint")
        bbox = item.get("bbox_normalized")
        if not 0.0 <= confidence <= 1.0:
            rejected.append(
                {"index": index, "id": object_id, "reason": "invalid_confidence"}
            )
            continue
        if confidence < float(minimum_confidence):
            rejected.append(
                {"index": index, "id": object_id, "reason": "low_confidence"}
            )
            continue
        if not isinstance(hint, dict):
            rejected.append(
                {"index": index, "id": object_id, "reason": "missing_position_hint"}
            )
            continue
        x_fraction = float(hint.get("x_fraction", -1.0))
        y_fraction = float(hint.get("y_fraction", -1.0))
        hint_confidence = float(hint.get("confidence", confidence) or 0.0)
        if not all(
            0.0 <= value <= 1.0
            for value in (x_fraction, y_fraction, hint_confidence)
        ):
            rejected.append(
                {"index": index, "id": object_id, "reason": "invalid_position_hint"}
            )
            continue
        if hint_confidence < float(minimum_confidence):
            rejected.append(
                {
                    "index": index,
                    "id": object_id,
                    "reason": "low_position_confidence",
                }
            )
            continue
        normalized_bbox: list[float] | None = None
        if isinstance(bbox, list) and len(bbox) == 4:
            normalized_bbox = [float(value) for value in bbox]
            if (
                not all(0.0 <= value <= 1.0 for value in normalized_bbox)
                or normalized_bbox[0] >= normalized_bbox[2]
                or normalized_bbox[1] >= normalized_bbox[3]
            ):
                rejected.append(
                    {"index": index, "id": object_id, "reason": "invalid_bbox"}
                )
                continue
        seen.add(object_id)
        accepted.append(
            {
                "id": object_id,
                "category": str(expected[object_id]["category"]),
                "visible": bool(item.get("visible", True)),
                "confidence": confidence,
                "bbox_normalized": normalized_bbox,
                "room_position_hint": {
                    "x_fraction": x_fraction,
                    "y_fraction": y_fraction,
                    "confidence": hint_confidence,
                },
                "evidence": str(item.get("evidence") or ""),
                "provenance": "generated_reference_image_observation",
                "strength": "soft",
            }
        )
    return {
        "schema": SOFT_PRIOR_SCHEMA,
        "contract": {
            "authority": "soft_observation_only",
            "may_change_object_set": False,
            "may_change_dimensions": False,
            "may_change_architecture": False,
            "may_override_hard_relations": False,
        },
        "accepted": accepted,
        "rejected": rejected,
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "coverage": len(accepted) / max(len(expected), 1),
        "warnings": list(raw.get("warnings", []))
        if isinstance(raw, dict) and isinstance(raw.get("warnings"), list)
        else [],
    }


def soft_prior_alignment(
    plan: dict[str, Any],
    prior: dict[str, Any],
) -> dict[str, Any]:
    room = plan["room"]
    by_id = {
        str(obj["id"]): obj
        for obj in plan.get("objects", [])
        if isinstance(obj, dict) and obj.get("id")
    }
    results: list[dict[str, Any]] = []
    weighted_squared_error = 0.0
    total_weight = 0.0
    for item in prior.get("accepted", []):
        obj = by_id.get(str(item["id"]))
        if not obj:
            continue
        hint = item["room_position_hint"]
        observed = (
            float(obj["x"]) / max(float(room["width"]), 1e-9),
            float(obj["y"]) / max(float(room["length"]), 1e-9),
        )
        target = (float(hint["x_fraction"]), float(hint["y_fraction"]))
        error = math.dist(observed, target)
        weight = float(item["confidence"]) * float(hint["confidence"])
        weighted_squared_error += weight * error * error
        total_weight += weight
        results.append(
            {
                "id": str(item["id"]),
                "plan_fraction": [round(observed[0], 6), round(observed[1], 6)],
                "soft_target_fraction": [target[0], target[1]],
                "normalized_error": round(error, 6),
                "weight": round(weight, 6),
            }
        )
    rmse = (
        math.sqrt(weighted_squared_error / total_weight)
        if total_weight > 0.0
        else None
    )
    return {
        "comparable_object_count": len(results),
        "weight_sum": round(total_weight, 6),
        "weighted_normalized_rmse": round(rmse, 6) if rmse is not None else None,
        "objects": results,
    }


def build_guided_layout_prompt(
    brief: dict[str, Any],
    baseline_plan: dict[str, Any],
    prior: dict[str, Any],
) -> str:
    return (
        _layout_prompt(brief)
        + "\n\nAdditional generated-image observations follow. They are SOFT suggestions only. "
        "The SceneBrief, architecture, exact object set, dimensions, hard relations, boundary, "
        "entry clearance, and support constraints always win. Ignore an observation when satisfying "
        "it would violate any hard rule. Keep changes from the baseline minimal. Image coordinates "
        "were interpreted under a requested south-to-north camera and remain uncertain.\n\n"
        f"Baseline text-only plan:\n{json.dumps(baseline_plan, indent=2, ensure_ascii=False)}\n\n"
        f"Validated soft observations:\n{json.dumps(prior, indent=2, ensure_ascii=False)}"
    )


def guided_codex_layout(
    brief: dict[str, Any],
    baseline_plan: dict[str, Any],
    prior: dict[str, Any],
    output_dir: Path,
    model: str,
) -> dict[str, Any]:
    raw = run_codex_json(
        build_guided_layout_prompt(brief, baseline_plan, prior),
        output_dir,
        stage="layout_plan_reference_soft",
        model=model,
    )
    plan = _normalize_codex_layout(raw, brief)
    plan["planner"] = "codex_exec_with_reference_soft_prior"
    plan["reference_soft_prior"] = {
        "schema": prior["schema"],
        "accepted_count": int(prior["accepted_count"]),
        "authority": "soft_observation_only",
    }
    return plan


def _refresh_pose_semantics(
    plan: dict[str, Any],
    brief: dict[str, Any],
) -> None:
    changes = apply_facing_constraints(plan["objects"])
    changes.extend(
        apply_relation_facing_constraints(
            plan["objects"], plan.get("relations", [])
        )
    )
    plan["orientation_resolution"] = changes
    graph = brief.get("scene_graph")
    if isinstance(graph, dict):
        plan["scene_graph"] = materialize_scene_graph(graph, plan["objects"])


def _bounded_soft_target(
    obj: dict[str, Any],
    hint: dict[str, Any],
    room: dict[str, Any],
    *,
    max_free_displacement: float,
) -> tuple[float, float, str]:
    current_x = float(obj["x"])
    current_y = float(obj["y"])
    target_x = float(hint["x_fraction"]) * float(room["width"])
    target_y = float(hint["y_fraction"]) * float(room["length"])
    wall = str(obj.get("preferred_wall") or "")
    if wall in {"north", "south"}:
        target_y = current_y
        mode = "wall_tangent_x"
    elif wall in {"east", "west"}:
        target_x = current_x
        mode = "wall_tangent_y"
    else:
        mode = "bounded_free_xy"
        dx = target_x - current_x
        dy = target_y - current_y
        distance = math.hypot(dx, dy)
        if distance > max_free_displacement > 0.0:
            scale = max_free_displacement / distance
            target_x = current_x + dx * scale
            target_y = current_y + dy * scale
    object_width, object_length = footprint(obj)
    margin = 0.05
    if mode != "wall_tangent_y":
        target_x = min(
            max(target_x, object_width / 2.0 + margin),
            float(room["width"]) - object_width / 2.0 - margin,
        )
    if mode != "wall_tangent_x":
        target_y = min(
            max(target_y, object_length / 2.0 + margin),
            float(room["length"]) - object_length / 2.0 - margin,
        )
    return target_x, target_y, mode


def project_soft_prior(
    baseline: dict[str, Any],
    prior: dict[str, Any],
    brief: dict[str, Any],
    *,
    max_free_displacement: float = 0.8,
    alphas: tuple[float, ...] = (1.0, 0.75, 0.5, 0.25),
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Greedily apply only hard-valid, score-improving soft pose proposals.

    Wall-associated objects move along their current wall only. Free objects may move
    in 2D, but each proposal is displacement-capped. The unchanged baseline is always
    a valid fallback.
    """

    best = deepcopy(baseline)
    best_score = soft_prior_alignment(best, prior)["weighted_normalized_rmse"]
    audit: dict[str, Any] = {
        "schema": "codex_trellis_reference_soft_projection_v1",
        "policy": {
            "wall_associated_motion": "tangent_only",
            "free_object_max_displacement_m": float(max_free_displacement),
            "candidate_alphas": list(alphas),
            "acceptance": "strictly_lower_soft_rmse_and_hard_validation_ok",
        },
        "baseline_rmse": best_score,
        "attempted_candidates": 0,
        "hard_valid_candidates": 0,
        "accepted_moves": [],
    }
    if best_score is None:
        audit["final_rmse"] = None
        audit["improved"] = False
        return best, audit

    hints = {
        str(item["id"]): item
        for item in prior.get("accepted", [])
        if isinstance(item, dict) and item.get("id")
    }
    ordered_ids = sorted(
        hints,
        key=lambda object_id: (
            -float(hints[object_id].get("confidence", 0.0)),
            object_id,
        ),
    )
    for object_id in ordered_ids:
        current_obj = next(
            (obj for obj in best["objects"] if str(obj.get("id")) == object_id),
            None,
        )
        if current_obj is None:
            continue
        hint = hints[object_id]["room_position_hint"]
        target_x, target_y, motion_mode = _bounded_soft_target(
            current_obj,
            hint,
            best["room"],
            max_free_displacement=float(max_free_displacement),
        )
        move_best: tuple[
            dict[str, Any], dict[str, Any], float, float
        ] | None = None
        for alpha in alphas:
            candidate = deepcopy(best)
            candidate_obj = next(
                obj
                for obj in candidate["objects"]
                if str(obj.get("id")) == object_id
            )
            from_xy = [float(candidate_obj["x"]), float(candidate_obj["y"])]
            candidate_obj["x"] = from_xy[0] + float(alpha) * (
                target_x - from_xy[0]
            )
            candidate_obj["y"] = from_xy[1] + float(alpha) * (
                target_y - from_xy[1]
            )
            _refresh_pose_semantics(candidate, brief)
            validation = validate_layout(candidate)
            audit["attempted_candidates"] += 1
            if not validation["ok"]:
                continue
            audit["hard_valid_candidates"] += 1
            score = soft_prior_alignment(
                candidate, prior
            )["weighted_normalized_rmse"]
            if score is None or score >= float(best_score) - 1e-9:
                continue
            if move_best is None or float(score) < move_best[2]:
                move_best = (candidate, validation, float(score), float(alpha))
        if move_best is None:
            continue
        selected, _, selected_score, selected_alpha = move_best
        selected_obj = next(
            obj
            for obj in selected["objects"]
            if str(obj.get("id")) == object_id
        )
        audit["accepted_moves"].append(
            {
                "id": object_id,
                "motion_mode": motion_mode,
                "alpha": selected_alpha,
                "from_xy": [
                    round(float(current_obj["x"]), 6),
                    round(float(current_obj["y"]), 6),
                ],
                "to_xy": [
                    round(float(selected_obj["x"]), 6),
                    round(float(selected_obj["y"]), 6),
                ],
                "rmse_before": round(float(best_score), 6),
                "rmse_after": round(selected_score, 6),
            }
        )
        best = selected
        best_score = selected_score
    best["planner"] = "reference_soft_prior_projection"
    best["reference_soft_prior"] = {
        "schema": prior.get("schema", SOFT_PRIOR_SCHEMA),
        "accepted_count": int(prior.get("accepted_count", len(hints))),
        "authority": "soft_observation_only",
        "projection_policy": audit["policy"],
    }
    audit["final_rmse"] = round(float(best_score), 6)
    audit["improved"] = float(best_score) < float(audit["baseline_rmse"]) - 1e-9
    return best, audit


def hard_invariant_report(
    brief: dict[str, Any],
    baseline: dict[str, Any],
    guided: dict[str, Any],
) -> dict[str, Any]:
    expected = {str(obj["id"]): obj for obj in brief.get("objects", [])}
    baseline_by_id = {str(obj["id"]): obj for obj in baseline.get("objects", [])}
    guided_by_id = {str(obj["id"]): obj for obj in guided.get("objects", [])}
    checks = {
        "baseline_exact_object_ids": set(baseline_by_id) == set(expected),
        "guided_exact_object_ids": set(guided_by_id) == set(expected),
        "room_dimensions_unchanged": guided.get("room") == baseline.get("room"),
        "architecture_unchanged": guided.get("architecture")
        == baseline.get("architecture"),
        "hard_relations_unchanged": guided.get("relations")
        == baseline.get("relations"),
        "dimensions_unchanged": all(
            guided_by_id.get(object_id, {}).get("dimensions")
            == baseline_by_id.get(object_id, {}).get("dimensions")
            == expected[object_id].get("dimensions")
            for object_id in expected
        ),
        "categories_unchanged": all(
            guided_by_id.get(object_id, {}).get("category")
            == baseline_by_id.get(object_id, {}).get("category")
            == expected[object_id].get("category")
            for object_id in expected
        ),
    }
    return {"ok": all(checks.values()), "checks": checks}


def _repair_plan(plan: dict[str, Any], iterations: int) -> tuple[dict[str, Any], dict[str, Any]]:
    result = deepcopy(plan)
    validation = validate_layout(result)
    for iteration in range(1, int(iterations) + 1):
        if validation["ok"]:
            break
        result = deterministic_repair(result, iteration=iteration)
        validation = validate_layout(result)
    return result, validation


def _generate_reference_with_subprocess(
    prompt_path: Path,
    output_dir: Path,
    *,
    flux_python: Path,
    flux_model: Path,
    width: int,
    height: int,
    steps: int,
    seed: int,
) -> dict[str, Any]:
    image_path = output_dir / "reference_image.png"
    metadata_path = output_dir / "reference_image_generation.json"
    command = [
        str(flux_python),
        "-m",
        "sage.experiments.codex_trellis_scene_v2.flux_reference",
        "--prompt-file",
        str(prompt_path),
        "--model-path",
        str(flux_model),
        "--output-image",
        str(image_path),
        "--metadata-output",
        str(metadata_path),
        "--width",
        str(width),
        "--height",
        str(height),
        "--steps",
        str(steps),
        "--seed",
        str(seed),
    ]
    process = subprocess.run(
        command,
        cwd=Path.cwd(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=900,
        check=False,
    )
    (output_dir / "flux_stdout.txt").write_text(process.stdout, encoding="utf-8")
    (output_dir / "flux_stderr.txt").write_text(process.stderr, encoding="utf-8")
    if process.returncode != 0:
        raise RuntimeError(
            f"FLUX reference generation failed with code {process.returncode}; "
            f"see {output_dir / 'flux_stderr.txt'}"
        )
    return read_json(metadata_path)


def run_reference_soft_prior_experiment(args: Any) -> dict[str, Any]:
    output_dir = Path(args.output_dir).expanduser().resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        if not bool(args.overwrite):
            raise FileExistsError(output_dir)
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    prompt = str(args.prompt or "").strip()
    if args.prompt_file:
        prompt = args.prompt_file.read_text(encoding="utf-8").strip()
    if not prompt:
        raise ValueError("--prompt or --prompt-file is required")
    (output_dir / "selected_prompt.txt").write_text(
        prompt + "\n", encoding="utf-8"
    )
    brief = expand_prompt(
        prompt,
        output_dir,
        room_type_override=args.room_type,
        mode=str(args.expander),
        model=str(args.model),
    )
    architecture = plan_architecture(brief)
    brief["scene_graph"] = build_typed_scene_graph(brief, architecture)
    write_json(output_dir / "scene_brief.json", brief)
    write_json(output_dir / "architecture_plan.json", architecture)

    reference_prompt = build_reference_prompt(brief)
    reference_prompt_path = output_dir / "reference_prompt.txt"
    reference_prompt_path.write_text(reference_prompt + "\n", encoding="utf-8")
    generation = _generate_reference_with_subprocess(
        reference_prompt_path,
        output_dir,
        flux_python=Path(args.flux_python).expanduser().resolve(),
        flux_model=Path(args.flux_model).expanduser().resolve(),
        width=int(args.width),
        height=int(args.height),
        steps=int(args.flux_steps),
        seed=int(args.seed),
    )
    reference_image = Path(generation["output_path"])
    raw_observation = run_codex_image_json(
        build_observer_prompt(brief),
        reference_image,
        output_dir,
        stage="reference_soft_prior_observation",
        model=str(args.model),
    )
    write_json(output_dir / "reference_observation_raw.json", raw_observation)
    prior = validate_soft_prior(
        raw_observation,
        brief,
        minimum_confidence=float(args.minimum_observation_confidence),
    )
    write_json(output_dir / "reference_soft_prior.json", prior)

    if str(args.baseline_planner) == "codex":
        baseline_initial = codex_layout(brief, output_dir, str(args.model))
    else:
        baseline_initial = rules_layout(brief)
    baseline_initial["room"] = deepcopy(brief["room"])
    baseline_initial_validation = validate_layout(baseline_initial)
    write_json(output_dir / "layout_text_only_initial.json", baseline_initial)
    write_json(
        output_dir / "validation_text_only_initial.json",
        baseline_initial_validation,
    )
    baseline, baseline_validation = _repair_plan(
        baseline_initial, int(args.repair_iterations)
    )
    write_json(output_dir / "layout_text_only.json", baseline)
    write_json(output_dir / "validation_text_only.json", baseline_validation)

    guided_initial = guided_codex_layout(
        brief,
        baseline,
        prior,
        output_dir,
        str(args.model),
    )
    guided_initial["room"] = deepcopy(brief["room"])
    guided_initial_validation = validate_layout(guided_initial)
    write_json(output_dir / "layout_reference_soft_initial.json", guided_initial)
    write_json(
        output_dir / "validation_reference_soft_initial.json",
        guided_initial_validation,
    )
    guided_repaired, guided_repaired_validation = _repair_plan(
        guided_initial, int(args.repair_iterations)
    )
    projected, projection_audit = project_soft_prior(
        baseline,
        prior,
        brief,
        max_free_displacement=float(args.max_free_displacement),
    )
    projected_validation = validate_layout(projected)
    guided_repaired_alignment = soft_prior_alignment(guided_repaired, prior)
    projected_alignment = soft_prior_alignment(projected, prior)
    repaired_rmse = guided_repaired_alignment["weighted_normalized_rmse"]
    projected_rmse = projected_alignment["weighted_normalized_rmse"]
    if (
        guided_repaired_validation["ok"]
        and repaired_rmse is not None
        and (
            projected_rmse is None
            or float(repaired_rmse) < float(projected_rmse)
        )
    ):
        guided = guided_repaired
        guided_validation = guided_repaired_validation
        selected_guided_source = "codex_guided_repaired"
    else:
        guided = projected
        guided_validation = projected_validation
        selected_guided_source = "deterministic_soft_projection"
    write_json(output_dir / "soft_projection_audit.json", projection_audit)
    write_json(output_dir / "layout_reference_soft.json", guided)
    write_json(output_dir / "validation_reference_soft.json", guided_validation)

    baseline_alignment = soft_prior_alignment(baseline, prior)
    guided_alignment = soft_prior_alignment(guided, prior)
    baseline_rmse = baseline_alignment["weighted_normalized_rmse"]
    guided_rmse = guided_alignment["weighted_normalized_rmse"]
    alignment_comparable = baseline_rmse is not None and guided_rmse is not None
    invariants = hard_invariant_report(brief, baseline, guided)
    report = {
        "schema": EXPERIMENT_SCHEMA,
        "ok": bool(
            invariants["ok"]
            and baseline_validation["ok"]
            and guided_validation["ok"]
        ),
        "branch_role": "isolated_reference_soft_prior_ablation",
        "output_dir": str(output_dir),
        "model": str(args.model),
        "reference_generation": generation,
        "soft_prior": {
            "path": str(output_dir / "reference_soft_prior.json"),
            "accepted_count": int(prior["accepted_count"]),
            "rejected_count": int(prior["rejected_count"]),
            "coverage": float(prior["coverage"]),
            "authority": "soft_observation_only",
            "minimum_observation_confidence": float(
                args.minimum_observation_confidence
            ),
            "warnings": list(prior.get("warnings", [])),
        },
        "baseline": {
            "planner": str(baseline["planner"]),
            "initial_validation_ok": bool(baseline_initial_validation["ok"]),
            "validation_ok": bool(baseline_validation["ok"]),
            "initial_alignment": soft_prior_alignment(baseline_initial, prior),
            "alignment": baseline_alignment,
        },
        "reference_soft": {
            "planner": str(guided["planner"]),
            "selected_source": selected_guided_source,
            "codex_initial_validation_ok": bool(
                guided_initial_validation["ok"]
            ),
            "codex_initial_alignment": soft_prior_alignment(
                guided_initial, prior
            ),
            "codex_repaired_validation_ok": bool(
                guided_repaired_validation["ok"]
            ),
            "codex_repaired_alignment": guided_repaired_alignment,
            "projection": projection_audit,
            "validation_ok": bool(guided_validation["ok"]),
            "alignment": guided_alignment,
        },
        "hard_invariants": invariants,
        "outcome": {
            "alignment_comparable": alignment_comparable,
            "soft_prior_alignment_improved": (
                float(guided_rmse) < float(baseline_rmse)
                if alignment_comparable
                else None
            ),
            "normalized_rmse_delta": (
                round(float(guided_rmse) - float(baseline_rmse), 6)
                if alignment_comparable
                else None
            ),
            "hard_validation_preserved": (
                bool(guided_validation["ok"])
                if baseline_validation["ok"]
                else None
            ),
        },
        "limitations": [
            "This phase evaluates soft-prior extraction and layout alignment; relation-aware SDF is not yet integrated into the full planner.",
            "The generated single view has uncertain depth and may omit or duplicate objects.",
            "A lower soft-prior RMSE is not by itself evidence of better final 3D visual quality.",
            "Final claims require equal-asset Blender renders, multi-view scoring, and the same SDF validator for both branches.",
        ],
    }
    write_json(output_dir / "reference_soft_prior_ab_report.json", report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Isolated text-only versus generated-reference soft layout prior experiment."
    )
    parser.add_argument("--prompt")
    parser.add_argument("--prompt-file", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--room-type",
        choices=("bedroom", "living_room", "kitchen", "study", "restroom"),
    )
    parser.add_argument("--model", default=os.environ.get("SAGE_CODEX_MODEL", "gpt-5.6-sol"))
    parser.add_argument("--expander", choices=("rules", "hybrid", "codex"), default="rules")
    parser.add_argument("--baseline-planner", choices=("rules", "codex"), default="codex")
    parser.add_argument("--repair-iterations", type=int, default=2)
    parser.add_argument(
        "--flux-python",
        default="/data/wsj/anaconda3/envs/simgen/bin/python",
    )
    parser.add_argument(
        "--flux-model",
        default="/data/wsj/models/text_to_image__primary",
    )
    parser.add_argument("--width", type=int, default=768)
    parser.add_argument("--height", type=int, default=768)
    parser.add_argument("--flux-steps", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20260724)
    parser.add_argument("--minimum-observation-confidence", type=float, default=0.75)
    parser.add_argument("--max-free-displacement", type=float, default=0.8)
    return parser


def main(argv: list[str] | None = None) -> int:
    report = run_reference_soft_prior_experiment(build_parser().parse_args(argv))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
