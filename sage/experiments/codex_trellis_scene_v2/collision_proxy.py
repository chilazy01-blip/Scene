from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import trimesh
from scipy import ndimage


VOXEL_SDF_SCHEMA = "codex_trellis_voxel_sdf_v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _axis_to_z_matrix(axis_to_z: int, axis_sign: float) -> np.ndarray:
    sign = -1.0 if float(axis_sign) < 0.0 else 1.0
    result = np.eye(4, dtype=np.float64)
    if axis_to_z == 0:
        result[:3, :3] = (
            np.array(
                ((0.0, 0.0, 1.0), (0.0, 1.0, 0.0), (-1.0, 0.0, 0.0))
            )
            if sign < 0.0
            else np.array(
                ((0.0, 0.0, -1.0), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0))
            )
        )
    elif axis_to_z == 1:
        result[:3, :3] = (
            np.array(
                ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, -1.0, 0.0))
            )
            if sign < 0.0
            else np.array(
                ((1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.0, 1.0, 0.0))
            )
        )
    return result


def _yaw_matrix(degrees: float) -> np.ndarray:
    angle = math.radians(float(degrees))
    cosine = math.cos(angle)
    sine = math.sin(angle)
    result = np.eye(4, dtype=np.float64)
    result[:3, :3] = np.array(
        ((cosine, -sine, 0.0), (sine, cosine, 0.0), (0.0, 0.0, 1.0))
    )
    return result


def resolve_capability_glb(capability: dict[str, Any], asset_root: Path) -> Path:
    relative = Path(str(capability["collision_proxy"]["source_glb"]))
    if relative.is_absolute():
        raise ValueError("capability source_glb must be relative")
    path = (asset_root / relative).resolve()
    root = asset_root.resolve()
    if root not in path.parents:
        raise ValueError("capability source_glb escapes asset root")
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def load_normalized_asset_mesh(
    capability: dict[str, Any],
    asset_root: Path,
    *,
    verify_hash: bool = True,
) -> tuple[trimesh.Trimesh, dict[str, Any]]:
    path = resolve_capability_glb(capability, asset_root)
    actual_sha256 = sha256_file(path)
    expected_sha256 = str(capability["source_asset"]["sha256"])
    if verify_hash and actual_sha256 != expected_sha256:
        raise ValueError(
            f"asset hash mismatch for {capability['asset_id']}: "
            f"{actual_sha256} != {expected_sha256}"
        )

    loaded = trimesh.load(path, force="scene")
    mesh = loaded.to_geometry()
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
        raise ValueError(f"asset has no triangle mesh: {path}")

    frame = capability["coordinate_frame"]
    source_up_axis = str(frame.get("source_mesh_up_axis") or "z")
    source_axis_to_z = {"x": 0, "y": 1, "z": 2}[source_up_axis]
    mesh.apply_transform(
        _axis_to_z_matrix(
            source_axis_to_z,
            float(frame.get("source_mesh_up_sign", 1.0)),
        )
    )
    mesh.apply_transform(
        _yaw_matrix(float(frame.get("asset_local_yaw_offset_degrees", 0.0)))
    )
    raw_bounds = np.asarray(mesh.bounds, dtype=np.float64)
    raw_extents = np.asarray(mesh.extents, dtype=np.float64)
    center = np.asarray(mesh.bounding_box.centroid, dtype=np.float64)
    dimensions = frame["canonical_dimensions"]
    target = np.array(
        [
            float(dimensions["width"]),
            float(dimensions["length"]),
            float(dimensions["height"]),
        ],
        dtype=np.float64,
    )
    scale = target / np.maximum(raw_extents, 1e-9)
    mesh.apply_translation(-center)
    mesh.apply_scale(scale)
    mesh.apply_translation((0.0, 0.0, target[2] / 2.0))

    return mesh, {
        "asset_id": capability["asset_id"],
        "source_glb": str(path),
        "source_sha256": actual_sha256,
        "source_geometry_count": len(loaded.geometry),
        "source_face_count": int(len(mesh.faces)),
        "source_body_count": int(mesh.body_count),
        "source_watertight": bool(mesh.is_watertight),
        "raw_bounds": raw_bounds.tolist(),
        "raw_extents": raw_extents.tolist(),
        "source_mesh_up_axis": source_up_axis,
        "source_mesh_up_sign": float(frame.get("source_mesh_up_sign", 1.0)),
        "canonical_dimensions": target.tolist(),
        "mesh_normalization_scale": scale.tolist(),
        "normalized_bounds": np.asarray(mesh.bounds).tolist(),
    }


