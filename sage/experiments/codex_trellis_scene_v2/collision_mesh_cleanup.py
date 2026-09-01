from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import trimesh


COLLISION_MESH_CLEANUP_SCHEMA = "codex_trellis_collision_mesh_cleanup_v1"


@dataclass(frozen=True)
class CollisionMeshCleanupConfig:
    """Conservative cleanup for a collision-only copy of a visual mesh.

    The cleanup deliberately does not fill holes, voxel-remesh the complete
    asset, or replace the render mesh.  Those operations can seal a desk bay or
    an open shelf.  This pass only repairs topology that is safe to infer from
    the existing surface and removes components that are too small to be useful
    collision geometry.
    """

    weld_tolerance_m: float = 1e-6
    minimum_component_faces: int = 4
    minimum_component_area_fraction: float = 1e-5
    minimum_component_diagonal_fraction: float = 0.004
    maximum_components: int = 512
    minimum_retained_area_fraction: float = 0.995
    maximum_bounds_change_m: float = 0.03

    def validate(self) -> None:
        if self.weld_tolerance_m <= 0.0:
            raise ValueError("weld_tolerance_m must be positive")
        if self.minimum_component_faces < 1:
            raise ValueError("minimum_component_faces must be positive")
        if not 0.0 <= self.minimum_component_area_fraction <= 1.0:
            raise ValueError("minimum_component_area_fraction must be in [0, 1]")
        if not 0.0 <= self.minimum_component_diagonal_fraction <= 1.0:
            raise ValueError("minimum_component_diagonal_fraction must be in [0, 1]")
        if self.maximum_components < 1:
            raise ValueError("maximum_components must be positive")
        if not 0.0 < self.minimum_retained_area_fraction <= 1.0:
            raise ValueError("minimum_retained_area_fraction must be in (0, 1]")
        if self.maximum_bounds_change_m < 0.0:
            raise ValueError("maximum_bounds_change_m must be non-negative")


def _mesh_hash(mesh: trimesh.Trimesh) -> str:
    digest = hashlib.sha256()
    digest.update(np.ascontiguousarray(mesh.vertices, dtype=np.float64).tobytes())
    digest.update(np.ascontiguousarray(mesh.faces, dtype=np.int64).tobytes())
    return digest.hexdigest()


def face_component_labels(
    vertex_count: int, faces: np.ndarray
) -> tuple[np.ndarray, int]:
    """Return a component label per face without materializing split meshes."""

    parent = np.arange(vertex_count, dtype=np.int64)
    rank = np.zeros(vertex_count, dtype=np.uint8)

    def find(value: int) -> int:
        root = value
        while parent[root] != root:
            root = int(parent[root])
        while parent[value] != value:
            next_value = int(parent[value])
            parent[value] = root
            value = next_value
        return root

    def union(first: int, second: int) -> None:
        root_first = find(first)
        root_second = find(second)
        if root_first == root_second:
            return
        if rank[root_first] < rank[root_second]:
            root_first, root_second = root_second, root_first
        parent[root_second] = root_first
        if rank[root_first] == rank[root_second]:
            rank[root_first] += 1

    for first, second, third in np.asarray(faces, dtype=np.int64):
        union(int(first), int(second))
        union(int(second), int(third))

    roots = np.fromiter(
        (find(int(face[0])) for face in faces), dtype=np.int64, count=len(faces)
    )
    _, labels = np.unique(roots, return_inverse=True)
    return labels.astype(np.int64), int(labels.max() + 1 if len(labels) else 0)


def _drop_degenerate_and_duplicate_faces(mesh: trimesh.Trimesh) -> dict[str, int]:
    initial = int(len(mesh.faces))
    if not initial:
        return {"degenerate_faces_removed": 0, "duplicate_faces_removed": 0}

    areas = np.asarray(mesh.area_faces, dtype=np.float64)
    scale = max(float(np.linalg.norm(np.ptp(mesh.bounds, axis=0))), 1.0)
    nondegenerate = np.isfinite(areas) & (areas > np.finfo(np.float64).eps * scale * scale * 64)
    mesh.update_faces(nondegenerate)
    after_degenerate = int(len(mesh.faces))

    canonical_faces = np.sort(np.asarray(mesh.faces, dtype=np.int64), axis=1)
    _, unique_indices = np.unique(canonical_faces, axis=0, return_index=True)
    keep = np.zeros(len(mesh.faces), dtype=bool)
    keep[np.asarray(unique_indices, dtype=np.int64)] = True
    mesh.update_faces(keep)
    mesh.remove_unreferenced_vertices()
    return {
        "degenerate_faces_removed": initial - after_degenerate,
        "duplicate_faces_removed": after_degenerate - int(len(mesh.faces)),
    }


def _weld_vertices(mesh: trimesh.Trimesh, tolerance_m: float) -> int:
    before = int(len(mesh.vertices))
    digits = max(0, int(math.ceil(-math.log10(tolerance_m))))
    mesh.merge_vertices(
        merge_tex=True,
        merge_norm=True,
        digits_vertex=digits,
    )
    mesh.remove_unreferenced_vertices()
    return before - int(len(mesh.vertices))


