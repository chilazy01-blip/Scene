from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np


GEOMETRY_CONTRACT_SCHEMA = "codex_trellis_relation_geometry_contract_v1"
GEOMETRY_CERTIFICATE_SCHEMA = "codex_trellis_geometry_certificate_v1"

RELATION_SLOT_TYPES = {
    "supported_by": ("support_surfaces", "bounded_plane_support"),
    "contained_in": ("containment_volumes", "full_containment"),
    "tucked_under": ("free_space_volumes", "partial_entry"),
    "partially_inserted": ("free_space_volumes", "partial_entry"),
    "against": ("contact_surfaces", "bounded_plane_contact"),
    "contact": ("contact_surfaces", "bounded_plane_contact"),
}


class DistanceProxy(Protocol):
    pitch: float

    def query(self, points: np.ndarray) -> np.ndarray: ...


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def content_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def pose_matrix(pose: dict[str, Any] | np.ndarray | None) -> np.ndarray:
    if pose is None:
        return np.eye(4, dtype=np.float64)
    if isinstance(pose, np.ndarray):
        matrix = np.asarray(pose, dtype=np.float64)
        if matrix.shape != (4, 4):
            raise ValueError("pose matrix must be 4x4")
        return matrix
    translation = pose.get("translation_m", pose)
    x = float(translation.get("x", 0.0))
    y = float(translation.get("y", 0.0))
    z = float(translation.get("z", 0.0))
    angle = math.radians(float(pose.get("yaw_degrees", 0.0)))
    cosine, sine = math.cos(angle), math.sin(angle)
    matrix = np.array(
        [
            [cosine, -sine, 0.0, x],
            [sine, cosine, 0.0, y],
            [0.0, 0.0, 1.0, z],
            [0.0, 0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )
    return matrix


def transform_points(points: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    points = np.asarray(points, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError("points must have shape (N, 3)")
    return points @ matrix[:3, :3].T + matrix[:3, 3]


def _slot_index(
    capability: dict[str, Any], collection: str
) -> dict[str, dict[str, Any]]:
    return {
        str(slot["id"]): slot
        for slot in capability.get(collection, [])
        if isinstance(slot, dict) and slot.get("id")
    }


def compile_relation_geometry(
    relation: dict[str, Any],
    source_capability: dict[str, Any],
    target_capability: dict[str, Any],
) -> dict[str, Any]:
    """Compile a scene relation into geometry predicates without category branches."""

    relation_type = str(relation.get("type") or relation.get("relation") or "")
    if relation_type not in RELATION_SLOT_TYPES:
        raise ValueError(f"unsupported geometry relation: {relation_type!r}")
    collection, evaluator = RELATION_SLOT_TYPES[relation_type]
    slot_id = str(
        relation.get("target_slot_id")
        or relation.get("capability_id")
        or relation.get("free_space_id")
        or ""
    )
    slots = _slot_index(target_capability, collection)
    if not slot_id:
        if len(slots) != 1:
            raise ValueError(
                f"relation {relation_type} must select one target slot from {collection}"
            )
        slot_id = next(iter(slots))
    if slot_id not in slots:
        raise KeyError(
            f"target asset {target_capability.get('asset_id')} has no "
            f"{collection} slot {slot_id!r}"
        )
    slot = slots[slot_id]
    allowed = slot.get("allowed_categories")
    source_category = str(source_capability.get("category") or "")
    if isinstance(allowed, list) and allowed and source_category not in allowed:
        raise ValueError(
            f"source category {source_category!r} is not allowed by slot {slot_id!r}"
        )

    tolerance = float(
        relation.get("contact_tolerance_m")
        or slot.get("contact_tolerance_m")
        or slot.get("clearance_m")
        or 0.005
    )
    if tolerance <= 0.0:
        raise ValueError("geometry tolerance must be positive")
    anchor_id = relation.get("source_anchor_id")
    source_anchor = None
    if anchor_id:
        anchors = _slot_index(source_capability, "semantic_anchors")
        if str(anchor_id) not in anchors:
            raise KeyError(
                f"source asset {source_capability.get('asset_id')} has no "
                f"semantic anchor {anchor_id!r}"
            )
        source_anchor = anchors[str(anchor_id)]
    contract = {
        "schema": GEOMETRY_CONTRACT_SCHEMA,
        "relation_type": relation_type,
        "source_asset_id": str(source_capability.get("asset_id") or ""),
        "target_asset_id": str(target_capability.get("asset_id") or ""),
        "source_capability_hash": content_hash(source_capability),
        "target_capability_hash": content_hash(target_capability),
        "target_slot_collection": collection,
        "target_slot_id": slot_id,
        "evaluator": evaluator,
        "target_slot": slot,
        "source_anchor_id": anchor_id,
        "source_anchor": source_anchor,
        "tolerance_m": tolerance,
        "verification_policy": str(
            relation.get("verification_policy") or "conservative_bilateral"
        ),
    }
    contract["contract_hash"] = content_hash(contract)
    return contract


def _points_in_box(
    points: np.ndarray, minimum: np.ndarray, maximum: np.ndarray
) -> np.ndarray:
    return np.all((points >= minimum) & (points <= maximum), axis=1)


def _bounded_plane_metrics(points: np.ndarray, slot: dict[str, Any]) -> dict[str, Any]:
    center = np.asarray(slot["center_m"], dtype=np.float64)
    normal = np.asarray(slot["normal"], dtype=np.float64)
    normal /= max(np.linalg.norm(normal), 1e-12)
    u_axis = np.asarray(slot["u_axis"], dtype=np.float64)
    u_axis /= max(np.linalg.norm(u_axis), 1e-12)
    v_axis = np.asarray(slot["v_axis"], dtype=np.float64)
    v_axis /= max(np.linalg.norm(v_axis), 1e-12)
    half = np.asarray(slot["half_extents_m"], dtype=np.float64)
    relative = points - center
    normal_distance = relative @ normal
    u = relative @ u_axis
    v = relative @ v_axis
    footprint = (np.abs(u) <= half[0]) & (np.abs(v) <= half[1])
    return {
        "normal_distance_m": normal_distance,
        "footprint_mask": footprint,
        "footprint_fraction": float(np.mean(footprint)) if len(points) else 0.0,
    }


def _relation_predicate(
    contract: dict[str, Any], points_target_local: np.ndarray
) -> dict[str, Any]:
    slot = contract["target_slot"]
    evaluator = contract["evaluator"]
    tolerance = float(contract["tolerance_m"])
    if evaluator in {"full_containment", "partial_entry"}:
        minimum = np.asarray(slot["min_m"], dtype=np.float64)
        maximum = np.asarray(slot["max_m"], dtype=np.float64)
        coordinate_scale = max(
            (
                float(np.max(np.abs(points_target_local)))
                if len(points_target_local)
                else 0.0
            ),
            float(np.max(np.abs(minimum))),
            float(np.max(np.abs(maximum))),
            1.0,
        )
        numeric_error = float(np.finfo(np.float64).eps * coordinate_scale * 16.0)
        if evaluator == "full_containment":
            clearance = float(slot.get("clearance_m", 0.0))
            classified_minimum = minimum + clearance
            classified_maximum = maximum - clearance
            lower_margin = points_target_local - classified_minimum
            upper_margin = classified_maximum - points_target_local
            signed_clearance = np.min(
                np.concatenate((lower_margin, upper_margin), axis=1), axis=1
            )
            inside = signed_clearance >= -numeric_error
            boundary = np.abs(signed_clearance) <= numeric_error
            fraction = float(np.mean(inside)) if len(inside) else 0.0
            return {
                "ok": bool(len(inside) and np.all(inside)),
                "inside_fraction": fraction,
                "required_inside_fraction": 1.0,
                "inside_count": int(np.count_nonzero(inside)),
                "outside_count": int(np.count_nonzero(~inside)),
                "boundary_count": int(np.count_nonzero(boundary)),
                "minimum_signed_clearance_m": (
                    float(np.min(signed_clearance)) if len(signed_clearance) else None
                ),
                "inside_outside_classifier": "analytic_convex_box_binary64_v1",
                "classification_complete": True,
                "classification_numeric_error_bound_m": numeric_error,
            }
        inside = _points_in_box(points_target_local, minimum, maximum)
        fraction = float(np.mean(inside)) if len(inside) else 0.0
        required = float(
            slot.get(
                "minimum_geometry_fraction_inside",
                slot.get("minimum_footprint_overlap", 0.15),
            )
        )
        entry_axis_value = slot.get("entry_axis")
        minimum_depth = float(slot.get("minimum_entry_depth_m", 0.0))
        maximum_depth = None
        depth_ok = True
        if entry_axis_value is not None and minimum_depth > 0.0:
            outward = np.asarray(entry_axis_value, dtype=np.float64)
            outward /= max(np.linalg.norm(outward), 1e-12)
            portal_corner = np.where(outward >= 0.0, maximum, minimum)
            portal_projection = float(np.dot(portal_corner, outward))
            depths = portal_projection - points_target_local @ outward
            maximum_depth = float(np.max(depths)) if len(depths) else None
            depth_ok = bool(
                maximum_depth is not None and maximum_depth >= minimum_depth
            )
        return {
            "ok": bool(fraction + 1e-12 >= required and depth_ok),
            "inside_fraction": fraction,
            "required_inside_fraction": required,
            "maximum_entry_depth_m": maximum_depth,
            "minimum_entry_depth_m": minimum_depth,
            "entry_depth_ok": depth_ok,
            "inside_outside_classifier": "analytic_box_binary64_v1",
            "classification_complete": True,
            "classification_numeric_error_bound_m": numeric_error,
        }

    plane = _bounded_plane_metrics(points_target_local, slot)
    distance = plane.pop("normal_distance_m")
    footprint = plane.pop("footprint_mask")
    near = np.abs(distance) <= tolerance
    contact_fraction = float(np.mean(near & footprint)) if len(distance) else 0.0
    required = float(slot.get("minimum_contact_fraction", 0.05))
    if evaluator == "bounded_plane_support":
        above = distance >= -tolerance
        ok = bool(
            len(distance)
            and np.all(above)
            and np.any(near & footprint)
            and plane["footprint_fraction"]
            >= float(slot.get("minimum_footprint_overlap", 0.5))
        )
    else:
        ok = bool(contact_fraction + 1e-12 >= required)
    return {
        "ok": ok,
        **plane,
        "contact_fraction": contact_fraction,
        "required_contact_fraction": required,
        "minimum_plane_distance_m": float(np.min(distance)) if len(distance) else None,
    }


def _collision_direction(
    points_world: np.ndarray,
    other_world_from_local: np.ndarray,
    proxy: DistanceProxy | None,
    tolerance: float,
    *,
    ambiguous_refinement_threshold: float = 0.02,
) -> dict[str, Any]:
    if proxy is None:
        return {"complete": False, "deep_count": None, "minimum_distance_m": None}
    points_other_local = transform_points(
        points_world, np.linalg.inv(other_world_from_local)
    )
    manifest = getattr(proxy, "manifest", {})
    proxy_levels = getattr(proxy, "levels", {})
    level_entries = (
        list(manifest.get("levels", []))
        if isinstance(manifest, dict) and isinstance(proxy_levels, dict)
        else []
    )
    ordered_levels = [
        str(entry["name"])
        for entry in sorted(
            level_entries, key=lambda item: float(item["pitch_m"]), reverse=True
        )
        if str(entry.get("name") or "") in proxy_levels
    ]
    if not ordered_levels:
        ordered_levels = [""]

    def query(level_name: str, points: np.ndarray) -> tuple[np.ndarray, float, float]:
        if level_name:
            selected = proxy_levels[level_name]
            result = np.asarray(proxy.query(points, level=level_name), dtype=np.float64)
            level_metadata = getattr(selected, "metadata", {})
            pitch = float(selected.pitch)
        else:
            result = np.asarray(proxy.query(points), dtype=np.float64)
            level_metadata = getattr(proxy, "metadata", {})
            pitch = float(proxy.pitch)
        uncertainty_value = float(
            level_metadata.get("max_discretization_error_m", 0.0)
            if isinstance(level_metadata, dict)
            else 0.0
        )
        return result.copy(), pitch, uncertainty_value

    distances, initial_pitch, initial_uncertainty = query(
        ordered_levels[0], points_other_local
    )
    uncertainty_by_point = np.full(
        len(distances), initial_uncertainty, dtype=np.float64
    )
    pitch_by_point = np.full(len(distances), initial_pitch, dtype=np.float64)

    def masks() -> tuple[np.ndarray, np.ndarray]:
        deep_mask = distances < -(tolerance + uncertainty_by_point)
        ambiguous_mask = (distances < 0.0) & ~deep_mask
        return deep_mask, ambiguous_mask

    deep, ambiguous = masks()
    initial_ambiguous_count = int(np.count_nonzero(ambiguous))
    initial_ambiguous_fraction = (
        float(initial_ambiguous_count / len(distances)) if len(distances) else 0.0
    )
    refinement_levels: list[dict[str, Any]] = []
    refined_indices = np.nonzero(ambiguous)[0]
    # The coarse outer proxy is useful for rejecting clearly separated points,
    # but every negative/uncertain sample is refined when a smaller-pitch level
    # exists so the new hierarchy never weakens the former finest-level check.
    # The threshold remains explicit as the policy signal for high-ambiguity
    # escalation and reporting.
    if len(refined_indices):
        for level_name in ordered_levels[1:]:
            if not len(refined_indices):
                break
            refined_distances, pitch, uncertainty = query(
                level_name, points_other_local[refined_indices]
            )
            distances[refined_indices] = refined_distances
            uncertainty_by_point[refined_indices] = uncertainty
            pitch_by_point[refined_indices] = pitch
            refinement_levels.append(
                {
                    "level": level_name,
                    "pitch_m": pitch,
                    "uncertainty_m": uncertainty,
                    "sample_count": int(len(refined_indices)),
                }
            )
            deep, ambiguous = masks()
            refined_indices = np.nonzero(ambiguous)[0]
    finest_queried_pitch = (
        float(refinement_levels[-1]["pitch_m"]) if refinement_levels else initial_pitch
    )
    maximum_active_pitch = (
        float(np.max(pitch_by_point)) if len(pitch_by_point) else initial_pitch
    )
    final_uncertainty = (
        float(np.max(uncertainty_by_point)) if len(uncertainty_by_point) else 0.0
    )
    deep_threshold = -(tolerance + final_uncertainty)
    return {
        "complete": True,
        "sample_count": int(len(distances)),
        "deep_count": int(np.count_nonzero(deep)),
        "ambiguous_count": int(np.count_nonzero(ambiguous)),
        "ambiguous_fraction": (
            float(np.count_nonzero(ambiguous) / len(distances))
            if len(distances)
            else 0.0
        ),
        "minimum_distance_m": float(np.min(distances)) if len(distances) else None,
        "proxy_pitch_m": maximum_active_pitch,
        "finest_queried_pitch_m": finest_queried_pitch,
        "proxy_uncertainty_m": final_uncertainty,
        "deep_penetration_threshold_m": deep_threshold,
        "local_refinement": {
            "trigger_threshold_fraction": float(ambiguous_refinement_threshold),
            "triggered": bool(refinement_levels),
            "initial_level": ordered_levels[0] or None,
            "initial_pitch_m": initial_pitch,
            "initial_uncertainty_m": initial_uncertainty,
            "initial_ambiguous_count": initial_ambiguous_count,
            "initial_ambiguous_fraction": initial_ambiguous_fraction,
            "threshold_exceeded": bool(
                initial_ambiguous_fraction > ambiguous_refinement_threshold
            ),
            "levels": refinement_levels,
            "residual_ambiguous_count": int(np.count_nonzero(ambiguous)),
        },
    }


def _anchor_relation_points(
    contract: dict[str, Any], source_points_local: np.ndarray
) -> np.ndarray:
    anchor = contract.get("source_anchor")
    if not isinstance(anchor, dict):
        return source_points_local
    shape = anchor.get("shape")
    if shape == "point":
        return np.asarray([anchor["point_m"]], dtype=np.float64)
    if shape == "box":
        inside = _points_in_box(
            source_points_local,
            np.asarray(anchor["min_m"], dtype=np.float64),
            np.asarray(anchor["max_m"], dtype=np.float64),
        )
        selected = source_points_local[inside]
        if not len(selected):
            raise ValueError(
                f"source samples do not cover semantic anchor {anchor.get('id')!r}"
            )
        return selected
    raise ValueError(f"unsupported source anchor shape: {shape!r}")


@dataclass(frozen=True)
class GeometryEvaluation:
    accepted: bool
    certificate: dict[str, Any]


def evaluate_relation_geometry(
    contract: dict[str, Any],
    *,
    source_points_local: np.ndarray,
    target_points_local: np.ndarray,
    source_pose: dict[str, Any] | np.ndarray | None = None,
    target_pose: dict[str, Any] | np.ndarray | None = None,
    source_proxy: DistanceProxy | None = None,
    target_proxy: DistanceProxy | None = None,
    proxy_hashes: dict[str, str] | None = None,
    capability_hashes: dict[str, str] | None = None,
    predicate_points_local: np.ndarray | None = None,
    predicate_point_basis: str = "surface_samples",
    ambiguous_refinement_threshold: float = 0.02,
) -> GeometryEvaluation:
    """Evaluate relation semantics and bilateral non-penetration."""

    source_matrix = pose_matrix(source_pose)
    target_matrix = pose_matrix(target_pose)
    source_points_local = np.asarray(source_points_local, dtype=np.float64)
    target_points_local = np.asarray(target_points_local, dtype=np.float64)
    source_world = transform_points(source_points_local, source_matrix)
    target_world = transform_points(target_points_local, target_matrix)
    predicate_input = (
        source_points_local
        if predicate_points_local is None
        else np.asarray(predicate_points_local, dtype=np.float64)
    )
    relation_source_local = _anchor_relation_points(contract, predicate_input)
    relation_source_world = transform_points(relation_source_local, source_matrix)
    source_in_target = transform_points(
        relation_source_world, np.linalg.inv(target_matrix)
    )

    predicate = _relation_predicate(contract, source_in_target)
    tolerance = float(contract["tolerance_m"])
    source_to_target = _collision_direction(
        source_world,
        target_matrix,
        target_proxy,
        tolerance,
        ambiguous_refinement_threshold=ambiguous_refinement_threshold,
    )
    target_to_source = _collision_direction(
        target_world,
        source_matrix,
        source_proxy,
        tolerance,
        ambiguous_refinement_threshold=ambiguous_refinement_threshold,
    )
    collision_complete = bool(
        source_to_target["complete"] and target_to_source["complete"]
    )
    no_deep_collision = bool(
        collision_complete
        and source_to_target["deep_count"] == 0
        and target_to_source["deep_count"] == 0
    )
    conservative = contract.get("verification_policy") == "conservative_bilateral"
    collision_ok = (
        no_deep_collision
        if conservative
        else bool(
            (not source_to_target["complete"] or source_to_target["deep_count"] == 0)
            and (
                not target_to_source["complete"] or target_to_source["deep_count"] == 0
            )
        )
    )
    inputs = {
        "contract_hash": contract["contract_hash"],
        "source_pose": source_matrix.round(12).tolist(),
        "target_pose": target_matrix.round(12).tolist(),
        "proxy_hashes": dict(proxy_hashes or {}),
        "capability_hashes": dict(
            capability_hashes
            or {
                "source": str(contract.get("source_capability_hash") or ""),
                "target": str(contract.get("target_capability_hash") or ""),
            }
        ),
        "predicate_point_basis": predicate_point_basis,
        "predicate_point_count": int(len(relation_source_local)),
    }
    proxy_error_bound = max(
        float(source_to_target.get("proxy_uncertainty_m") or 0.0),
        float(target_to_source.get("proxy_uncertainty_m") or 0.0),
    )
    certificate = {
        "schema": GEOMETRY_CERTIFICATE_SCHEMA,
        "accepted": bool(predicate["ok"] and collision_ok),
        "relation": {
            "type": contract["relation_type"],
            "source_asset_id": contract["source_asset_id"],
            "target_asset_id": contract["target_asset_id"],
            "target_slot_id": contract["target_slot_id"],
        },
        "predicate": {
            **predicate,
            "point_basis": predicate_point_basis,
            "point_count": int(len(relation_source_local)),
        },
        "collision": {
            "complete": collision_complete,
            "policy": contract["verification_policy"],
            "source_to_target": source_to_target,
            "target_to_source": target_to_source,
        },
        "inputs": inputs,
        "inputs_hash": content_hash(inputs),
        "quantified_error_bounds": {
            "proxy_discretization_m": proxy_error_bound,
            "relation_tolerance_m": tolerance,
            "predicate_numeric_m": float(
                predicate.get("classification_numeric_error_bound_m") or 0.0
            ),
        },
    }
    certificate["certificate_hash"] = content_hash(certificate)
    return GeometryEvaluation(bool(certificate["accepted"]), certificate)


def certificate_is_fresh(
    certificate: dict[str, Any],
    *,
    contract: dict[str, Any],
    source_pose: dict[str, Any] | np.ndarray | None,
    target_pose: dict[str, Any] | np.ndarray | None,
    proxy_hashes: dict[str, str] | None = None,
    capability_hashes: dict[str, str] | None = None,
    predicate_point_basis: str = "surface_samples",
    predicate_point_count: int | None = None,
) -> bool:
    existing_inputs = certificate.get("inputs", {})
    inputs = {
        "contract_hash": contract["contract_hash"],
        "source_pose": pose_matrix(source_pose).round(12).tolist(),
        "target_pose": pose_matrix(target_pose).round(12).tolist(),
        "proxy_hashes": dict(proxy_hashes or {}),
        "capability_hashes": dict(
            capability_hashes
            or {
                "source": str(contract.get("source_capability_hash") or ""),
                "target": str(contract.get("target_capability_hash") or ""),
            }
        ),
        "predicate_point_basis": predicate_point_basis,
        "predicate_point_count": int(
            predicate_point_count
            if predicate_point_count is not None
            else existing_inputs.get("predicate_point_count", 0)
        ),
    }
    return bool(certificate.get("inputs_hash") == content_hash(inputs))
