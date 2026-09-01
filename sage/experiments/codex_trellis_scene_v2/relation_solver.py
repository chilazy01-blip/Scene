from __future__ import annotations

import math
from typing import Any, Iterable

import numpy as np
import trimesh

from .mesh_verifier import (
    intersection_tolerance,
    prepare_triangle_mesh,
    verify_mesh_intersection,
)
from .relation_geometry import (
    DistanceProxy,
    GeometryEvaluation,
    evaluate_relation_geometry,
    pose_matrix,
    transform_points,
)


RELATION_SOLVER_SCHEMA = "codex_trellis_relation_geometry_solver_v1"


def _axis_values(
    lower: float, upper: float, preferred: float, step: float
) -> list[float]:
    if lower > upper + 1e-12:
        return []
    preferred = min(max(preferred, lower), upper)
    if upper - lower <= step:
        return sorted({float(lower), float(preferred), float(upper)})
    values = list(np.arange(lower, upper + step * 0.5, step, dtype=np.float64))
    values.extend((lower, preferred, upper, (lower + upper) / 2.0))
    return sorted(
        {
            round(float(value), 9)
            for value in values
            if lower - 1e-9 <= value <= upper + 1e-9
        }
    )


def _yaw_values(slot: dict[str, Any], preferred: float) -> list[float]:
    entry_pose = slot.get("entry_pose")
    if not isinstance(entry_pose, dict):
        return [float(preferred)]
    center = float(entry_pose.get("yaw_degrees", preferred))
    tolerance = float(entry_pose.get("yaw_tolerance_degrees", 0.0))
    if tolerance <= 0.0:
        return [center]
    return [center - tolerance, center, center + tolerance]


def _rotated_bounds(points: np.ndarray, yaw: float) -> tuple[np.ndarray, np.ndarray]:
    rotated = transform_points(points, pose_matrix({"yaw_degrees": yaw}))
    return np.min(rotated, axis=0), np.max(rotated, axis=0)


