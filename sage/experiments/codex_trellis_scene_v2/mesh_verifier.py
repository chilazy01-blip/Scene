from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import trimesh
from scipy.spatial import cKDTree

from .relation_geometry import pose_matrix, transform_points


MESH_VERIFICATION_SCHEMA = "codex_trellis_mesh_intersection_verification_v1"


@dataclass(frozen=True)
class TriangleSoup:
    triangles: np.ndarray
    source_face_indices: np.ndarray
    removed_degenerate_count: int


@dataclass(frozen=True)
class PreparedTriangleMesh:
    soup: TriangleSoup
    minimum: np.ndarray
    maximum: np.ndarray
    centers: np.ndarray
    radii: np.ndarray
    tree: cKDTree | None
    maximum_radius: float
    tolerance: float


def _prepare_triangles(
    mesh: trimesh.Trimesh,
    transform: dict[str, Any] | np.ndarray | None,
    tolerance: float,
) -> TriangleSoup:
    vertices = transform_points(np.asarray(mesh.vertices), pose_matrix(transform))
    triangles = vertices[np.asarray(mesh.faces, dtype=np.int64)]
    cross = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    keep = np.linalg.norm(cross, axis=1) > tolerance * tolerance
    indices = np.nonzero(keep)[0].astype(np.int64)
    return TriangleSoup(
        triangles=np.asarray(triangles[keep], dtype=np.float64),
        source_face_indices=indices,
        removed_degenerate_count=int(np.count_nonzero(~keep)),
    )


def intersection_tolerance(
    first_mesh: trimesh.Trimesh,
    second_mesh: trimesh.Trimesh,
    *,
    relative_tolerance: float = 1e-9,
) -> float:
    bounds = np.vstack((np.asarray(first_mesh.bounds), np.asarray(second_mesh.bounds)))
    scale = max(float(np.linalg.norm(np.ptp(bounds, axis=0))), 1.0)
    return max(
        scale * float(relative_tolerance),
        np.finfo(np.float64).eps * scale * 32,
    )


def prepare_triangle_mesh(
    mesh: trimesh.Trimesh,
    *,
    transform: dict[str, Any] | np.ndarray | None = None,
    tolerance: float,
) -> PreparedTriangleMesh:
    if tolerance <= 0.0:
        raise ValueError("tolerance must be positive")
    soup = _prepare_triangles(mesh, transform, tolerance)
    if not len(soup.triangles):
        return PreparedTriangleMesh(
            soup=soup,
            minimum=np.empty((0, 3), dtype=np.float64),
            maximum=np.empty((0, 3), dtype=np.float64),
            centers=np.empty((0, 3), dtype=np.float64),
            radii=np.empty((0,), dtype=np.float64),
            tree=None,
            maximum_radius=0.0,
            tolerance=float(tolerance),
        )
    minimum = np.min(soup.triangles, axis=1)
    maximum = np.max(soup.triangles, axis=1)
    centers = np.mean(soup.triangles, axis=1)
    radii = np.max(
        np.linalg.norm(soup.triangles - centers[:, None, :], axis=2), axis=1
    )
    return PreparedTriangleMesh(
        soup=soup,
        minimum=minimum,
        maximum=maximum,
        centers=centers,
        radii=radii,
        tree=cKDTree(centers),
        maximum_radius=float(np.max(radii)),
        tolerance=float(tolerance),
    )


