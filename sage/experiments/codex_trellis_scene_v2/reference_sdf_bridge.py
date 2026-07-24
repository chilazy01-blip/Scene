from __future__ import annotations

import argparse
import json
import math
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any

import numpy as np
import trimesh

from .capabilities import (
    capability_index,
    load_capability_registry,
    require_free_space,
)
from .collision_proxy import build_capability_proxy, load_normalized_asset_mesh
from .io_utils import read_json, write_json
from .scene_graph import materialize_scene_graph
from .under_desk_pilot import (
    classify_under_desk_points,
    optimize_tucked_under_pose,
)
from .validator import validate_layout


REFERENCE_SDF_BINDING_SCHEMA = "codex_trellis_reference_sdf_binding_v1"
REFERENCE_SDF_AUDIT_SCHEMA = "codex_trellis_reference_sdf_repair_audit_v1"
RELATION_AWARE_VALIDATION_SCHEMA = (
    "codex_trellis_relation_aware_layout_validation_v1"
)


def _normalize_yaw(value: float) -> float:
    result = float(value) % 360.0
    return 0.0 if abs(result - 360.0) < 1e-9 else result


def world_to_target_local(
    world_pose: dict[str, float], target_world_pose: dict[str, float]
) -> dict[str, float]:
    yaw = math.radians(float(target_world_pose["yaw"]))
    dx = float(world_pose["x"]) - float(target_world_pose["x"])
    dy = float(world_pose["y"]) - float(target_world_pose["y"])
    return {
        "x": math.cos(yaw) * dx + math.sin(yaw) * dy,
        "y": -math.sin(yaw) * dx + math.cos(yaw) * dy,
        "z": float(world_pose["z"]) - float(target_world_pose["z"]),
        "yaw": _normalize_yaw(
            float(world_pose["yaw"]) - float(target_world_pose["yaw"])
        ),
    }


def target_local_to_world(
    local_pose: dict[str, float], target_world_pose: dict[str, float]
) -> dict[str, float]:
    yaw = math.radians(float(target_world_pose["yaw"]))
    return {
        "x": float(target_world_pose["x"])
        + math.cos(yaw) * float(local_pose["x"])
        - math.sin(yaw) * float(local_pose["y"]),
        "y": float(target_world_pose["y"])
        + math.sin(yaw) * float(local_pose["x"])
        + math.cos(yaw) * float(local_pose["y"]),
        "z": float(target_world_pose["z"]) + float(local_pose["z"]),
        "yaw": _normalize_yaw(
            float(target_world_pose["yaw"]) + float(local_pose["yaw"])
        ),
    }


def validate_binding_contract(binding: Any) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(binding, dict):
        return {
            "ok": False,
            "errors": ["binding contract must be an object"],
            "error_count": 1,
        }
    if binding.get("schema") != REFERENCE_SDF_BINDING_SCHEMA:
        errors.append(f"schema must be {REFERENCE_SDF_BINDING_SCHEMA}")
    relations = binding.get("relations")
    if not isinstance(relations, list) or not relations:
        errors.append("relations must be a non-empty list")
        relations = []
    seen: set[tuple[str, str, str]] = set()
    required = (
        "source_object_id",
        "target_object_id",
        "source_asset_id",
        "target_asset_id",
        "free_space_id",
    )
    for index, item in enumerate(relations):
        prefix = f"relations[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be an object")
            continue
        if item.get("relation_type") != "tucked_under":
            errors.append(f"{prefix}.relation_type must be tucked_under")
        for key in required:
            if not str(item.get(key) or ""):
                errors.append(f"{prefix}.{key} must be non-empty")
        relation_key = (
            str(item.get("source_object_id") or ""),
            str(item.get("relation_type") or ""),
            str(item.get("target_object_id") or ""),
        )
        if relation_key in seen:
            errors.append(f"duplicate relation binding: {relation_key}")
        seen.add(relation_key)
    return {"ok": not errors, "errors": errors, "error_count": len(errors)}


def _relation_parts(item: Any) -> tuple[str, str, str, str, dict[str, Any]]:
    if isinstance(item, (list, tuple)) and len(item) == 3:
        return (
            str(item[0]),
            str(item[1]),
            str(item[2]),
            "soft",
            {},
        )
    if isinstance(item, dict):
        parameters = item.get("parameters")
        return (
            str(item.get("source") or item.get("subject") or ""),
            str(item.get("type") or item.get("predicate") or ""),
            str(item.get("target") or item.get("object") or ""),
            str(item.get("strength") or "soft"),
            deepcopy(parameters) if isinstance(parameters, dict) else {},
        )
    return "", "", "", "", {}