@dataclass
class VoxelSDF:
    sdf: np.ndarray
    occupancy: np.ndarray
    origin: np.ndarray
    pitch: float
    metadata: dict[str, Any]

    def query(self, points: np.ndarray) -> np.ndarray:
        points = np.asarray(points, dtype=np.float64)
        if points.ndim == 1:
            points = points.reshape(1, 3)
        coordinates = (points - self.origin.reshape(1, 3)) / self.pitch
        maximum = np.asarray(self.sdf.shape, dtype=np.float64) - 1.0
        clipped = np.clip(coordinates, 0.0, maximum)
        values = ndimage.map_coordinates(
            self.sdf,
            clipped.T,
            order=1,
            mode="nearest",
            prefilter=False,
        )
        outside_delta = (coordinates - clipped) * self.pitch
        outside_distance = np.linalg.norm(outside_delta, axis=1)
        outside = outside_distance > 0.0
        values[outside] = np.maximum(values[outside], 0.0) + outside_distance[outside]
        return values.astype(np.float64)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            path,
            schema=np.asarray(VOXEL_SDF_SCHEMA),
            sdf=np.asarray(self.sdf, dtype=np.float32),
            occupancy=np.asarray(self.occupancy, dtype=np.uint8),
            origin=np.asarray(self.origin, dtype=np.float64),
            pitch=np.asarray(float(self.pitch), dtype=np.float64),
            metadata=np.asarray(json.dumps(self.metadata, sort_keys=True)),
        )

    @classmethod
    def load(cls, path: Path) -> "VoxelSDF":
        with np.load(path, allow_pickle=False) as payload:
            schema = str(payload["schema"].item())
            if schema != VOXEL_SDF_SCHEMA:
                raise ValueError(f"Unsupported voxel SDF schema: {schema}")
            return cls(
                sdf=np.asarray(payload["sdf"], dtype=np.float32),
                occupancy=np.asarray(payload["occupancy"], dtype=bool),
                origin=np.asarray(payload["origin"], dtype=np.float64),
                pitch=float(payload["pitch"].item()),
                metadata=json.loads(str(payload["metadata"].item())),
            )