def _orient2d(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    return float((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))


def _point_in_triangle_2d(point: np.ndarray, triangle: np.ndarray, tolerance: float) -> bool:
    values = [
        _orient2d(triangle[0], triangle[1], point),
        _orient2d(triangle[1], triangle[2], point),
        _orient2d(triangle[2], triangle[0], point),
    ]
    return bool(
        (all(value >= -tolerance for value in values))
        or (all(value <= tolerance for value in values))
    )


def _segments_intersect_2d(
    a: np.ndarray,
    b: np.ndarray,
    c: np.ndarray,
    d: np.ndarray,
    tolerance: float,
) -> bool:
    o1, o2 = _orient2d(a, b, c), _orient2d(a, b, d)
    o3, o4 = _orient2d(c, d, a), _orient2d(c, d, b)
    return bool(
        min(o1, o2) <= tolerance
        and max(o1, o2) >= -tolerance
        and min(o3, o4) <= tolerance
        and max(o3, o4) >= -tolerance
        and max(min(a[0], b[0]), min(c[0], d[0]))
        <= min(max(a[0], b[0]), max(c[0], d[0])) + tolerance
        and max(min(a[1], b[1]), min(c[1], d[1]))
        <= min(max(a[1], b[1]), max(c[1], d[1])) + tolerance
    )


def _coplanar_triangles_intersect(
    first: np.ndarray,
    second: np.ndarray,
    normal: np.ndarray,
    tolerance: float,
) -> bool:
    drop_axis = int(np.argmax(np.abs(normal)))
    axes = [axis for axis in range(3) if axis != drop_axis]
    first_2d = first[:, axes]
    second_2d = second[:, axes]
    for edge_a in range(3):
        for edge_b in range(3):
            if _segments_intersect_2d(
                first_2d[edge_a],
                first_2d[(edge_a + 1) % 3],
                second_2d[edge_b],
                second_2d[(edge_b + 1) % 3],
                tolerance,
            ):
                return True
    return _point_in_triangle_2d(first_2d[0], second_2d, tolerance) or _point_in_triangle_2d(
        second_2d[0], first_2d, tolerance
    )


def _segment_triangle_intersection(
    start: np.ndarray,
    end: np.ndarray,
    triangle: np.ndarray,
    tolerance: float,
) -> bool:
    direction = end - start
    edge1 = triangle[1] - triangle[0]
    edge2 = triangle[2] - triangle[0]
    pvec = np.cross(direction, edge2)
    determinant = float(np.dot(edge1, pvec))
    if abs(determinant) <= tolerance:
        return False
    inverse = 1.0 / determinant
    tvec = start - triangle[0]
    u = float(np.dot(tvec, pvec) * inverse)
    if u < -tolerance or u > 1.0 + tolerance:
        return False
    qvec = np.cross(tvec, edge1)
    v = float(np.dot(direction, qvec) * inverse)
    if v < -tolerance or u + v > 1.0 + tolerance:
        return False
    distance = float(np.dot(edge2, qvec) * inverse)
    return bool(-tolerance <= distance <= 1.0 + tolerance)


def triangles_intersect(
    first: np.ndarray,
    second: np.ndarray,
    *,
    tolerance: float,
) -> bool:
    normal_first = np.cross(first[1] - first[0], first[2] - first[0])
    normal_second = np.cross(second[1] - second[0], second[2] - second[0])
    norm_first = np.linalg.norm(normal_first)
    norm_second = np.linalg.norm(normal_second)
    if norm_first <= tolerance * tolerance or norm_second <= tolerance * tolerance:
        return False
    unit_first = normal_first / norm_first
    unit_second = normal_second / norm_second
    parallel = np.linalg.norm(np.cross(unit_first, unit_second)) <= tolerance
    plane_distances = (second - first[0]) @ unit_first
    if parallel and np.max(np.abs(plane_distances)) <= tolerance:
        return _coplanar_triangles_intersect(first, second, unit_first, tolerance)
    if np.all(plane_distances > tolerance) or np.all(plane_distances < -tolerance):
        return False
    reverse_distances = (first - second[0]) @ unit_second
    if np.all(reverse_distances > tolerance) or np.all(reverse_distances < -tolerance):
        return False
    for edge in range(3):
        if _segment_triangle_intersection(
            first[edge], first[(edge + 1) % 3], second, tolerance
        ):
            return True
        if _segment_triangle_intersection(
            second[edge], second[(edge + 1) % 3], first, tolerance
        ):
            return True
    return False


def verify_mesh_intersection(
    first_mesh: trimesh.Trimesh,
    second_mesh: trimesh.Trimesh,
    *,
    first_transform: dict[str, Any] | np.ndarray | None = None,
    second_transform: dict[str, Any] | np.ndarray | None = None,
    relative_tolerance: float = 1e-9,
    maximum_candidate_pairs: int = 250_000,
    prepared_second: PreparedTriangleMesh | None = None,
) -> dict[str, Any]:
    """Adaptive broad/narrow-phase surface intersection verification.

    This deliberately reports ``exact_predicates=False``.  It is the Python
    fallback behind an interface that can later host an OpenMeshCraft-style
    native exact-predicate backend.
    """

    tolerance = intersection_tolerance(
        first_mesh, second_mesh, relative_tolerance=relative_tolerance
    )
    first = _prepare_triangles(first_mesh, first_transform, tolerance)
    if prepared_second is not None:
        if not math.isclose(
            prepared_second.tolerance,
            tolerance,
            rel_tol=1e-12,
            abs_tol=np.finfo(np.float64).eps,
        ):
            raise ValueError("prepared triangle mesh tolerance does not match pair")
        second = prepared_second.soup
    else:
        second = _prepare_triangles(second_mesh, second_transform, tolerance)
    if not len(first.triangles) or not len(second.triangles):
        return {
            "schema": MESH_VERIFICATION_SCHEMA,
            "backend": "python_adaptive_triangle_v1",
            "exact_predicates": False,
            "complete": True,
            "intersects": False,
            "candidate_pair_count": 0,
            "tested_pair_count": 0,
            "intersection_pair_count": 0,
            "removed_degenerate_faces": [
                first.removed_degenerate_count,
                second.removed_degenerate_count,
            ],
            "tolerance_m": tolerance,
            "second_bvh_cache_used": prepared_second is not None,
        }

    original_removed = [
        first.removed_degenerate_count,
        second.removed_degenerate_count,
    ]
    initial_first_centers = np.mean(first.triangles, axis=1)
    initial_second_centers = np.mean(second.triangles, axis=1)
    initial_first_radii = np.max(
        np.linalg.norm(
            first.triangles - initial_first_centers[:, None, :], axis=2
        ),
        axis=1,
    )
    initial_second_radii = np.max(
        np.linalg.norm(
            second.triangles - initial_second_centers[:, None, :], axis=2
        ),
        axis=1,
    )
    forward_cost = len(first.triangles) * max(float(np.max(initial_second_radii)), tolerance) ** 3
    reverse_cost = len(second.triangles) * max(float(np.max(initial_first_radii)), tolerance) ** 3
    pair_order_swapped = prepared_second is None and reverse_cost < forward_cost
    if pair_order_swapped:
        first, second = second, first

    first_min = np.min(first.triangles, axis=1)
    first_max = np.max(first.triangles, axis=1)
    second_min = (
        prepared_second.minimum
        if prepared_second is not None
        else np.min(second.triangles, axis=1)
    )
    second_max = (
        prepared_second.maximum
        if prepared_second is not None
        else np.max(second.triangles, axis=1)
    )
    first_centers = np.mean(first.triangles, axis=1)
    second_centers = (
        prepared_second.centers
        if prepared_second is not None
        else np.mean(second.triangles, axis=1)
    )
    first_radii = np.max(
        np.linalg.norm(first.triangles - first_centers[:, None, :], axis=2), axis=1
    )
    second_radii = (
        prepared_second.radii
        if prepared_second is not None
        else np.max(
            np.linalg.norm(second.triangles - second_centers[:, None, :], axis=2),
            axis=1,
        )
    )
    second_tree = (
        prepared_second.tree
        if prepared_second is not None
        else cKDTree(second_centers)
    )
    maximum_second_radius = (
        prepared_second.maximum_radius
        if prepared_second is not None
        else float(np.max(second_radii))
    )
    candidate_count = 0
    tested_count = 0
    intersections: list[list[int]] = []
    complete = True
    decision_conclusive = False
    query_chunk_size = 2048
    for query_start in range(0, len(first.triangles), query_chunk_size):
        query_stop = min(query_start + query_chunk_size, len(first.triangles))
        nearby_lists = second_tree.query_ball_point(
            first_centers[query_start:query_stop],
            first_radii[query_start:query_stop]
            + maximum_second_radius
            + tolerance,
            workers=-1,
        )
        for local_first_index, nearby in enumerate(nearby_lists):
            first_index = query_start + local_first_index
            nearby_indices = np.asarray(nearby, dtype=np.int64)
            if not len(nearby_indices):
                continue
            center_delta = second_centers[nearby_indices] - first_centers[first_index]
            individual_radius = (
                first_radii[first_index] + second_radii[nearby_indices] + tolerance
            )
            sphere_keep = np.einsum("ij,ij->i", center_delta, center_delta) <= (
                individual_radius * individual_radius
            )
            nearby_indices = nearby_indices[sphere_keep]
            if not len(nearby_indices):
                continue
            aabb_keep = np.all(
                (first_max[first_index] + tolerance >= second_min[nearby_indices])
                & (second_max[nearby_indices] + tolerance >= first_min[first_index]),
                axis=1,
            )
            candidate_indices = nearby_indices[aabb_keep]
            candidate_count += len(candidate_indices)
            for second_index_value in candidate_indices:
                second_index = int(second_index_value)
                if tested_count >= maximum_candidate_pairs:
                    complete = False
                    break
                tested_count += 1
                if triangles_intersect(
                    first.triangles[first_index],
                    second.triangles[second_index],
                    tolerance=tolerance,
                ):
                    pair = [
                        int(first.source_face_indices[first_index]),
                        int(second.source_face_indices[second_index]),
                    ]
                    intersections.append(pair[::-1] if pair_order_swapped else pair)
                    decision_conclusive = True
                    break
            if decision_conclusive or not complete:
                break
        if decision_conclusive or not complete:
            break
    return {
        "schema": MESH_VERIFICATION_SCHEMA,
        "backend": "python_adaptive_triangle_v1",
        "exact_predicates": False,
        "complete": complete,
        "intersects": bool(intersections),
        "candidate_pair_count": candidate_count,
        "tested_pair_count": tested_count,
        "intersection_pair_count": len(intersections),
        "intersection_pairs_preview": intersections[:20],
        "removed_degenerate_faces": original_removed,
        "broad_phase_pair_order_swapped": pair_order_swapped,
        "tolerance_m": tolerance,
        "second_bvh_cache_used": prepared_second is not None,
        "classification": (
            "surface_intersection"
            if intersections
            else "no_surface_intersection_or_nested_without_crossing"
        ),
    }
