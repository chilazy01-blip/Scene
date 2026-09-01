from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

import numpy as np
import trimesh
from scipy import ndimage

from .collision_mesh_cleanup import face_component_labels
from .collision_proxy import VoxelSDF


MULTILEVEL_PROXY_SCHEMA = "codex_trellis_multilevel_collision_proxy_v1"


@dataclass(frozen=True)
class ProxyLevelSpec:
    name: str
    pitch_m: float
    surface_dilation_voxels: int = 1

    def validate(self) -> None:
        if not self.name:
            raise ValueError("proxy level name must be non-empty")
        if self.pitch_m <= 0.0:
            raise ValueError("proxy level pitch must be positive")
        if self.surface_dilation_voxels < 0:
            raise ValueError("surface dilation must be non-negative")


@dataclass
class MultiLevelProxy:
    levels: dict[str, VoxelSDF]
    manifest: dict[str, Any]

    def query(self, points: np.ndarray, *, level: str | None = None) -> np.ndarray:
        selected = level or str(self.manifest["finest_level"])
        if selected not in self.levels:
            raise KeyError(f"unknown collision proxy level: {selected}")
        return self.levels[selected].query(points)

    @property
    def pitch(self) -> float:
        return float(self.levels[str(self.manifest["finest_level"])].pitch)

    @property
    def metadata(self) -> dict[str, Any]:
        return self.levels[str(self.manifest["finest_level"])].metadata


def mesh_content_hash(mesh: trimesh.Trimesh) -> str:
    digest = hashlib.sha256()
    digest.update(np.ascontiguousarray(mesh.vertices, dtype=np.float64).tobytes())
    digest.update(np.ascontiguousarray(mesh.faces, dtype=np.int64).tobytes())
    return digest.hexdigest()


def _split_components(
    mesh: trimesh.Trimesh, maximum_split_components: int
) -> tuple[Iterator[trimesh.Trimesh], str, int]:
    """Stream connected meshes without retaining every component copy.

    TRELLIS triangle soups can contain hundreds of retained parts.  Trimesh's
    ``mesh.split`` materializes all part meshes at once, so even a moderate
    180k-face chair can cross the task RSS gate.  The union-find labels below
    stay compact, and each minimal untextured collision component is released
    before the next is created.
    """

    labels, source_component_count = face_component_labels(
        len(mesh.vertices), np.asarray(mesh.faces, dtype=np.int64)
    )
    if source_component_count > maximum_split_components:
        return iter((mesh,)), "global_surface_budget_fallback", source_component_count

    order = np.argsort(labels, kind="stable")
    counts = np.bincount(labels, minlength=source_component_count)
    offsets = np.concatenate(([0], np.cumsum(counts, dtype=np.int64)))

    def stream() -> Iterator[trimesh.Trimesh]:
        source_faces = np.asarray(mesh.faces, dtype=np.int64)
        source_vertices = np.asarray(mesh.vertices, dtype=np.float64)
        for component_index in range(source_component_count):
            face_indices = order[offsets[component_index] : offsets[component_index + 1]]
            if not len(face_indices):
                continue
            faces = source_faces[face_indices]
            vertex_indices, inverse = np.unique(faces.reshape(-1), return_inverse=True)
            yield trimesh.Trimesh(
                vertices=source_vertices[vertex_indices],
                faces=inverse.reshape((-1, 3)),
                process=False,
            )

    return stream(), "connected_components_streaming", source_component_count


def _component_voxel_points(
    component: trimesh.Trimesh,
    pitch: float,
    *,
    fill_watertight_components: bool,
) -> tuple[np.ndarray, bool]:
    grid = component.voxelized(pitch)
    filled = bool(fill_watertight_components and component.is_watertight)
    if filled:
        grid = grid.copy().fill()
    return np.asarray(grid.points, dtype=np.float64), filled