def build_voxel_sdf(
    mesh: trimesh.Trimesh,
    *,
    pitch: float,
    padding_voxels: int,
    fill_interior: bool,
    surface_dilation_voxels: int = 0,
    metadata: dict[str, Any] | None = None,
) -> VoxelSDF:
    if pitch <= 0.0:
        raise ValueError("pitch must be positive")
    if padding_voxels < 1:
        raise ValueError("padding_voxels must be at least 1")

    voxelized = mesh.voxelized(float(pitch))
    raw_surface_count = int(voxelized.filled_count)
    if fill_interior:
        voxelized = voxelized.copy().fill()
    occupancy = np.asarray(voxelized.matrix, dtype=bool)
    if surface_dilation_voxels > 0:
        occupancy = ndimage.binary_dilation(
            occupancy, iterations=int(surface_dilation_voxels)
        )
    occupancy = np.pad(
        occupancy,
        int(padding_voxels),
        mode="constant",
        constant_values=False,
    )
    base_origin = voxelized.indices_to_points(np.array([[0, 0, 0]], dtype=int))[0]
    origin = np.asarray(base_origin, dtype=np.float64) - float(
        padding_voxels
    ) * float(pitch)

    outside = ndimage.distance_transform_edt(~occupancy)
    inside = ndimage.distance_transform_edt(occupancy)
    sdf = (outside - 0.5) * float(pitch)
    sdf[occupancy] = -(inside[occupancy] - 0.5) * float(pitch)
    report = dict(metadata or {})
    report.update(
        {
            "schema": VOXEL_SDF_SCHEMA,
            "pitch_m": float(pitch),
            "padding_voxels": int(padding_voxels),
            "fill_interior": bool(fill_interior),
            "surface_dilation_voxels": int(surface_dilation_voxels),
            "grid_shape": [int(value) for value in occupancy.shape],
            "grid_origin_m": origin.tolist(),
            "raw_surface_voxel_count": raw_surface_count,
            "occupied_voxel_count": int(occupancy.sum()),
            "occupied_ratio": float(occupancy.mean()),
            "sign_strategy": "filled_voxel_occupancy_edt",
        }
    )
    return VoxelSDF(
        sdf=np.asarray(sdf, dtype=np.float32),
        occupancy=occupancy,
        origin=origin,
        pitch=float(pitch),
        metadata=report,
    )


def build_capability_proxy(
    capability: dict[str, Any],
    asset_root: Path,
    output_path: Path,
    *,
    verify_hash: bool = True,
) -> tuple[VoxelSDF, trimesh.Trimesh, dict[str, Any]]:
    total_started = time.perf_counter()
    mesh, normalization = load_normalized_asset_mesh(
        capability, asset_root, verify_hash=verify_hash
    )
    config = capability["collision_proxy"]
    if output_path.is_file():
        cached = VoxelSDF.load(output_path)
        cached_normalization = cached.metadata.get("normalization")
        cached_normalization = (
            cached_normalization if isinstance(cached_normalization, dict) else {}
        )
        cache_matches = (
            str(cached.metadata.get("asset_id") or "")
            == str(capability["asset_id"])
            and str(cached.metadata.get("source_sha256") or "")
            == str(normalization["source_sha256"])
            and abs(float(cached.pitch) - float(config["voxel_pitch_m"])) <= 1e-12
            and int(cached.metadata.get("padding_voxels", -1))
            == int(config["padding_voxels"])
            and str(cached_normalization.get("source_mesh_up_axis") or "")
            == str(capability["coordinate_frame"]["source_mesh_up_axis"])
        )
        if cache_matches:
            cached.metadata["cache_hit"] = True
            cached.metadata["cache_bytes"] = int(output_path.stat().st_size)
            cached.metadata["total_proxy_load_seconds"] = round(
                time.perf_counter() - total_started, 6
            )
            return cached, mesh, cached.metadata

    build_started = time.perf_counter()
    proxy = build_voxel_sdf(
        mesh,
        pitch=float(config["voxel_pitch_m"]),
        padding_voxels=int(config["padding_voxels"]),
        fill_interior=bool(config.get("fill_interior", True)),
        surface_dilation_voxels=int(config.get("surface_dilation_voxels", 0)),
        metadata={
            "asset_id": capability["asset_id"],
            "category": capability["category"],
            "source_sha256": normalization["source_sha256"],
            "source_watertight": normalization["source_watertight"],
            "source_face_count": normalization["source_face_count"],
            "source_body_count": normalization["source_body_count"],
            "normalization": normalization,
        },
    )
    proxy.metadata["voxel_sdf_build_seconds"] = round(
        time.perf_counter() - build_started, 6
    )
    proxy.metadata["total_proxy_build_seconds"] = round(
        time.perf_counter() - total_started, 6
    )
    proxy.metadata["cache_hit"] = False
    proxy.save(output_path)
    proxy.metadata["cache_bytes"] = int(output_path.stat().st_size)
    proxy.save(output_path)
    proxy.metadata["cache_bytes"] = int(output_path.stat().st_size)
    return proxy, mesh, proxy.metadata
