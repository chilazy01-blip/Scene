"""Deterministic material-slot contracts and P018 three-path routing.

This module deliberately stays independent from the unfinished P017 asset
index.  Geometry/category selection remains upstream; this layer decides only
whether an already compatible geometry can be reused as-is, safely
rematerialized, or must be returned to the geometry-generation path.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import struct
import tempfile
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable

from PIL import Image


GLB_MAGIC = 0x46546C67
JSON_CHUNK = 0x4E4F534A
BIN_CHUNK = 0x004E4942
MATERIAL_FAMILIES = {"wood", "metal", "fabric", "glass"}
ROUTE_EXACT = "exact_reuse"
ROUTE_REMATERIALIZE = "controlled_rematerialization"
ROUTE_REGENERATE = "regenerate_geometry"


class MaterialContractError(ValueError):
    """Raised when a material package or slot contract is unsafe."""


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_material_package(package: dict[str, Any]) -> dict[str, Any]:
    package_id = str(package.get("package_id") or "")
    family = str(package.get("material_family") or "")
    if not package_id:
        raise MaterialContractError("material package requires package_id")
    if family not in MATERIAL_FAMILIES:
        raise MaterialContractError(
            f"unsupported material_family for {package_id}: {family}"
        )
    roles = package.get("compatible_slot_roles")
    if not isinstance(roles, list) or not roles or not all(str(item) for item in roles):
        raise MaterialContractError(
            f"material package {package_id} requires compatible_slot_roles"
        )
    pbr = package.get("pbr")
    if not isinstance(pbr, dict):
        raise MaterialContractError(f"material package {package_id} requires pbr")
    base = pbr.get("base_color_srgb")
    if not isinstance(base, list) or len(base) not in {3, 4}:
        raise MaterialContractError(f"material package {package_id} base color invalid")
    if any(float(value) < 0.0 or float(value) > 1.0 for value in base):
        raise MaterialContractError(f"material package {package_id} base color out of range")
    for name in ("roughness", "metallic"):
        value = float(pbr.get(name, -1.0))
        if not 0.0 <= value <= 1.0:
            raise MaterialContractError(
                f"material package {package_id} {name} out of range"
            )
    alpha_mode = str(pbr.get("alpha_mode") or "OPAQUE")
    if alpha_mode not in {"OPAQUE", "MASK", "BLEND"}:
        raise MaterialContractError(f"material package {package_id} alpha mode invalid")
    texture = package.get("texture")
    if texture is not None:
        if not isinstance(texture, dict):
            raise MaterialContractError(f"material package {package_id} texture invalid")
        if str(texture.get("color_space") or "") != "sRGB":
            raise MaterialContractError(
                f"material package {package_id} base-color texture must be sRGB"
            )
        scale = float(texture.get("real_scale_m", 0.0))
        resolution = int(texture.get("resolution", 0))
        if scale <= 0 or resolution <= 0:
            raise MaterialContractError(
                f"material package {package_id} texture scale/resolution invalid"
            )
    normalized = deepcopy(package)
    normalized["package_id"] = package_id
    normalized["material_family"] = family
    normalized["compatible_slot_roles"] = sorted({str(item) for item in roles})
    normalized["package_hash"] = content_hash(
        {key: value for key, value in normalized.items() if key != "package_hash"}
    )
    return normalized


def load_material_library(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    packages = payload.get("packages", []) if isinstance(payload, dict) else []
    if not isinstance(packages, list):
        raise MaterialContractError("material library packages must be a list")
    resolved: dict[str, dict[str, Any]] = {}
    for raw in packages:
        if not isinstance(raw, dict):
            raise MaterialContractError("material library package must be an object")
        package = validate_material_package(raw)
        if package["package_id"] in resolved:
            raise MaterialContractError(
                f"duplicate material package: {package['package_id']}"
            )
        resolved[package["package_id"]] = package
    return resolved


def validate_slot_contract(slot: dict[str, Any]) -> dict[str, Any]:
    slot_id = str(slot.get("slot_id") or "")
    role = str(slot.get("semantic_role") or "")
    allowed = slot.get("allowed_material_families")
    if not slot_id or not role:
        raise MaterialContractError("slot requires slot_id and semantic_role")
    if not isinstance(allowed, list) or not allowed:
        raise MaterialContractError(f"slot {slot_id} requires allowed material families")
    invalid = sorted(set(str(item) for item in allowed) - MATERIAL_FAMILIES)
    if invalid:
        raise MaterialContractError(f"slot {slot_id} has invalid families: {invalid}")
    if bool(slot.get("requires_uv")) and not bool(slot.get("uv_available")):
        raise MaterialContractError(f"slot {slot_id} requires UV but none is available")
    normalized = deepcopy(slot)
    normalized["slot_id"] = slot_id
    normalized["semantic_role"] = role
    normalized["allowed_material_families"] = sorted(set(str(item) for item in allowed))
    return normalized


def route_material_request(
    slot: dict[str, Any],
    requested_package: dict[str, Any],
    *,
    current_package_id: str | None = None,
) -> dict[str, Any]:
    """Choose exact reuse, controlled rematerialization, or regeneration.

    Every material safety check is a hard gate.  Style/palette similarity is
    intentionally absent here; it is allowed only after this function accepts
    semantic, UV, transparency, and sidedness compatibility.
    """

    try:
        normalized_slot = validate_slot_contract(slot)
        package = validate_material_package(requested_package)
    except MaterialContractError as exc:
        return {
            "route": ROUTE_REGENERATE,
            "accepted": False,
            "hard_gate_failures": [str(exc)],
        }
    failures: list[str] = []
    role = normalized_slot["semantic_role"]
    family = package["material_family"]
    if role not in package["compatible_slot_roles"]:
        failures.append("semantic_slot_role_incompatible")
    if family not in normalized_slot["allowed_material_families"]:
        failures.append("material_family_incompatible")
    texture = package.get("texture")
    if texture and not normalized_slot.get("uv_available"):
        failures.append("textured_package_requires_uv")
    uv_quality = str(normalized_slot.get("uv_quality") or "unknown")
    if texture and uv_quality not in {"valid", "reviewed"}:
        failures.append("uv_quality_not_approved")
    pbr = package["pbr"]
    requested_alpha = str(pbr.get("alpha_mode") or "OPAQUE")
    allowed_alpha = set(normalized_slot.get("allowed_alpha_modes") or ["OPAQUE"])
    if requested_alpha not in allowed_alpha:
        failures.append("alpha_mode_incompatible")
    if bool(pbr.get("double_sided", False)) and not bool(
        normalized_slot.get("allows_double_sided", False)
    ):
        failures.append("double_sided_incompatible")
    minimum_density = float(normalized_slot.get("minimum_texel_density_px_m", 0.0))
    if texture:
        declared_density = float(texture["resolution"]) / float(texture["real_scale_m"])
        if declared_density < minimum_density:
            failures.append("texel_density_below_slot_minimum")
    else:
        declared_density = None
    if failures:
        return {
            "route": ROUTE_REGENERATE,
            "accepted": False,
            "slot_id": normalized_slot["slot_id"],
            "package_id": package["package_id"],
            "hard_gate_failures": failures,
            "global_color_transfer_forbidden": True,
        }
    if current_package_id and current_package_id == package["package_id"]:
        route = ROUTE_EXACT
    elif bool(normalized_slot.get("rematerializable", False)):
        route = ROUTE_REMATERIALIZE
    else:
        return {
            "route": ROUTE_REGENERATE,
            "accepted": False,
            "slot_id": normalized_slot["slot_id"],
            "package_id": package["package_id"],
            "hard_gate_failures": ["slot_not_rematerializable"],
        }
    return {
        "route": route,
        "accepted": True,
        "slot_id": normalized_slot["slot_id"],
        "semantic_role": role,
        "package_id": package["package_id"],
        "material_family": family,
        "declared_texel_density_px_m": declared_density,
        "hard_gate_failures": [],
        "geometry_contract_unchanged": True,
    }


def derived_material_cache_key(
    *,
    geometry_hash: str,
    material_package_hash: str,
    slot_binding: dict[str, Any],
    uv_transform: dict[str, Any],
    renderer_version: str,
) -> str:
    return content_hash(
        {
            "geometry_hash": geometry_hash,
            "material_package_hash": material_package_hash,
            "slot_binding": slot_binding,
            "uv_transform": uv_transform,
            "renderer_version": renderer_version,
        }
    )


def publish_derived_material_cache(
    *,
    source_glb: Path,
    derived_glb: Path,
    cache_root: Path,
    cache_key: str,
    contract: dict[str, Any],
) -> dict[str, Any]:
    """Publish or validate one immutable content-addressed derivative."""

    if len(cache_key) != 64 or any(char not in "0123456789abcdef" for char in cache_key):
        raise MaterialContractError("derived cache key must be a lowercase SHA-256")
    directory = cache_root / cache_key[:2]
    artifact = directory / f"{cache_key}.glb"
    sidecar = directory / f"{cache_key}.json"
    derived_hash = file_sha256(derived_glb)
    expected = {
        "schema": "scene-v2-p018-derived-material-cache-entry/v1",
        "cache_key": cache_key,
        "source_glb": str(source_glb.resolve()),
        "source_glb_sha256": file_sha256(source_glb),
        "derived_glb": str(artifact.resolve()),
        "derived_glb_sha256": derived_hash,
        "contract": deepcopy(contract),
        "contract_hash": content_hash(contract),
    }
    directory.mkdir(parents=True, exist_ok=True)
    cache_hit = artifact.is_file() and sidecar.is_file()
    if cache_hit:
        recorded = json.loads(sidecar.read_text(encoding="utf-8"))
        if recorded != expected or file_sha256(artifact) != derived_hash:
            raise MaterialContractError("derived material cache entry is stale or corrupt")
    else:
        if artifact.exists() or sidecar.exists():
            raise MaterialContractError("partial derived material cache entry exists")
        try:
            os.link(derived_glb, artifact)
        except OSError:
            shutil.copy2(derived_glb, artifact)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=directory, delete=False
        ) as stream:
            json.dump(expected, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            temporary = Path(stream.name)
        temporary.replace(sidecar)
    return {
        "schema": "scene-v2-p018-derived-material-cache-publication/v1",
        "ok": True,
        "cache_hit": cache_hit,
        "cache_key": cache_key,
        "artifact": str(artifact),
        "sidecar": str(sidecar),
        "derived_glb_sha256": derived_hash,
    }


def read_glb(path: Path) -> tuple[dict[str, Any], bytes]:
    data = path.read_bytes()
    if len(data) < 20:
        raise MaterialContractError(f"invalid GLB header: {path}")
    magic, version, total = struct.unpack_from("<III", data, 0)
    if magic != GLB_MAGIC or version != 2 or total != len(data):
        raise MaterialContractError(f"invalid GLB v2 container: {path}")
    offset = 12
    document: dict[str, Any] | None = None
    binary = b""
    while offset + 8 <= len(data):
        length, kind = struct.unpack_from("<II", data, offset)
        offset += 8
        chunk = data[offset : offset + length]
        offset += length
        if kind == JSON_CHUNK:
            document = json.loads(chunk.rstrip(b" \t\r\n\x00").decode("utf-8"))
        elif kind == BIN_CHUNK:
            binary = chunk
    if document is None:
        raise MaterialContractError(f"GLB has no JSON chunk: {path}")
    return document, binary


def _image_payload(
    document: dict[str, Any], binary: bytes, image_index: int
) -> bytes | None:
    images = document.get("images", [])
    if not 0 <= image_index < len(images):
        return None
    image = images[image_index]
    view_index = image.get("bufferView")
    if view_index is None:
        return None
    views = document.get("bufferViews", [])
    if not 0 <= int(view_index) < len(views):
        return None
    view = views[int(view_index)]
    start = int(view.get("byteOffset", 0))
    end = start + int(view.get("byteLength", 0))
    return binary[start:end] if 0 <= start <= end <= len(binary) else None


def audit_glb_materials(path: Path) -> dict[str, Any]:
    document, binary = read_glb(path)
    materials = document.get("materials", [])
    textures = document.get("textures", [])
    primitives_by_material: dict[int, list[dict[str, Any]]] = {}
    for mesh_index, mesh in enumerate(document.get("meshes", [])):
        for primitive_index, primitive in enumerate(mesh.get("primitives", [])):
            material_index = primitive.get("material")
            if material_index is None:
                continue
            primitives_by_material.setdefault(int(material_index), []).append(
                {
                    "mesh_index": mesh_index,
                    "mesh_name": str(mesh.get("name") or f"mesh_{mesh_index}"),
                    "primitive_index": primitive_index,
                    "has_uv0": "TEXCOORD_0" in primitive.get("attributes", {}),
                    "has_normal": "NORMAL" in primitive.get("attributes", {}),
                }
            )
    image_reports: list[dict[str, Any]] = []
    for index, image in enumerate(document.get("images", [])):
        payload = _image_payload(document, binary, index)
        dimensions = None
        if payload:
            try:
                with Image.open(BytesIO(payload)) as opened:
                    dimensions = [int(opened.width), int(opened.height)]
            except Exception:
                dimensions = None
        image_reports.append(
            {
                "index": index,
                "name": image.get("name"),
                "mime_type": image.get("mimeType"),
                "embedded_buffer_view": image.get("bufferView") is not None,
                "external_uri": image.get("uri"),
                "dimensions": dimensions,
            }
        )
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for index, material in enumerate(materials):
        pbr = material.get("pbrMetallicRoughness", {})
        base_ref = pbr.get("baseColorTexture")
        texture_index = int(base_ref["index"]) if isinstance(base_ref, dict) else None
        image_index = None
        if texture_index is not None and 0 <= texture_index < len(textures):
            image_index = textures[texture_index].get("source")
        uses = primitives_by_material.get(index, [])
        uv_ok = all(bool(item["has_uv0"]) for item in uses) if uses else True
        embedded = True
        if image_index is not None:
            embedded = bool(image_reports[int(image_index)]["embedded_buffer_view"])
            if not uv_ok:
                failures.append({"material_index": index, "type": "texture_without_uv"})
            if not embedded:
                failures.append({"material_index": index, "type": "texture_not_embedded"})
        rows.append(
            {
                "index": index,
                "name": str(material.get("name") or f"material_{index}"),
                "primitive_count": len(uses),
                "primitives": uses,
                "uv0_complete": uv_ok,
                "base_color_texture": texture_index,
                "base_color_image": image_index,
                "base_color_color_space": "sRGB_by_glTF_spec" if image_index is not None else None,
                "metallic_factor": float(pbr.get("metallicFactor", 1.0)),
                "roughness_factor": float(pbr.get("roughnessFactor", 1.0)),
                "alpha_mode": str(material.get("alphaMode") or "OPAQUE"),
                "double_sided": bool(material.get("doubleSided", False)),
            }
        )
    return {
        "schema": "scene-v2-p018-glb-material-audit/v1",
        "path": str(path.resolve()),
        "sha256": file_sha256(path),
        "ok": not failures,
        "material_count": len(materials),
        "texture_count": len(textures),
        "image_count": len(image_reports),
        "embedded_image_count": sum(row["embedded_buffer_view"] for row in image_reports),
        "materials": rows,
        "images": image_reports,
        "failures": failures,
    }


def geometry_signature(path: Path, *, quantum_m: float = 1e-5) -> dict[str, Any]:
    """Hash world-space vertices while ignoring materials and texture bytes."""

    import numpy as np
    import trimesh

    loaded = trimesh.load(path, force="scene", process=False)
    if not isinstance(loaded, trimesh.Scene) or not loaded.geometry:
        raise MaterialContractError(f"GLB contains no scene geometry: {path}")
    vertices: list[np.ndarray] = []
    face_count = 0
    for node_name in sorted(loaded.graph.nodes_geometry):
        transform, geometry_name = loaded.graph[node_name]
        mesh = loaded.geometry[geometry_name]
        points = trimesh.transform_points(np.asarray(mesh.vertices), transform)
        vertices.append(points)
        face_count += int(len(mesh.faces))
    combined = np.concatenate(vertices, axis=0)
    quantized = np.rint(combined / float(quantum_m)).astype(np.int64)
    order = np.lexsort((quantized[:, 2], quantized[:, 1], quantized[:, 0]))
    canonical = np.ascontiguousarray(quantized[order])
    return {
        "schema": "scene-v2-material-independent-geometry-signature/v1",
        "sha256": hashlib.sha256(canonical.tobytes()).hexdigest(),
        "quantum_m": float(quantum_m),
        "geometry_count": len(loaded.geometry),
        "node_geometry_count": len(loaded.graph.nodes_geometry),
        "vertex_count": int(len(combined)),
        "face_count": face_count,
        "bounds": np.round(loaded.bounds, 6).tolist(),
    }


def geometry_equivalence(
    source_path: Path,
    target_path: Path,
    *,
    maximum_surface_delta_m: float = 1e-6,
) -> dict[str, Any]:
    """Compare exported surfaces while tolerating sub-micron float encoding.

    glTF exporters may split a vertex at a new material/UV corner, so raw
    accessor vertex multiplicity is not a geometric invariant.  This gate
    keeps face count, world bounds, node/mesh counts and a symmetric all-point
    nearest-surface distance.  It reports the representational split instead
    of silently treating it as added geometry.
    """

    import numpy as np
    import trimesh
    from scipy.spatial import cKDTree

    def points_and_counts(path: Path) -> tuple[np.ndarray, dict[str, Any]]:
        scene = trimesh.load(path, force="scene", process=False)
        if not isinstance(scene, trimesh.Scene) or not scene.geometry:
            raise MaterialContractError(f"GLB contains no scene geometry: {path}")
        points = []
        face_count = 0
        raw_vertex_count = 0
        for node_name in sorted(scene.graph.nodes_geometry):
            transform, geometry_name = scene.graph[node_name]
            mesh = scene.geometry[geometry_name]
            transformed = trimesh.transform_points(np.asarray(mesh.vertices), transform)
            points.append(transformed)
            face_count += int(len(mesh.faces))
            raw_vertex_count += int(len(mesh.vertices))
        combined = np.concatenate(points, axis=0)
        # Eight decimals is much finer than the one-micron hard threshold and
        # only removes duplicate accessor corners created by material splits.
        unique = np.unique(np.round(combined, 8), axis=0)
        return unique, {
            "geometry_count": len(scene.geometry),
            "node_geometry_count": len(scene.graph.nodes_geometry),
            "raw_vertex_count": raw_vertex_count,
            "unique_world_vertex_count": int(len(unique)),
            "face_count": face_count,
            "bounds": np.asarray(scene.bounds, dtype=np.float64),
        }

    source, source_counts = points_and_counts(source_path)
    target, target_counts = points_and_counts(target_path)
    source_to_target = cKDTree(target).query(source, k=1, workers=-1)[0]
    target_to_source = cKDTree(source).query(target, k=1, workers=-1)[0]
    maximum_delta = float(max(source_to_target.max(), target_to_source.max()))
    counts_ok = all(
        source_counts[key] == target_counts[key]
        for key in ("geometry_count", "node_geometry_count", "face_count")
    )
    bounds_delta = float(
        np.max(np.abs(source_counts["bounds"] - target_counts["bounds"]))
    )
    ok = bool(
        counts_ok
        and bounds_delta <= maximum_surface_delta_m
        and maximum_delta <= maximum_surface_delta_m
    )
    return {
        "schema": "scene-v2-p018-geometry-surface-equivalence/v1",
        "ok": ok,
        "maximum_allowed_surface_delta_m": float(maximum_surface_delta_m),
        "maximum_symmetric_world_vertex_delta_m": maximum_delta,
        "p99_source_to_target_delta_m": float(np.percentile(source_to_target, 99)),
        "p99_target_to_source_delta_m": float(np.percentile(target_to_source, 99)),
        "maximum_bounds_delta_m": bounds_delta,
        "face_mesh_node_counts_equal": counts_ok,
        "source": {
            **{key: value for key, value in source_counts.items() if key != "bounds"},
            "bounds": source_counts["bounds"].tolist(),
        },
        "target": {
            **{key: value for key, value in target_counts.items() if key != "bounds"},
            "bounds": target_counts["bounds"].tolist(),
        },
        "raw_vertex_count_difference_is_attribute_corner_splitting": int(
            target_counts["raw_vertex_count"] - source_counts["raw_vertex_count"]
        ),
    }


def percentile(values: Iterable[float], q: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    position = max(0.0, min(1.0, q)) * (len(ordered) - 1)
    low = int(math.floor(position))
    high = int(math.ceil(position))
    if low == high:
        return ordered[low]
    fraction = position - low
    return ordered[low] * (1.0 - fraction) + ordered[high] * fraction
