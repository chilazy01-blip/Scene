from __future__ import annotations

import math
from copy import deepcopy
from pathlib import Path
from typing import Any

from .io_utils import read_json


ASSET_CAPABILITY_SCHEMA = "codex_trellis_asset_capability_v1"
CAPABILITY_REGISTRY_SCHEMA = "codex_trellis_asset_capability_registry_v1"
SUPPORTED_DIMENSION_POLICIES = {
    "fixed_physical",
    "uniform_scalable",
    "axis_scalable",
    "opening_fit",
    "modular",
}
SUPPORTED_PROXY_TYPES = {"voxel_sdf"}
SUPPORTED_SUPPORT_SHAPES = {"planar_rectangle"}
SUPPORTED_CONTAINMENT_SHAPES = {"box"}


def _positive_dimensions(value: Any) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    axes = ("width", "length", "height")
    if not all(axis in value for axis in axes):
        return None
    result = {axis: float(value[axis]) for axis in axes}
    return result if all(result[axis] > 0.0 for axis in axes) else None


def _vector(value: Any, length: int) -> list[float] | None:
    if not isinstance(value, list) or len(value) != length:
        return None
    if not all(isinstance(item, (int, float)) for item in value):
        return None
    return [float(item) for item in value]


def _validate_coordinate_frame(
    capability: dict[str, Any], errors: list[str]
) -> dict[str, float] | None:
    frame = capability.get("coordinate_frame")
    if not isinstance(frame, dict):
        errors.append("coordinate_frame must be an object")
        return None
    if frame.get("units") != "meters":
        errors.append("coordinate_frame.units must be meters")
    if frame.get("up_axis") != "z":
        errors.append("coordinate_frame.up_axis must be z")
    if frame.get("origin") != "footprint_center_base":
        errors.append("coordinate_frame.origin must be footprint_center_base")
    if frame.get("source_mesh_up_axis") not in {"x", "y", "z"}:
        errors.append("coordinate_frame.source_mesh_up_axis must be x, y, or z")
    if float(frame.get("source_mesh_up_sign", 0.0) or 0.0) not in {-1.0, 1.0}:
        errors.append("coordinate_frame.source_mesh_up_sign must be -1 or 1")
    dimensions = _positive_dimensions(frame.get("canonical_dimensions"))
    if dimensions is None:
        errors.append(
            "coordinate_frame.canonical_dimensions must contain positive width, length, and height"
        )
    return dimensions


def _validate_collision_proxy(capability: dict[str, Any], errors: list[str]) -> None:
    proxy = capability.get("collision_proxy")
    if not isinstance(proxy, dict):
        errors.append("collision_proxy must be an object")
        return
    if proxy.get("representation") not in SUPPORTED_PROXY_TYPES:
        errors.append("collision_proxy.representation must be voxel_sdf")
    source_glb = proxy.get("source_glb")
    if not isinstance(source_glb, str) or not source_glb.strip():
        errors.append("collision_proxy.source_glb must be a non-empty relative path")
    elif Path(source_glb).is_absolute():
        errors.append("collision_proxy.source_glb must be relative to the asset root")
    if float(proxy.get("voxel_pitch_m", 0.0) or 0.0) <= 0.0:
        errors.append("collision_proxy.voxel_pitch_m must be positive")
    if int(proxy.get("padding_voxels", 0) or 0) < 1:
        errors.append("collision_proxy.padding_voxels must be at least 1")
    if proxy.get("sign_strategy") != "filled_voxel_occupancy_edt":
        errors.append(
            "collision_proxy.sign_strategy must be filled_voxel_occupancy_edt"
        )