def cleanup_collision_mesh(
    visual_mesh: trimesh.Trimesh,
    config: CollisionMeshCleanupConfig | None = None,
) -> tuple[trimesh.Trimesh, dict[str, Any]]:
    """Create and audit a non-destructive collision copy.

    If the requested component cap would discard too much surface area or move
    the bounds too far, ``accepted`` is false and callers must retain the raw
    proxy path.  A rejected cleanup is still returned for diagnostics, but it
    is never safe to advertise it as authoritative collision geometry.
    """

    config = config or CollisionMeshCleanupConfig()
    config.validate()
    mesh = visual_mesh.copy()
    if not isinstance(mesh, trimesh.Trimesh) or not len(mesh.faces):
        raise ValueError("collision cleanup requires a non-empty triangle mesh")

    source_hash = _mesh_hash(mesh)
    source_bounds = np.asarray(mesh.bounds, dtype=np.float64)
    source_area = float(mesh.area)
    source_faces = int(len(mesh.faces))
    source_vertices = int(len(mesh.vertices))
    face_cleanup = _drop_degenerate_and_duplicate_faces(mesh)
    welded_vertices = _weld_vertices(mesh, config.weld_tolerance_m)

    labels, component_count = face_component_labels(
        len(mesh.vertices), np.asarray(mesh.faces, dtype=np.int64)
    )
    face_areas = np.asarray(mesh.area_faces, dtype=np.float64)
    counts = np.bincount(labels, minlength=component_count)
    areas = np.bincount(labels, weights=face_areas, minlength=component_count)
    total_area = max(float(areas.sum()), np.finfo(np.float64).tiny)

    face_vertices = np.asarray(mesh.vertices)[np.asarray(mesh.faces, dtype=np.int64)]
    face_minimum = np.min(face_vertices, axis=1)
    face_maximum = np.max(face_vertices, axis=1)
    component_minimum = np.full((component_count, 3), np.inf, dtype=np.float64)
    component_maximum = np.full((component_count, 3), -np.inf, dtype=np.float64)
    for axis in range(3):
        np.minimum.at(component_minimum[:, axis], labels, face_minimum[:, axis])
        np.maximum.at(component_maximum[:, axis], labels, face_maximum[:, axis])
    diagonals = np.linalg.norm(component_maximum - component_minimum, axis=1)
    asset_diagonal = max(float(np.linalg.norm(np.ptp(source_bounds, axis=0))), 1e-12)

    keep_component = (
        (counts >= int(config.minimum_component_faces))
        | (areas / total_area >= float(config.minimum_component_area_fraction))
        | (diagonals / asset_diagonal >= float(config.minimum_component_diagonal_fraction))
    )
    eligible = np.nonzero(keep_component)[0]
    cap_applied = len(eligible) > config.maximum_components
    if cap_applied:
        ranked = eligible[np.argsort(areas[eligible])[::-1]]
        keep_component[:] = False
        keep_component[ranked[: config.maximum_components]] = True

    keep_faces = keep_component[labels]
    removed_component_count = int(component_count - np.count_nonzero(keep_component))
    removed_face_count = int(np.count_nonzero(~keep_faces))
    mesh.update_faces(keep_faces)
    mesh.remove_unreferenced_vertices()

    retained_area_fraction = float(mesh.area / total_area) if len(mesh.faces) else 0.0
    cleaned_bounds = np.asarray(mesh.bounds, dtype=np.float64) if len(mesh.faces) else source_bounds
    bounds_change = np.max(np.abs(cleaned_bounds - source_bounds), axis=0)
    reasons: list[str] = []
    if retained_area_fraction < config.minimum_retained_area_fraction:
        reasons.append("retained_area_below_threshold")
    if float(np.max(bounds_change)) > config.maximum_bounds_change_m:
        reasons.append("bounds_changed_beyond_threshold")
    if not len(mesh.faces):
        reasons.append("cleanup_removed_all_faces")

    report = {
        "schema": COLLISION_MESH_CLEANUP_SCHEMA,
        "accepted": not reasons,
        "reasons": reasons,
        "non_destructive_visual_mesh_preserved": True,
        "hole_filling_performed": False,
        "global_voxel_remesh_performed": False,
        "config": asdict(config),
        "source": {
            "mesh_hash": source_hash,
            "vertex_count": source_vertices,
            "face_count": source_faces,
            "surface_area_m2": source_area,
            "bounds_m": source_bounds.tolist(),
        },
        "cleanup": {
            **face_cleanup,
            "welded_vertex_count": welded_vertices,
            "component_count_after_weld": component_count,
            "component_cap_applied": cap_applied,
            "kept_component_count": int(np.count_nonzero(keep_component)),
            "removed_component_count": removed_component_count,
            "removed_face_count": removed_face_count,
            "retained_area_fraction": retained_area_fraction,
            "bounds_change_m": bounds_change.tolist(),
            "cleaned_mesh_hash": _mesh_hash(mesh),
            "cleaned_vertex_count": int(len(mesh.vertices)),
            "cleaned_face_count": int(len(mesh.faces)),
            "cleaned_bounds_m": cleaned_bounds.tolist(),
        },
    }
    return mesh, report
