from __future__ import annotations

import math
from typing import Any

import numpy as np
import trimesh
from scipy import ndimage

from .collision_proxy import VoxelSDF


CAPABILITY_PROPOSAL_SCHEMA = "codex_trellis_geometry_capability_proposal_v1"


def _review_record(kind: str, confidence: float) -> dict[str, Any]:
    return {
        "proposal_kind": kind,
        "confidence": float(min(max(confidence, 0.0), 1.0)),
        "review_required": True,
        "approved": False,
        "provenance": "automatic_geometry_proposal_v1",
    }


def propose_support_surfaces(
    mesh: trimesh.Trimesh,
    *,
    height_bin_m: float,
    minimum_area_fraction: float = 0.01,
    maximum_proposals: int = 8,
) -> list[dict[str, Any]]:
    triangles = np.asarray(mesh.triangles, dtype=np.float64)
    normals = np.asarray(mesh.face_normals, dtype=np.float64)
    areas = np.asarray(mesh.area_faces, dtype=np.float64)
    upward = normals[:, 2] >= math.cos(math.radians(12.0))
    if not np.any(upward):
        return []
    centers = np.mean(triangles, axis=1)
    total_footprint = max(float(mesh.extents[0] * mesh.extents[1]), 1e-12)
    groups: dict[int, list[int]] = {}
    for face_index in np.nonzero(upward)[0]:
        key = int(round(float(centers[face_index, 2]) / height_bin_m))
        groups.setdefault(key, []).append(int(face_index))
    proposals: list[dict[str, Any]] = []
    for indices in groups.values():
        area = float(np.sum(areas[indices]))
        if area < total_footprint * minimum_area_fraction:
            continue
        vertices = triangles[indices].reshape(-1, 3)
        minimum = np.min(vertices, axis=0)
        maximum = np.max(vertices, axis=0)
        center = (minimum + maximum) / 2.0
        half = (maximum - minimum)[:2] / 2.0
        if np.any(half <= height_bin_m / 2.0):
            continue
        proposals.append(
            {
                "shape": "planar_rectangle",
                "center_m": [float(center[0]), float(center[1]), float(np.mean(vertices[:, 2]))],
                "normal": [0.0, 0.0, 1.0],
                "u_axis": [1.0, 0.0, 0.0],
                "v_axis": [0.0, 1.0, 0.0],
                "half_extents_m": half.tolist(),
                "area_evidence_m2": area,
                **_review_record("support_surface", min(1.0, area / total_footprint)),
            }
        )
    proposals.sort(key=lambda item: (-item["center_m"][2], -item["area_evidence_m2"]))
    for index, proposal in enumerate(proposals[:maximum_proposals], 1):
        proposal["id"] = f"auto_support_{index}"
    return proposals[:maximum_proposals]