def _find_hard_relation(
    plan: dict[str, Any], source: str, relation_type: str, target: str
) -> dict[str, Any]:
    for item in plan.get("relations", []):
        item_source, item_type, item_target, strength, parameters = (
            _relation_parts(item)
        )
        if (item_source, item_type, item_target) != (
            source,
            relation_type,
            target,
        ):
            continue
        if strength != "hard":
            raise ValueError(
                f"{source} {relation_type} {target} must be a hard relation"
            )
        return {
            "source": source,
            "type": relation_type,
            "target": target,
            "strength": strength,
            "parameters": parameters,
        }
    raise KeyError(f"missing hard relation: {source} {relation_type} {target}")


def _observation_index(prior: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item["id"]): item
        for item in prior.get("accepted", [])
        if isinstance(item, dict) and item.get("id")
    }


def _observation_weight(item: dict[str, Any]) -> float:
    hint = item["room_position_hint"]
    return min(
        1.0,
        max(
            0.0,
            float(item.get("confidence", 0.0))
            * float(hint.get("confidence", 0.0)),
        ),
    )


def derive_tucked_under_reference_target(
    plan: dict[str, Any],
    prior: dict[str, Any],
    relation: dict[str, Any],
    free_space: dict[str, Any],
) -> dict[str, Any]:
    """Convert accepted room observations into the target asset's local frame."""

    by_id = {
        str(obj["id"]): obj
        for obj in plan.get("objects", [])
        if isinstance(obj, dict) and obj.get("id")
    }
    source_id = str(relation["source"])
    target_id = str(relation["target"])
    source = by_id.get(source_id)
    target = by_id.get(target_id)
    if source is None or target is None:
        raise KeyError("relation endpoints are missing from the layout")
    observations = _observation_index(prior)
    source_observation = observations.get(source_id)
    if source_observation is None:
        raise KeyError(f"no accepted image observation for {source_id}")
    room = plan["room"]
    source_hint = source_observation["room_position_hint"]
    source_observed_world = {
        "x": float(source_hint["x_fraction"]) * float(room["width"]),
        "y": float(source_hint["y_fraction"]) * float(room["length"]),
        "z": float(source.get("z", 0.0)),
        "yaw": float(source.get("yaw", 0.0)),
    }
    target_observation = observations.get(target_id)
    target_world = {
        "x": float(target["x"]),
        "y": float(target["y"]),
        "z": float(target.get("z", 0.0)),
        "yaw": float(target.get("yaw", 0.0)),
    }
    if target_observation is not None:
        target_hint = target_observation["room_position_hint"]
        observed_target_world = {
            "x": float(target_hint["x_fraction"]) * float(room["width"]),
            "y": float(target_hint["y_fraction"]) * float(room["length"]),
            "z": float(target.get("z", 0.0)),
            "yaw": float(target.get("yaw", 0.0)),
        }
        relative_world = {
            "x": target_world["x"]
            + source_observed_world["x"]
            - observed_target_world["x"],
            "y": target_world["y"]
            + source_observed_world["y"]
            - observed_target_world["y"],
            "z": source_observed_world["z"],
            "yaw": source_observed_world["yaw"],
        }
        confidence = min(
            _observation_weight(source_observation),
            _observation_weight(target_observation),
        )
        position_source = "source_and_target_image_observations"
    else:
        relative_world = source_observed_world
        confidence = 0.75 * _observation_weight(source_observation)
        position_source = "source_observation_against_planned_target"
    local = world_to_target_local(relative_world, target_world)
    required_yaw = float(free_space["entry_pose"]["yaw_degrees"])
    return {
        "source": "accepted_reference_observation_to_target_local",
        "source_object_id": source_id,
        "target_object_id": target_id,
        "translation_m": [float(local["x"]), float(local["y"]), float(local["z"])],
        "yaw_degrees": required_yaw,
        "confidence": float(confidence),
        "position_source": position_source,
        "yaw_source": "target_free_space_capability",
        "source_observation": deepcopy(source_observation),
        "target_observation": deepcopy(target_observation),
    }


def _dimensions_match(
    obj: dict[str, Any], capability: dict[str, Any], tolerance: float = 1e-6
) -> bool:
    expected = capability["coordinate_frame"]["canonical_dimensions"]
    actual = obj["dimensions"]
    return all(
        abs(float(actual[axis]) - float(expected[axis])) <= tolerance
        for axis in ("width", "length", "height")
    )