def generate_relation_candidates(
    contract: dict[str, Any],
    source_points_local: np.ndarray,
    *,
    preferred_target_local_pose: dict[str, Any] | None = None,
    translation_step_m: float = 0.05,
    maximum_candidates: int = 10_000,
) -> list[dict[str, float]]:
    """Generate candidates from slot geometry, never from asset categories."""

    if translation_step_m <= 0.0:
        raise ValueError("translation_step_m must be positive")
    preferred = dict(preferred_target_local_pose or {})
    preferred_xyz = np.array(
        [
            float(preferred.get("x", 0.0)),
            float(preferred.get("y", 0.0)),
            float(preferred.get("z", 0.0)),
        ]
    )
    preferred_yaw = float(preferred.get("yaw_degrees", preferred.get("yaw", 0.0)))
    points = np.asarray(source_points_local, dtype=np.float64)
    slot = contract["target_slot"]
    evaluator = contract["evaluator"]
    candidates: list[dict[str, float]] = []

    for yaw in _yaw_values(slot, preferred_yaw):
        bounds_min, bounds_max = _rotated_bounds(points, yaw)
        translations: Iterable[tuple[float, float, float]]
        if evaluator == "full_containment":
            minimum = np.asarray(slot["min_m"], dtype=np.float64)
            maximum = np.asarray(slot["max_m"], dtype=np.float64)
            clearance = float(slot.get("clearance_m", 0.0))
            lower = minimum + clearance - bounds_min
            upper = maximum - clearance - bounds_max
            axes = [
                _axis_values(
                    lower[index], upper[index], preferred_xyz[index], translation_step_m
                )
                for index in range(3)
            ]
            translations = (
                (x, y, z) for x in axes[0] for y in axes[1] for z in axes[2]
            )
        elif evaluator == "partial_entry":
            entry_pose = slot.get("entry_pose")
            if isinstance(entry_pose, dict) and isinstance(
                entry_pose.get("translation_bounds_m"), dict
            ):
                raw = entry_pose["translation_bounds_m"]
                axes = [
                    _axis_values(
                        float(raw[axis][0]),
                        float(raw[axis][1]),
                        preferred_xyz[index],
                        translation_step_m,
                    )
                    for index, axis in enumerate(("x", "y", "z"))
                ]
            else:
                minimum = np.asarray(slot["min_m"], dtype=np.float64) - bounds_max
                maximum = np.asarray(slot["max_m"], dtype=np.float64) - bounds_min
                axes = [
                    _axis_values(
                        minimum[index],
                        maximum[index],
                        preferred_xyz[index],
                        translation_step_m,
                    )
                    for index in range(3)
                ]
            translations = (
                (x, y, z) for x in axes[0] for y in axes[1] for z in axes[2]
            )
        elif evaluator == "bounded_plane_support":
            normal = np.asarray(slot["normal"], dtype=np.float64)
            if abs(float(np.dot(normal, [0.0, 0.0, 1.0]))) < 0.999:
                raise ValueError("yaw-only solver supports horizontal support surfaces")
            center = np.asarray(slot["center_m"], dtype=np.float64)
            half = np.asarray(slot["half_extents_m"], dtype=np.float64)
            lower_x = center[0] - half[0] - bounds_min[0]
            upper_x = center[0] + half[0] - bounds_max[0]
            lower_y = center[1] - half[1] - bounds_min[1]
            upper_y = center[1] + half[1] - bounds_max[1]
            z = center[2] - bounds_min[2]
            xs = _axis_values(lower_x, upper_x, preferred_xyz[0], translation_step_m)
            ys = _axis_values(lower_y, upper_y, preferred_xyz[1], translation_step_m)
            translations = ((x, y, z) for x in xs for y in ys)
        elif evaluator == "bounded_plane_contact":
            center = np.asarray(slot["center_m"], dtype=np.float64)
            normal = np.asarray(slot["normal"], dtype=np.float64)
            normal /= max(np.linalg.norm(normal), 1e-12)
            u_axis = np.asarray(slot["u_axis"], dtype=np.float64)
            v_axis = np.asarray(slot["v_axis"], dtype=np.float64)
            half = np.asarray(slot["half_extents_m"], dtype=np.float64)
            rotated = transform_points(points, pose_matrix({"yaw_degrees": yaw}))
            minimum_normal = float(np.min(rotated @ normal))
            preferred_u = float((preferred_xyz - center) @ u_axis)
            preferred_v = float((preferred_xyz - center) @ v_axis)
            us = _axis_values(-half[0], half[0], preferred_u, translation_step_m)
            vs = _axis_values(-half[1], half[1], preferred_v, translation_step_m)
            translations = (
                tuple(center + u * u_axis + v * v_axis - minimum_normal * normal)
                for u in us
                for v in vs
            )
        else:
            raise ValueError(f"unsupported relation evaluator: {evaluator}")

        for x, y, z in translations:
            candidates.append(
                {
                    "x": float(x),
                    "y": float(y),
                    "z": float(z),
                    "yaw_degrees": float(yaw),
                }
            )
            if len(candidates) >= maximum_candidates:
                return candidates
    return candidates