def propose_contact_surfaces(
    mesh: trimesh.Trimesh,
    *,
    plane_bin_m: float,
    minimum_area_fraction: float = 0.02,
    maximum_proposals: int = 12,
) -> list[dict[str, Any]]:
    triangles = np.asarray(mesh.triangles, dtype=np.float64)
    normals = np.asarray(mesh.face_normals, dtype=np.float64)
    areas = np.asarray(mesh.area_faces, dtype=np.float64)
    directions = [
        np.asarray(value, dtype=np.float64)
        for value in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0))
    ]
    diagonal_area = max(
        float(mesh.extents[2] * max(mesh.extents[0], mesh.extents[1])), 1e-12
    )
    groups: dict[tuple[int, int], list[int]] = {}
    for face_index, normal in enumerate(normals):
        dots = [float(np.dot(normal, direction)) for direction in directions]
        direction_index = int(np.argmax(dots))
        if dots[direction_index] < math.cos(math.radians(12.0)):
            continue
        direction = directions[direction_index]
        plane = float(np.dot(np.mean(triangles[face_index], axis=0), direction))
        key = (direction_index, int(round(plane / plane_bin_m)))
        groups.setdefault(key, []).append(face_index)
    proposals: list[dict[str, Any]] = []
    for (direction_index, _), indices in groups.items():
        area = float(np.sum(areas[indices]))
        if area < diagonal_area * minimum_area_fraction:
            continue
        normal = directions[direction_index]
        if abs(normal[0]) > 0.5:
            u_axis = np.asarray([0.0, 1.0, 0.0])
        else:
            u_axis = np.asarray([1.0, 0.0, 0.0])
        v_axis = np.asarray([0.0, 0.0, 1.0])
        vertices = triangles[indices].reshape(-1, 3)
        u_values = vertices @ u_axis
        v_values = vertices @ v_axis
        plane_values = vertices @ normal
        u_center = float((np.min(u_values) + np.max(u_values)) / 2.0)
        v_center = float((np.min(v_values) + np.max(v_values)) / 2.0)
        plane_center = float(np.mean(plane_values))
        center = plane_center * normal + u_center * u_axis + v_center * v_axis
        proposals.append(
            {
                "shape": "planar_rectangle",
                "center_m": center.tolist(),
                "normal": normal.tolist(),
                "u_axis": u_axis.tolist(),
                "v_axis": v_axis.tolist(),
                "half_extents_m": [
                    float((np.max(u_values) - np.min(u_values)) / 2.0),
                    float((np.max(v_values) - np.min(v_values)) / 2.0),
                ],
                "area_evidence_m2": area,
                **_review_record("contact_surface", min(1.0, area / diagonal_area)),
            }
        )
    proposals.sort(key=lambda item: -item["area_evidence_m2"])
    for index, proposal in enumerate(proposals[:maximum_proposals], 1):
        proposal["id"] = f"auto_contact_{index}"
    return proposals[:maximum_proposals]