def build_component_aware_sdf(
    mesh: trimesh.Trimesh,
    *,
    pitch: float,
    padding_voxels: int = 3,
    surface_dilation_voxels: int = 1,
    fill_watertight_components: bool = True,
    maximum_split_components: int = 512,
    metadata: dict[str, Any] | None = None,
) -> VoxelSDF:
    """Build a conservative proxy without filling across separate open parts.

    Each connected component is voxelized independently.  A component is
    interior-filled only when it is itself watertight; an open assembly is never
    globally filled, so a shelf portal or desk bay remains open.
    """

    if pitch <= 0.0:
        raise ValueError("pitch must be positive")
    if padding_voxels < 1:
        raise ValueError("padding_voxels must be at least 1")
    if surface_dilation_voxels < 0:
        raise ValueError("surface_dilation_voxels must be non-negative")
    if maximum_split_components < 1:
        raise ValueError("maximum_split_components must be positive")
    components, component_strategy, source_component_count = _split_components(
        mesh, maximum_split_components
    )
    if not len(mesh.faces):
        raise ValueError("mesh has no triangle components")

    lower = np.floor(np.asarray(mesh.bounds[0]) / pitch) * pitch
    upper = np.ceil(np.asarray(mesh.bounds[1]) / pitch) * pitch
    origin = lower - padding_voxels * pitch
    shape = np.ceil((upper - lower) / pitch).astype(int) + 1 + 2 * padding_voxels
    occupancy = np.zeros(tuple(int(value) for value in shape), dtype=bool)
    reports: list[dict[str, Any]] = []
    for index, component in enumerate(components):
        allow_fill = bool(
            fill_watertight_components
            and component_strategy == "connected_components_streaming"
        )
        points, filled = _component_voxel_points(
            component,
            pitch,
            fill_watertight_components=allow_fill,
        )
        indices = np.rint((points - origin) / pitch).astype(np.int64)
        valid = np.all((indices >= 0) & (indices < np.asarray(shape)), axis=1)
        indices = indices[valid]
        occupancy[indices[:, 0], indices[:, 1], indices[:, 2]] = True
        reports.append(
            {
                "component_index": index,
                "face_count": int(len(component.faces)),
                "watertight": bool(component.is_watertight),
                "interior_filled": filled,
                "voxel_count_before_union": int(len(indices)),
            }
        )
    if surface_dilation_voxels:
        occupancy = ndimage.binary_dilation(
            occupancy, iterations=int(surface_dilation_voxels)
        )

    outside = ndimage.distance_transform_edt(~occupancy)
    inside = ndimage.distance_transform_edt(occupancy)
    sdf = (outside - 0.5) * pitch
    sdf[occupancy] = -(inside[occupancy] - 0.5) * pitch
    approximation_error = (
        math.sqrt(3.0) * pitch / 2.0 + surface_dilation_voxels * pitch
    )
    report = dict(metadata or {})
    report.update(
        {
            "schema": MULTILEVEL_PROXY_SCHEMA,
            "construction": "component_aware_voxel_outer_proxy",
            "mesh_hash": mesh_content_hash(mesh),
            "pitch_m": float(pitch),
            "padding_voxels": int(padding_voxels),
            "surface_dilation_voxels": int(surface_dilation_voxels),
            "fill_policy": "watertight_components_only",
            "component_count": len(reports),
            "source_component_count": source_component_count,
            "component_strategy": component_strategy,
            "maximum_split_components": int(maximum_split_components),
            "components": reports,
            "grid_shape": [int(value) for value in occupancy.shape],
            "grid_origin_m": origin.tolist(),
            "occupied_voxel_count": int(np.count_nonzero(occupancy)),
            "max_discretization_error_m": float(approximation_error),
            "sign_semantics": "occupied_proxy_negative_not_visual_mesh_interior",
        }
    )
    return VoxelSDF(
        sdf=np.asarray(sdf, dtype=np.float32),
        occupancy=occupancy,
        origin=origin,
        pitch=float(pitch),
        metadata=report,
    )


def compile_multilevel_proxy(
    mesh: trimesh.Trimesh,
    specs: Iterable[ProxyLevelSpec],
    *,
    padding_voxels: int = 3,
    fill_watertight_components: bool = True,
    maximum_split_components: int = 512,
    metadata: dict[str, Any] | None = None,
) -> MultiLevelProxy:
    specs = list(specs)
    if not specs:
        raise ValueError("at least one proxy level is required")
    for spec in specs:
        spec.validate()
    names = [spec.name for spec in specs]
    if len(names) != len(set(names)):
        raise ValueError("proxy level names must be unique")

    ordered = sorted(specs, key=lambda item: item.pitch_m, reverse=True)
    levels: dict[str, VoxelSDF] = {}
    for spec in ordered:
        levels[spec.name] = build_component_aware_sdf(
            mesh,
            pitch=spec.pitch_m,
            padding_voxels=padding_voxels,
            surface_dilation_voxels=spec.surface_dilation_voxels,
            fill_watertight_components=fill_watertight_components,
            maximum_split_components=maximum_split_components,
            metadata={**dict(metadata or {}), "level_name": spec.name},
        )
    mesh_digest = mesh_content_hash(mesh)
    manifest = {
        "schema": MULTILEVEL_PROXY_SCHEMA,
        "mesh_hash": mesh_digest,
        "coarsest_level": ordered[0].name,
        "finest_level": ordered[-1].name,
        "levels": [
            {
                "name": spec.name,
                "pitch_m": float(spec.pitch_m),
                "surface_dilation_voxels": int(spec.surface_dilation_voxels),
                "max_discretization_error_m": float(
                    levels[spec.name].metadata["max_discretization_error_m"]
                ),
            }
            for spec in ordered
        ],
    }
    manifest["build_hash"] = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return MultiLevelProxy(levels=levels, manifest=manifest)


def save_multilevel_proxy(proxy: MultiLevelProxy, output_directory: Path) -> Path:
    """Commit level files first and the manifest last.

    Readers treat the manifest as the commit marker, so an interrupted build
    cannot advertise a half-written proxy set.
    """

    output_directory.mkdir(parents=True, exist_ok=True)
    manifest = dict(proxy.manifest)
    level_entries = {entry["name"]: dict(entry) for entry in manifest["levels"]}
    for name, level in proxy.levels.items():
        final_path = output_directory / f"{name}.npz"
        with tempfile.NamedTemporaryFile(
            prefix=f".{name}.", suffix=".npz", dir=output_directory, delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
        try:
            level.save(temporary_path)
            os.replace(temporary_path, final_path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()
        level_entries[name]["path"] = final_path.name
    manifest["levels"] = [
        level_entries[entry["name"]] for entry in proxy.manifest["levels"]
    ]
    final_manifest = output_directory / "manifest.json"
    with tempfile.NamedTemporaryFile(
        prefix=".manifest.", suffix=".json", dir=output_directory, delete=False
    ) as temporary:
        temporary_path = Path(temporary.name)
        temporary.write(
            (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
        )
    try:
        os.replace(temporary_path, final_manifest)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    return final_manifest


def load_multilevel_proxy(manifest_path: Path) -> MultiLevelProxy:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != MULTILEVEL_PROXY_SCHEMA:
        raise ValueError(f"unsupported multilevel proxy schema: {manifest.get('schema')}")
    levels = {
        str(entry["name"]): VoxelSDF.load(manifest_path.parent / str(entry["path"]))
        for entry in manifest.get("levels", [])
    }
    if set(levels) != {str(entry["name"]) for entry in manifest.get("levels", [])}:
        raise ValueError("proxy manifest level set is incomplete")
    return MultiLevelProxy(levels=levels, manifest=manifest)