def optimize_relation_pose(
    contract: dict[str, Any],
    *,
    source_points_local: np.ndarray,
    target_points_local: np.ndarray,
    source_proxy: DistanceProxy,
    target_proxy: DistanceProxy,
    target_world_pose: dict[str, Any] | np.ndarray | None = None,
    preferred_target_local_pose: dict[str, Any] | None = None,
    translation_step_m: float = 0.05,
    maximum_candidates: int = 10_000,
    source_mesh: trimesh.Trimesh | None = None,
    target_mesh: trimesh.Trimesh | None = None,
    triangle_verification: str = "off",
    maximum_triangle_checks: int = 32,
) -> dict[str, Any]:
    if triangle_verification not in {"off", "collision_relations"}:
        raise ValueError("triangle_verification must be off or collision_relations")
    if triangle_verification != "off" and (source_mesh is None or target_mesh is None):
        raise ValueError("triangle verification requires source_mesh and target_mesh")
    candidates = generate_relation_candidates(
        contract,
        source_points_local,
        preferred_target_local_pose=preferred_target_local_pose,
        translation_step_m=translation_step_m,
        maximum_candidates=maximum_candidates,
    )
    target_matrix = pose_matrix(target_world_pose)
    preferred = dict(preferred_target_local_pose or {})
    preferred_vector = np.asarray(
        [
            float(preferred.get("x", 0.0)),
            float(preferred.get("y", 0.0)),
            float(preferred.get("z", 0.0)),
        ],
        dtype=np.float64,
    )
    accepted: list[tuple[float, dict[str, float], GeometryEvaluation]] = []
    rejection_counts = {"relation_predicate": 0, "collision": 0}
    for candidate in candidates:
        source_world_matrix = target_matrix @ pose_matrix(candidate)
        evaluation = evaluate_relation_geometry(
            contract,
            source_points_local=source_points_local,
            target_points_local=target_points_local,
            source_pose=source_world_matrix,
            target_pose=target_matrix,
            source_proxy=source_proxy,
            target_proxy=target_proxy,
            predicate_points_local=(
                np.asarray(source_mesh.vertices, dtype=np.float64)
                if contract["evaluator"] == "full_containment"
                and source_mesh is not None
                else None
            ),
            predicate_point_basis=(
                "all_mesh_vertices_convex_slot"
                if contract["evaluator"] == "full_containment"
                and source_mesh is not None
                else "surface_samples"
            ),
        )
        if evaluation.accepted:
            vector = np.asarray([candidate[axis] for axis in ("x", "y", "z")])
            yaw_delta = math.radians(
                candidate["yaw_degrees"]
                - float(preferred.get("yaw_degrees", preferred.get("yaw", 0.0)))
            )
            score = float(
                np.linalg.norm(vector - preferred_vector) + 0.05 * abs(yaw_delta)
            )
            accepted.append((score, candidate, evaluation))
        else:
            if not evaluation.certificate["predicate"]["ok"]:
                rejection_counts["relation_predicate"] += 1
            if not evaluation.certificate["collision"]["complete"] or any(
                int(
                    evaluation.certificate["collision"][direction].get("deep_count")
                    or 0
                )
                for direction in ("source_to_target", "target_to_source")
            ):
                rejection_counts["collision"] += 1
    if not accepted:
        raise RuntimeError(
            f"no valid {contract['relation_type']} pose among {len(candidates)} candidates"
        )
    accepted.sort(key=lambda item: item[0])
    triangle_reports: list[dict[str, Any]] = []
    selected = accepted[0]
    needs_disjoint_surfaces = contract["evaluator"] in {
        "full_containment",
        "partial_entry",
    }
    if triangle_verification == "collision_relations" and needs_disjoint_surfaces:
        pair_tolerance = intersection_tolerance(source_mesh, target_mesh)
        prepared_target = prepare_triangle_mesh(
            target_mesh,
            transform=target_matrix,
            tolerance=pair_tolerance,
        )
        selected = None
        for score, pose, evaluation in accepted[:maximum_triangle_checks]:
            source_world_matrix = target_matrix @ pose_matrix(pose)
            triangle_report = verify_mesh_intersection(
                source_mesh,
                target_mesh,
                first_transform=source_world_matrix,
                second_transform=target_matrix,
                prepared_second=prepared_target,
            )
            triangle_reports.append(
                {
                    "target_local_pose": pose,
                    "complete": triangle_report["complete"],
                    "intersects": triangle_report["intersects"],
                    "report": triangle_report,
                }
            )
            if triangle_report["complete"] and not triangle_report["intersects"]:
                selected = (score, pose, evaluation)
                break
        if selected is None:
            raise RuntimeError(
                "no triangle-verified collision-free pose within the verification budget"
            )
    score, pose, evaluation = selected
    return {
        "schema": RELATION_SOLVER_SCHEMA,
        "relation_type": contract["relation_type"],
        "candidate_count": len(candidates),
        "accepted_candidate_count": len(accepted),
        "rejection_counts": rejection_counts,
        "selected_target_local_pose": pose,
        "selected_score": score,
        "certificate": evaluation.certificate,
        "triangle_verification": {
            "policy": triangle_verification,
            "checked_candidate_count": len(triangle_reports),
            "candidates": triangle_reports,
        },
    }