def _validate_support_surfaces(
    capability: dict[str, Any],
    dimensions: dict[str, float] | None,
    errors: list[str],
) -> None:
    surfaces = capability.get("support_surfaces")
    if not isinstance(surfaces, list):
        errors.append("support_surfaces must be a list")
        return
    seen: set[str] = set()
    for index, surface in enumerate(surfaces):
        prefix = f"support_surfaces[{index}]"
        if not isinstance(surface, dict):
            errors.append(f"{prefix} must be an object")
            continue
        surface_id = str(surface.get("id") or "")
        if not surface_id:
            errors.append(f"{prefix}.id must be non-empty")
        elif surface_id in seen:
            errors.append(f"duplicate support surface id: {surface_id}")
        seen.add(surface_id)
        if surface.get("shape") not in SUPPORTED_SUPPORT_SHAPES:
            errors.append(f"{prefix}.shape must be planar_rectangle")
        center = _vector(surface.get("center_m"), 3)
        normal = _vector(surface.get("normal"), 3)
        u_axis = _vector(surface.get("u_axis"), 3)
        v_axis = _vector(surface.get("v_axis"), 3)
        half_extents = _vector(surface.get("half_extents_m"), 2)
        if center is None:
            errors.append(f"{prefix}.center_m must be a 3-vector")
        if normal is None or abs(math.sqrt(sum(item * item for item in normal)) - 1.0) > 1e-4:
            errors.append(f"{prefix}.normal must be a unit 3-vector")
        if u_axis is None or v_axis is None:
            errors.append(f"{prefix}.u_axis and v_axis must be 3-vectors")
        elif abs(sum(u_axis[i] * v_axis[i] for i in range(3))) > 1e-4:
            errors.append(f"{prefix}.u_axis and v_axis must be orthogonal")
        if half_extents is None or any(item <= 0.0 for item in half_extents):
            errors.append(f"{prefix}.half_extents_m must contain two positive values")
        allowed = surface.get("allowed_categories")
        if not isinstance(allowed, list) or not all(
            isinstance(item, str) and item for item in allowed
        ):
            errors.append(f"{prefix}.allowed_categories must be a non-empty string list")
        if float(surface.get("contact_tolerance_m", 0.0) or 0.0) <= 0.0:
            errors.append(f"{prefix}.contact_tolerance_m must be positive")
        if dimensions and center and half_extents:
            if abs(center[0]) + half_extents[0] > dimensions["width"] / 2.0 + 1e-6:
                errors.append(f"{prefix} exceeds canonical width")
            if abs(center[1]) + half_extents[1] > dimensions["length"] / 2.0 + 1e-6:
                errors.append(f"{prefix} exceeds canonical length")
            if not -1e-6 <= center[2] <= dimensions["height"] + 1e-6:
                errors.append(f"{prefix}.center_m z lies outside canonical height")


def _validate_containment_volumes(
    capability: dict[str, Any],
    dimensions: dict[str, float] | None,
    errors: list[str],
) -> None:
    volumes = capability.get("containment_volumes")
    if not isinstance(volumes, list):
        errors.append("containment_volumes must be a list")
        return
    seen: set[str] = set()
    for index, volume in enumerate(volumes):
        prefix = f"containment_volumes[{index}]"
        if not isinstance(volume, dict):
            errors.append(f"{prefix} must be an object")
            continue
        volume_id = str(volume.get("id") or "")
        if not volume_id:
            errors.append(f"{prefix}.id must be non-empty")
        elif volume_id in seen:
            errors.append(f"duplicate containment volume id: {volume_id}")
        seen.add(volume_id)
        if volume.get("shape") not in SUPPORTED_CONTAINMENT_SHAPES:
            errors.append(f"{prefix}.shape must be box")
        minimum = _vector(volume.get("min_m"), 3)
        maximum = _vector(volume.get("max_m"), 3)
        if minimum is None or maximum is None:
            errors.append(f"{prefix}.min_m and max_m must be 3-vectors")
            continue
        if any(minimum[axis] >= maximum[axis] for axis in range(3)):
            errors.append(f"{prefix}.min_m must be smaller than max_m")
        if dimensions:
            lower = (
                -dimensions["width"] / 2.0,
                -dimensions["length"] / 2.0,
                0.0,
            )
            upper = (
                dimensions["width"] / 2.0,
                dimensions["length"] / 2.0,
                dimensions["height"],
            )
            if any(
                minimum[axis] < lower[axis] - 1e-6
                or maximum[axis] > upper[axis] + 1e-6
                for axis in range(3)
            ):
                errors.append(f"{prefix} lies outside canonical dimensions")