def _grow_free_box(free: np.ndarray, seed: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    lower = seed.astype(int).copy()
    upper = seed.astype(int).copy()
    while True:
        options: list[tuple[int, int, int]] = []
        for axis in range(3):
            if lower[axis] > 0:
                candidate_lower = lower.copy()
                candidate_lower[axis] -= 1
                slices = tuple(
                    slice(candidate_lower[i], upper[i] + 1) for i in range(3)
                )
                if bool(np.all(free[slices])):
                    volume = int(np.prod(upper - candidate_lower + 1))
                    options.append((volume, axis, -1))
            if upper[axis] + 1 < free.shape[axis]:
                candidate_upper = upper.copy()
                candidate_upper[axis] += 1
                slices = tuple(
                    slice(lower[i], candidate_upper[i] + 1) for i in range(3)
                )
                if bool(np.all(free[slices])):
                    volume = int(np.prod(candidate_upper - lower + 1))
                    options.append((volume, axis, 1))
        if not options:
            return lower, upper
        _, axis, direction = max(options)
        if direction < 0:
            lower[axis] -= 1
        else:
            upper[axis] += 1


def _box_iou(first: tuple[np.ndarray, np.ndarray], second: tuple[np.ndarray, np.ndarray]) -> float:
    lower = np.maximum(first[0], second[0])
    upper = np.minimum(first[1], second[1])
    intersection = float(np.prod(np.maximum(upper - lower + 1, 0)))
    first_volume = float(np.prod(first[1] - first[0] + 1))
    second_volume = float(np.prod(second[1] - second[0] + 1))
    return intersection / max(first_volume + second_volume - intersection, 1.0)


def propose_free_space_volumes(
    mesh: trimesh.Trimesh,
    proxy: VoxelSDF,
    *,
    minimum_volume_fraction: float = 0.01,
    maximum_proposals: int = 6,
) -> list[dict[str, Any]]:
    bounds = np.asarray(mesh.bounds, dtype=np.float64)
    crop_lower = np.ceil((bounds[0] - proxy.origin) / proxy.pitch).astype(int)
    crop_upper = np.floor((bounds[1] - proxy.origin) / proxy.pitch).astype(int)
    crop_lower = np.maximum(crop_lower, 0)
    crop_upper = np.minimum(crop_upper, np.asarray(proxy.occupancy.shape) - 1)
    if np.any(crop_lower > crop_upper):
        return []
    slices = tuple(slice(crop_lower[axis], crop_upper[axis] + 1) for axis in range(3))
    free = ~np.asarray(proxy.occupancy[slices], dtype=bool)
    distance = ndimage.distance_transform_edt(free)
    local_maximum = distance == ndimage.maximum_filter(distance, size=5, mode="constant")
    seeds = np.argwhere(local_maximum & free)
    if not len(seeds):
        return []
    seed_scores = distance[tuple(seeds.T)]
    order = np.argsort(seed_scores)[::-1][:64]
    asset_volume = max(float(np.prod(np.asarray(mesh.extents))), 1e-12)
    boxes: list[tuple[np.ndarray, np.ndarray]] = []
    for seed in seeds[order]:
        box = _grow_free_box(free, seed)
        volume = float(np.prod(box[1] - box[0] + 1) * proxy.pitch**3)
        if volume < asset_volume * minimum_volume_fraction:
            continue
        if any(_box_iou(box, previous) > 0.65 for previous in boxes):
            continue
        boxes.append(box)
        if len(boxes) >= maximum_proposals:
            break

    proposals: list[dict[str, Any]] = []
    crop_shape = np.asarray(free.shape)
    for index, (lower, upper) in enumerate(boxes, 1):
        global_lower = crop_lower + lower
        global_upper = crop_lower + upper
        minimum = proxy.origin + (global_lower - 0.5) * proxy.pitch
        maximum = proxy.origin + (global_upper + 0.5) * proxy.pitch
        minimum = np.maximum(minimum, bounds[0])
        maximum = np.minimum(maximum, bounds[1])
        entry_axes: list[list[float]] = []
        for axis in range(3):
            if lower[axis] == 0:
                vector = [0.0, 0.0, 0.0]
                vector[axis] = -1.0
                entry_axes.append(vector)
            if upper[axis] == crop_shape[axis] - 1:
                vector = [0.0, 0.0, 0.0]
                vector[axis] = 1.0
                entry_axes.append(vector)
        volume = float(np.prod(maximum - minimum))
        proposals.append(
            {
                "id": f"auto_free_space_{index}",
                "shape": "box",
                "min_m": minimum.tolist(),
                "max_m": maximum.tolist(),
                "entry_axis_candidates": entry_axes,
                "volume_m3": volume,
                **_review_record(
                    "free_space_volume",
                    min(0.9, 0.35 + volume / asset_volume),
                ),
            }
        )
    return proposals


def propose_semantic_anchors(mesh: trimesh.Trimesh) -> list[dict[str, Any]]:
    minimum, maximum = np.asarray(mesh.bounds, dtype=np.float64)
    center = (minimum + maximum) / 2.0
    anchors = [
        ("bottom_center", [center[0], center[1], minimum[2]]),
        ("top_center", [center[0], center[1], maximum[2]]),
        ("negative_y_center", [center[0], minimum[1], center[2]]),
        ("positive_y_center", [center[0], maximum[1], center[2]]),
    ]
    return [
        {
            "id": name,
            "shape": "point",
            "point_m": [float(value) for value in point],
            **_review_record("semantic_anchor", 0.5),
        }
        for name, point in anchors
    ]


def propose_geometry_capabilities(
    mesh: trimesh.Trimesh,
    proxy: VoxelSDF,
    *,
    asset_id: str,
) -> dict[str, Any]:
    pitch = float(proxy.pitch)
    return {
        "schema": CAPABILITY_PROPOSAL_SCHEMA,
        "asset_id": asset_id,
        "review_required": True,
        "automatic_approval_forbidden": True,
        "mesh_hash": proxy.metadata.get("mesh_hash"),
        "proxy_error_m": proxy.metadata.get("max_discretization_error_m"),
        "support_surfaces": propose_support_surfaces(mesh, height_bin_m=max(pitch, 0.005)),
        "contact_surfaces": propose_contact_surfaces(mesh, plane_bin_m=max(pitch, 0.005)),
        "free_space_volumes": propose_free_space_volumes(mesh, proxy),
        "semantic_anchors": propose_semantic_anchors(mesh),
    }