def _relation_aware_validation(
    plan: dict[str, Any],
    *,
    source_id: str,
    target_id: str,
    dense_classification: dict[str, Any],
) -> dict[str, Any]:
    base = validate_layout(plan)
    pair = {str(source_id), str(target_id)}
    waived: list[dict[str, Any]] = []
    active: list[dict[str, Any]] = []
    may_waive = (
        dense_classification.get("classification") == "valid_under"
        and int(dense_classification.get("deep_penetration_point_count", 1)) == 0
    )
    for violation in base["violations"]:
        is_bound_pair_collision = (
            violation.get("type") == "floor_collision"
            and {str(value) for value in violation.get("objects", [])} == pair
        )
        if may_waive and is_bound_pair_collision:
            waived.append(
                {
                    **deepcopy(violation),
                    "waiver": "dense capability-bound SDF accepted tucked_under",
                }
            )
        else:
            active.append(deepcopy(violation))
    hard = [item for item in active if item.get("severity") == "hard"]
    soft = [item for item in active if item.get("severity") == "soft"]
    return {
        "schema": RELATION_AWARE_VALIDATION_SCHEMA,
        "ok": not hard,
        "hard_violation_count": len(hard),
        "soft_violation_count": len(soft),
        "violations": active,
        "waived_broad_phase_violations": waived,
        "base_validation": base,
        "sdf_authority": {
            "source_id": source_id,
            "target_id": target_id,
            "classification": dense_classification.get("classification"),
            "deep_penetration_point_count": int(
                dense_classification.get("deep_penetration_point_count", 0)
            ),
            "penetration_tolerance_m": float(
                dense_classification.get("penetration_tolerance_m", 0.0)
            ),
        },
    }