def validate_asset_capability(capability: Any) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(capability, dict):
        return {
            "ok": False,
            "error_count": 1,
            "warning_count": 0,
            "errors": ["asset capability must be an object"],
            "warnings": [],
        }
    if capability.get("schema") != ASSET_CAPABILITY_SCHEMA:
        errors.append(f"schema must be {ASSET_CAPABILITY_SCHEMA}")
    if not str(capability.get("asset_id") or ""):
        errors.append("asset_id must be non-empty")
    if not str(capability.get("category") or ""):
        errors.append("category must be non-empty")

    source = capability.get("source_asset")
    if not isinstance(source, dict):
        errors.append("source_asset must be an object")
    else:
        digest = str(source.get("sha256") or "")
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            errors.append("source_asset.sha256 must be a lowercase SHA-256 digest")

    dimensions = _validate_coordinate_frame(capability, errors)
    policy = capability.get("dimension_policy")
    if not isinstance(policy, dict) or policy.get("mode") not in SUPPORTED_DIMENSION_POLICIES:
        errors.append("dimension_policy.mode is unsupported")
    _validate_collision_proxy(capability, errors)
    _validate_support_surfaces(capability, dimensions, errors)
    _validate_containment_volumes(capability, dimensions, errors)

    if not capability.get("support_surfaces") and not capability.get(
        "containment_volumes"
    ):
        warnings.append("asset exposes geometry only and has no placement capability")
    return {
        "asset_id": capability.get("asset_id"),
        "ok": not errors,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
    }


def validate_capability_registry(registry: Any) -> dict[str, Any]:
    errors: list[str] = []
    assets = registry.get("assets") if isinstance(registry, dict) else None
    if not isinstance(registry, dict):
        errors.append("capability registry must be an object")
        assets = []
    elif registry.get("schema") != CAPABILITY_REGISTRY_SCHEMA:
        errors.append(f"schema must be {CAPABILITY_REGISTRY_SCHEMA}")
    if not isinstance(assets, list):
        errors.append("assets must be a list")
        assets = []
    results = [validate_asset_capability(asset) for asset in assets]
    ids = [str(asset.get("asset_id") or "") for asset in assets if isinstance(asset, dict)]
    duplicates = sorted({asset_id for asset_id in ids if ids.count(asset_id) > 1})
    if duplicates:
        errors.append("duplicate asset ids: " + ", ".join(duplicates))
    return {
        "schema": "codex_trellis_asset_capability_validation_v1",
        "ok": not errors and all(result["ok"] for result in results),
        "registry_errors": errors,
        "asset_count": len(assets),
        "valid_asset_count": sum(bool(result["ok"]) for result in results),
        "error_count": len(errors)
        + sum(int(result["error_count"]) for result in results),
        "warning_count": sum(int(result["warning_count"]) for result in results),
        "assets": results,
    }


def load_capability_registry(path: Path) -> dict[str, Any]:
    registry = read_json(path)
    validation = validate_capability_registry(registry)
    if not validation["ok"]:
        raise ValueError(
            "Invalid capability registry: "
            + "; ".join(
                validation["registry_errors"]
                + [
                    error
                    for result in validation["assets"]
                    for error in result["errors"]
                ]
            )
        )
    result = deepcopy(registry)
    result["validation"] = validation
    return result


def capability_index(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(asset["asset_id"]): asset
        for asset in registry.get("assets", [])
        if isinstance(asset, dict) and asset.get("asset_id")
    }