def apply_reference_relation_sdf_repair(
    plan: dict[str, Any],
    prior: dict[str, Any],
    brief: dict[str, Any],
    binding: dict[str, Any],
    *,
    capability_registry_path: Path,
    asset_root: Path,
    cache_dir: Path,
    sparse_point_count: int = 4096,
    seed: int = 20260724,
    verify_hash: bool = True,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    validation = validate_binding_contract(binding)
    if not validation["ok"]:
        raise ValueError("invalid relation SDF binding: " + "; ".join(validation["errors"]))
    relation_bindings = binding["relations"]
    if len(relation_bindings) != 1:
        raise ValueError("the current pilot accepts exactly one relation binding")
    relation_binding = relation_bindings[0]
    source_id = str(relation_binding["source_object_id"])
    target_id = str(relation_binding["target_object_id"])
    relation = _find_hard_relation(plan, source_id, "tucked_under", target_id)
    free_space_id = str(relation_binding["free_space_id"])
    if str(relation["parameters"].get("free_space_id") or "") != free_space_id:
        raise ValueError("typed relation and asset binding free_space_id disagree")

    registry = load_capability_registry(capability_registry_path)
    capabilities = capability_index(registry)
    source_capability = capabilities[str(relation_binding["source_asset_id"])]
    target_capability = capabilities[str(relation_binding["target_asset_id"])]
    free_space = require_free_space(target_capability, free_space_id)
    by_id = {
        str(obj["id"]): obj
        for obj in plan.get("objects", [])
        if isinstance(obj, dict) and obj.get("id")
    }
    source_obj = by_id[source_id]
    target_obj = by_id[target_id]
    if str(source_obj.get("category")) != str(source_capability["category"]):
        raise ValueError("source object category does not match bound capability")
    if str(target_obj.get("category")) != str(target_capability["category"]):
        raise ValueError("target object category does not match bound capability")
    if not _dimensions_match(source_obj, source_capability):
        raise ValueError("source object dimensions do not match bound capability")
    if not _dimensions_match(target_obj, target_capability):
        raise ValueError("target object dimensions do not match bound capability")

    cache_dir.mkdir(parents=True, exist_ok=True)
    target_sdf, _, target_proxy_report = build_capability_proxy(
        target_capability,
        asset_root,
        cache_dir / f"{target_capability['asset_id']}.voxel_sdf.npz",
        verify_hash=verify_hash,
    )
    source_mesh, source_normalization = load_normalized_asset_mesh(
        source_capability,
        asset_root,
        verify_hash=verify_hash,
    )
    sparse_points, _ = trimesh.sample.sample_surface(
        source_mesh,
        int(sparse_point_count),
        seed=int(seed),
    )
    sparse_points = np.asarray(sparse_points, dtype=np.float64)
    reference_target = derive_tucked_under_reference_target(
        plan, prior, relation, free_space
    )
    target_world = {
        "x": float(target_obj["x"]),
        "y": float(target_obj["y"]),
        "z": float(target_obj.get("z", 0.0)),
        "yaw": float(target_obj.get("yaw", 0.0)),
    }
    source_world = {
        "x": float(source_obj["x"]),
        "y": float(source_obj["y"]),
        "z": float(source_obj.get("z", 0.0)),
        "yaw": float(source_obj.get("yaw", 0.0)),
    }
    baseline_local = world_to_target_local(source_world, target_world)
    optimization = optimize_tucked_under_pose(
        target_sdf,
        sparse_points,
        parent_dimensions=target_capability["coordinate_frame"][
            "canonical_dimensions"
        ],
        child_dimensions=source_capability["coordinate_frame"][
            "canonical_dimensions"
        ],
        free_space=free_space,
        reference_target=reference_target,
        baseline_pose={
            "translation_m": [
                baseline_local["x"],
                baseline_local["y"],
                baseline_local["z"],
            ],
            "yaw_degrees": baseline_local["yaw"],
        },
    )
    selected_local = optimization["selected"]["pose"]
    dense_classification = classify_under_desk_points(
        target_sdf,
        np.asarray(source_mesh.vertices, dtype=np.float64),
        parent_dimensions=target_capability["coordinate_frame"][
            "canonical_dimensions"
        ],
        child_dimensions=source_capability["coordinate_frame"][
            "canonical_dimensions"
        ],
        translation_m=[
            float(selected_local["x"]),
            float(selected_local["y"]),
            float(selected_local["z"]),
        ],
        yaw_degrees=float(selected_local["yaw"]),
        free_space=free_space,
    )
    if dense_classification["classification"] != "valid_under":
        raise RuntimeError("dense reference rejected the sparse-selected pose")

    selected_world = target_local_to_world(selected_local, target_world)
    result = deepcopy(plan)
    result_source = next(
        obj for obj in result["objects"] if str(obj.get("id")) == source_id
    )
    result_target = next(
        obj for obj in result["objects"] if str(obj.get("id")) == target_id
    )
    before_world = {
        key: float(result_source.get(key, 0.0))
        for key in ("x", "y", "z", "yaw")
    }
    result_source.update(selected_world)
    if isinstance(brief.get("scene_graph"), dict):
        result["scene_graph"] = materialize_scene_graph(
            brief["scene_graph"], result["objects"]
        )
    relation_validation = _relation_aware_validation(
        result,
        source_id=source_id,
        target_id=target_id,
        dense_classification=dense_classification,
    )
    audit = {
        "schema": REFERENCE_SDF_AUDIT_SCHEMA,
        "ok": bool(relation_validation["ok"]),
        "binding_validation": validation,
        "relation_binding": deepcopy(relation_binding),
        "typed_relation": relation,
        "reference_target_local": reference_target,
        "baseline_pose_local": baseline_local,
        "selected_pose_local": deepcopy(selected_local),
        "before_pose_world": before_world,
        "selected_pose_world": selected_world,
        "optimization": optimization,
        "dense_selected_classification": dense_classification,
        "target_proxy": target_proxy_report,
        "source_normalization": source_normalization,
        "relation_aware_validation": relation_validation,
        "hard_invariants": {
            "object_ids_unchanged": {
                str(obj["id"]) for obj in result["objects"]
            }
            == {str(obj["id"]) for obj in plan["objects"]},
            "relations_unchanged": result.get("relations") == plan.get("relations"),
            "source_dimensions_unchanged": result_source.get("dimensions")
            == source_obj.get("dimensions"),
            "target_pose_unchanged": all(
                abs(
                    float(target_obj.get(key, 0.0))
                    - float(result_target.get(key, 0.0))
                )
                <= 1e-9
                for key in ("x", "y", "z", "yaw")
            ),
        },
    }
    audit["ok"] = bool(
        audit["ok"] and all(audit["hard_invariants"].values())
    )
    return result, audit, relation_validation


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Replay one explicit whole-room reference observation to "
            "capability-bound tucked_under SDF repair."
        )
    )
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--prior", required=True, type=Path)
    parser.add_argument("--brief", required=True, type=Path)
    parser.add_argument("--binding", required=True, type=Path)
    parser.add_argument("--capability-registry", required=True, type=Path)
    parser.add_argument("--asset-root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--sparse-point-count", type=int, default=4096)
    parser.add_argument("--seed", type=int, default=20260724)
    parser.add_argument(
        "--verify-hash",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    plan = read_json(args.plan.expanduser().resolve())
    prior = read_json(args.prior.expanduser().resolve())
    brief = read_json(args.brief.expanduser().resolve())
    binding = read_json(args.binding.expanduser().resolve())
    output_dir = args.output_dir.expanduser().resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        if not args.overwrite:
            raise FileExistsError(output_dir)
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    result, audit, validation = apply_reference_relation_sdf_repair(
        plan,
        prior,
        brief,
        binding,
        capability_registry_path=args.capability_registry.expanduser().resolve(),
        asset_root=args.asset_root.expanduser().resolve(),
        cache_dir=output_dir / "relation_sdf_cache",
        sparse_point_count=int(args.sparse_point_count),
        seed=int(args.seed),
        verify_hash=bool(args.verify_hash),
    )
    write_json(output_dir / "layout_after.json", result)
    write_json(
        output_dir / "reference_relation_sdf_repair_audit.json", audit
    )
    write_json(output_dir / "validation_after.json", validation)
    print(json.dumps(audit, indent=2, ensure_ascii=False))
    return 0 if audit["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
