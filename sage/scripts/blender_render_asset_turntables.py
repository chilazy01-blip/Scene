#!/usr/bin/env python3
"""Render auditable local-axis views for selected SAGE assets."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils.bvhtree import BVHTree
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from blender_mesh_bounds import mesh_bbox_world


TARGET_TYPES = {"MESH", "CURVE", "SURFACE", "META", "FONT"}
STANDARD_VIEW_SPECS = {
    "+x": ((2.8, 0.0, 1.25), (0.0, 0.0, 0.18)),
    "-x": ((-2.8, 0.0, 1.25), (0.0, 0.0, 0.18)),
    "+y": ((0.0, 2.8, 1.25), (0.0, 0.0, 0.18)),
    "-y": ((0.0, -2.8, 1.25), (0.0, 0.0, 0.18)),
}

# These opt-in cameras deliberately sit below the usual product-photography
# eye line.  They are evidence cameras, not attractive showcase cameras: the
# low views expose fused plinths while the under views make the complete lower
# surface inspectable.  The default profile remains the historical four-view
# contract so existing certificates are not silently reinterpreted.
LOW_UNDER_VIEW_SPECS = {
    "low_+x": ((2.8, 0.0, -0.12), (0.0, 0.0, 0.02)),
    "low_-x": ((-2.8, 0.0, -0.12), (0.0, 0.0, 0.02)),
    "low_+y": ((0.0, 2.8, -0.12), (0.0, 0.0, 0.02)),
    "low_-y": ((0.0, -2.8, -0.12), (0.0, 0.0, 0.02)),
    "under_+x": ((1.7, 0.0, -2.25), (0.0, 0.0, -0.12)),
    "under_-x": ((-1.7, 0.0, -2.25), (0.0, 0.0, -0.12)),
    "under_+y": ((0.0, 1.7, -2.25), (0.0, 0.0, -0.12)),
    "under_-y": ((0.0, -1.7, -2.25), (0.0, 0.0, -0.12)),
}


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []
    parser = argparse.ArgumentParser(description="Render asset turntable views.")
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--asset-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--object-ids", required=True)
    parser.add_argument("--resolution", type=int, default=520)
    parser.add_argument("--engine", choices=("eevee", "cycles_cpu"), default="eevee")
    parser.add_argument("--transparent", action="store_true")
    parser.add_argument("--fit-requested-dimensions", action="store_true")
    parser.add_argument(
        "--geometry-evidence",
        action="store_true",
        help="Write low-resolution face/depth/normal evidence aligned with every RGB view.",
    )
    parser.add_argument("--evidence-resolution", type=int, default=128)
    parser.add_argument(
        "--view-profile",
        choices=("standard", "low_under", "all"),
        default="standard",
        help="Select the historical cardinal views, diagnostic low/under views, or both.",
    )
    return parser.parse_args(argv)


def clear_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def renderable_objects() -> list[bpy.types.Object]:
    return [obj for obj in bpy.context.scene.objects if obj.type in TARGET_TYPES]


def layered_footprint_metrics(objects: list[bpy.types.Object]) -> dict:
    points = [
        obj.matrix_world @ vertex.co
        for obj in objects
        if obj.type in TARGET_TYPES
        for vertex in obj.data.vertices
    ]
    if not points:
        return {"evaluated": False, "reason": "no_mesh_vertices"}
    z_min = min(float(point.z) for point in points)
    z_max = max(float(point.z) for point in points)
    height = max(z_max - z_min, 1e-8)
    lower = [point for point in points if float(point.z) <= z_min + 0.30 * height]
    upper = [point for point in points if float(point.z) >= z_min + 0.45 * height]

    def area(rows: list[Vector]) -> float:
        if len(rows) < 4:
            return 0.0
        return max(0.0, max(v.x for v in rows) - min(v.x for v in rows)) * max(
            0.0, max(v.y for v in rows) - min(v.y for v in rows)
        )

    lower_area = float(area(lower))
    upper_area = float(area(upper))
    ratio = lower_area / max(upper_area, 1e-8)
    return {
        "evaluated": bool(lower_area > 0.0 and upper_area > 0.0),
        "lower_height_fraction_maximum": 0.30,
        "upper_height_fraction_minimum": 0.45,
        "lower_footprint_area": round(lower_area, 6),
        "upper_footprint_area": round(upper_area, 6),
        "lower_to_upper_footprint_area_ratio": round(ratio, 6),
    }


def look_at(camera_obj: bpy.types.Object, target: Vector) -> None:
    direction = target - camera_obj.location
    camera_obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def setup_world(*, style_audit: bool = False) -> None:
    world = bpy.data.worlds.new("TurntableWorld")
    world.use_nodes = True
    bpy.context.scene.world = world
    bg = world.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (0.965, 0.96, 0.94, 1.0)
    bg.inputs[1].default_value = 0.35 if style_audit else 0.85


def add_area_light(name: str, location: tuple[float, float, float], energy: float, size: float) -> None:
    light_data = bpy.data.lights.new(name=name, type="AREA")
    light_data.energy = energy
    light_data.size = size
    obj = bpy.data.objects.new(name, light_data)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location
    look_at(obj, Vector((0.0, 0.0, 0.0)))


def setup_lighting(*, style_audit: bool = False) -> None:
    multiplier = 0.32 if style_audit else 1.0
    add_area_light("KeyLight", (3.2, -3.5, 4.0), 4200.0 * multiplier, 4.5)
    add_area_light("FillLight", (-3.2, 3.0, 3.2), 1800.0 * multiplier, 5.5)
    add_area_light("TopLight", (0.0, 0.0, 4.8), 1200.0 * multiplier, 5.0)


def setup_render(output: Path, resolution: int, *, transparent: bool = False, engine: str = "eevee") -> None:
    scene = bpy.context.scene
    if engine == "cycles_cpu":
        scene.render.engine = "CYCLES"
        scene.cycles.device = "CPU"
        scene.cycles.samples = 32
        scene.cycles.use_denoising = True
    else:
        try:
            scene.render.engine = "BLENDER_EEVEE_NEXT"
        except Exception:
            scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = resolution
    scene.render.resolution_y = resolution
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA" if transparent else "RGB"
    scene.render.film_transparent = bool(transparent)
    if transparent:
        scene.view_settings.look = "AgX - Medium Low Contrast"
    scene.render.filepath = str(output)
    if hasattr(scene, "eevee") and hasattr(scene.eevee, "taa_render_samples"):
        scene.eevee.taa_render_samples = 32


def add_camera(name: str, location: tuple[float, float, float], target: tuple[float, float, float]) -> bpy.types.Object:
    cam_data = bpy.data.cameras.new(name)
    cam_obj = bpy.data.objects.new(name, cam_data)
    bpy.context.scene.collection.objects.link(cam_obj)
    cam_obj.location = location
    look_at(cam_obj, Vector(target))
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = 1.85
    bpy.context.scene.camera = cam_obj
    return cam_obj


def fit_orthographic_camera(
    camera: bpy.types.Object,
    objects: list[bpy.types.Object],
    *,
    margin: float = 1.18,
) -> float:
    """Fit every cardinal view independently so thin/tall assets are not clipped.

    The old fixed 1.85 scale could crop a tall object in a side view because the
    camera is elevated.  That made an evidence-capture defect look like broken
    geometry.  Camera-local bounds make the diagnostic view category agnostic.
    """

    bpy.context.view_layer.update()
    min_v, max_v = mesh_bbox_world(objects)
    world_corners = [
        Vector((x, y, z))
        for x in (float(min_v.x), float(max_v.x))
        for y in (float(min_v.y), float(max_v.y))
        for z in (float(min_v.z), float(max_v.z))
    ]
    inverse = camera.matrix_world.inverted()
    local = [inverse @ corner for corner in world_corners]
    # Include off-axis displacement as well as span.  VIEW_SPECS intentionally
    # looks slightly upward, so a span-only fit can still crop the lower edge.
    half_span = max(
        max(abs(float(item.x)) for item in local),
        max(abs(float(item.y)) for item in local),
        1e-6,
    )
    # Assets are normalized to a maximum world extent of 1.35.  A conservative
    # floor protects against stale/imported camera matrices and the elevated
    # cardinal view; the geometric fit can still request more room.
    scale = max(2.15, 2.0 * half_span * max(1.05, float(margin)))
    camera.data.ortho_scale = scale
    return scale


def axis_to_z_matrix(axis_to_z: int, axis_sign: float = 1.0) -> Matrix:
    sign = -1.0 if float(axis_sign) < 0.0 else 1.0
    if axis_to_z == 0:
        if sign < 0.0:
            return Matrix(((0.0, 0.0, 1.0, 0.0), (0.0, 1.0, 0.0, 0.0), (-1.0, 0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0)))
        return Matrix(((0.0, 0.0, -1.0, 0.0), (0.0, 1.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0)))
    if axis_to_z == 1:
        if sign < 0.0:
            return Matrix(((1.0, 0.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0), (0.0, -1.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0)))
        return Matrix(((1.0, 0.0, 0.0, 0.0), (0.0, 0.0, -1.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0)))
    return Matrix.Identity(4)


def normalize_asset(
    objects: list[bpy.types.Object],
    obj_plan: dict,
    *,
    fit_requested_dimensions: bool = False,
) -> dict:
    mesh_objects = [obj for obj in objects if obj.type in TARGET_TYPES]
    if not mesh_objects:
        raise RuntimeError("Imported asset contains no renderable objects.")
    axis_matrix = axis_to_z_matrix(
        int(obj_plan.get("asset_axis_to_z", 2)),
        float(obj_plan.get("asset_axis_to_z_sign", 1.0) or 1.0),
    )
    local_yaw_degrees = float(
        obj_plan.get("asset_local_yaw_offset_degrees", 0.0) or 0.0
    )
    local_yaw_matrix = Matrix.Rotation(
        math.radians(local_yaw_degrees), 4, "Z"
    )
    alignment_matrix = local_yaw_matrix @ axis_matrix
    root = bpy.data.objects.new("AssetRoot", None)
    bpy.context.scene.collection.objects.link(root)
    imported_set = set(objects)
    root_candidates = [obj for obj in objects if obj.parent not in imported_set]
    for obj in root_candidates:
        world = obj.matrix_world.copy()
        obj.parent = root
        obj.matrix_world = world
    root.matrix_world = alignment_matrix
    bpy.context.view_layer.update()
    min_v, max_v = mesh_bbox_world(mesh_objects)
    center = (min_v + max_v) * 0.5
    extents = max_v - min_v
    raw_extents = [float(extents.x), float(extents.y), float(extents.z)]
    requested = obj_plan.get("requested_dimensions") or obj_plan.get("dimensions")
    requested_xyz = None
    axis_scales = [1.0, 1.0, 1.0]
    if fit_requested_dimensions and isinstance(requested, dict):
        requested_xyz = [
            float(requested.get("width", 0.0) or 0.0),
            float(requested.get("length", 0.0) or 0.0),
            float(requested.get("height", 0.0) or 0.0),
        ]
        if all(value > 0.0 for value in requested_xyz):
            axis_scales = [
                requested_xyz[index] / max(raw_extents[index], 1e-6)
                for index in range(3)
            ]
    fitted_extents = [raw_extents[index] * axis_scales[index] for index in range(3)]
    max_extent = max(*fitted_extents, 1e-6)
    uniform_scale = 1.35 / max_extent
    root.matrix_world = (
        Matrix.Diagonal(
            (
                uniform_scale * axis_scales[0],
                uniform_scale * axis_scales[1],
                uniform_scale * axis_scales[2],
                1.0,
            )
        )
        @ Matrix.Translation((-center.x, -center.y, -center.z))
        @ alignment_matrix
    )
    bpy.context.view_layer.update()
    normalized_min, normalized_max = mesh_bbox_world(mesh_objects)
    normalized_extents = normalized_max - normalized_min
    layered_footprint = layered_footprint_metrics(mesh_objects)
    positive_scales = [value for value in axis_scales if value > 0.0]
    anisotropy = max(positive_scales) / max(min(positive_scales), 1e-6)
    report = {
        "object_id": obj_plan.get("id"),
        "axis_to_z": int(obj_plan.get("asset_axis_to_z", 2)),
        "asset_local_yaw_offset_degrees": round(local_yaw_degrees, 6),
        "raw_aligned_extents": [round(value, 6) for value in raw_extents],
        "requested_dimensions_xyz": requested_xyz,
        "fit_requested_dimensions": bool(
            fit_requested_dimensions and requested_xyz and all(value > 0.0 for value in requested_xyz)
        ),
        "axis_scale_factors": [round(value, 6) for value in axis_scales],
        "axis_scale_anisotropy": round(anisotropy, 6),
        "normalized_extents": [
            round(float(normalized_extents.x), 6),
            round(float(normalized_extents.y), 6),
            round(float(normalized_extents.z), 6),
        ],
        "layered_footprint": layered_footprint,
        "root_matrix_world": [
            [round(float(root.matrix_world[row][col]), 9) for col in range(4)]
            for row in range(4)
        ],
    }
    print(json.dumps(report), flush=True)
    return report


def _geometry_evidence_index(mesh_objects: list[bpy.types.Object], object_dir: Path) -> dict:
    """Build one world-space BVH while preserving original object/polygon identities."""

    vertices: list[Vector] = []
    polygons: list[list[int]] = []
    object_indices: list[int] = []
    polygon_indices: list[int] = []
    centroids: list[tuple[float, float, float]] = []
    centroid_z: list[float] = []
    maximum_z: list[float] = []
    object_names: list[str] = []
    for object_index, obj in enumerate(mesh_objects):
        if obj.type != "MESH":
            continue
        object_names.append(str(obj.name))
        matrix = obj.matrix_world.copy()
        for polygon in obj.data.polygons:
            world = [matrix @ obj.data.vertices[index].co for index in polygon.vertices]
            if len(world) < 3:
                continue
            offset = len(vertices)
            vertices.extend(world)
            polygons.append(list(range(offset, offset + len(world))))
            object_indices.append(object_index)
            polygon_indices.append(int(polygon.index))
            center = sum(world, Vector()) / float(len(world))
            centroids.append((float(center.x), float(center.y), float(center.z)))
            centroid_z.append(float(center.z))
            maximum_z.append(max(float(point.z) for point in world))
    if not polygons:
        raise RuntimeError("geometry evidence requires at least one mesh polygon")
    bvh = BVHTree.FromPolygons(vertices, polygons, all_triangles=False, epsilon=0.0)
    z_min = min(float(point.z) for point in vertices)
    z_max = max(float(point.z) for point in vertices)
    face_table_path = object_dir / "geometry_face_table.npz"
    np.savez_compressed(
        face_table_path,
        object_index=np.asarray(object_indices, dtype=np.int32),
        polygon_index=np.asarray(polygon_indices, dtype=np.int32),
        centroid_xyz=np.asarray(centroids, dtype=np.float32),
        centroid_z=np.asarray(centroid_z, dtype=np.float32),
        maximum_z=np.asarray(maximum_z, dtype=np.float32),
    )
    return {
        "bvh": bvh,
        "face_table_path": str(face_table_path),
        "object_names": object_names,
        "face_count": len(polygons),
        "normalized_z_min": z_min,
        "normalized_z_max": z_max,
    }


def _matrix_rows(matrix: Matrix) -> list[list[float]]:
    return [
        [round(float(matrix[row][col]), 9) for col in range(4)]
        for row in range(4)
    ]


def _rasterize_geometry_evidence(
    camera: bpy.types.Object,
    evidence_index: dict,
    output_path: Path,
    resolution: int,
) -> dict:
    """Ray-cast an orthographic face/depth/normal buffer for auditable localization."""

    size = max(32, int(resolution))
    face_index = np.full((size, size), -1, dtype=np.int32)
    depth = np.full((size, size), np.nan, dtype=np.float32)
    normals = np.zeros((size, size, 3), dtype=np.float32)
    matrix = camera.matrix_world.copy()
    direction = (matrix.to_3x3() @ Vector((0.0, 0.0, -1.0))).normalized()
    scale = float(camera.data.ortho_scale)
    aspect = 1.0
    bvh: BVHTree = evidence_index["bvh"]
    for row in range(size):
        local_y = (0.5 - (row + 0.5) / size) * scale
        for col in range(size):
            local_x = ((col + 0.5) / size - 0.5) * scale * aspect
            origin = matrix @ Vector((local_x, local_y, 0.0))
            location, normal, index, distance = bvh.ray_cast(origin, direction)
            if index is None or location is None:
                continue
            face_index[row, col] = int(index)
            depth[row, col] = float(distance)
            normals[row, col] = (float(normal.x), float(normal.y), float(normal.z))
    np.savez_compressed(
        output_path,
        face_index=face_index,
        depth=depth,
        normal=normals,
    )
    return {
        "path": str(output_path),
        "resolution": [size, size],
        "hit_pixel_count": int(np.count_nonzero(face_index >= 0)),
        "camera_type": str(camera.data.type),
        "orthographic_scale": round(scale, 9),
        "camera_matrix_world": _matrix_rows(matrix),
    }


def render_asset(
    asset_path: Path,
    obj_plan: dict,
    output_dir: Path,
    resolution: int,
    *,
    transparent: bool = False,
    fit_requested_dimensions: bool = False,
    geometry_evidence: bool = False,
    evidence_resolution: int = 128,
    view_specs: dict | None = None,
    engine: str = "eevee",
) -> tuple[dict[str, str], dict, dict]:
    object_id = str(obj_plan["id"])
    clear_scene()
    bpy.ops.import_scene.gltf(filepath=str(asset_path))
    imported = list(bpy.context.scene.objects)
    normalization = normalize_asset(
        imported,
        obj_plan,
        fit_requested_dimensions=fit_requested_dimensions,
    )
    mesh_objects = [obj for obj in imported if obj.type in TARGET_TYPES]
    setup_world(style_audit=transparent)
    setup_lighting(style_audit=transparent)
    paths: dict[str, str] = {}
    object_dir = output_dir / object_id
    object_dir.mkdir(parents=True, exist_ok=True)
    evidence: dict = {}
    evidence_index = (
        _geometry_evidence_index(
            [obj for obj in mesh_objects if obj.type == "MESH"], object_dir
        )
        if geometry_evidence
        else None
    )
    if evidence_index is not None:
        evidence = {
            "schema": "scene_detail_geometry_evidence_v1",
            "face_table_path": evidence_index["face_table_path"],
            "object_names": evidence_index["object_names"],
            "face_count": evidence_index["face_count"],
            "normalized_z_min": round(float(evidence_index["normalized_z_min"]), 9),
            "normalized_z_max": round(float(evidence_index["normalized_z_max"]), 9),
            "views": {},
        }
    selected_view_specs = view_specs or STANDARD_VIEW_SPECS
    for axis, (location, target) in selected_view_specs.items():
        camera = add_camera(f"Camera_{axis}", location, target)
        fit_orthographic_camera(camera, mesh_objects)
        output = object_dir / f"{axis.replace('+', 'plus_').replace('-', 'minus_')}.png"
        setup_render(output, resolution, transparent=transparent, engine=engine)
        bpy.ops.render.render(write_still=True)
        paths[axis] = str(output)
        if evidence_index is not None:
            evidence_output = object_dir / (
                f"{axis.replace('+', 'plus_').replace('-', 'minus_')}_geometry.npz"
            )
            evidence["views"][axis] = _rasterize_geometry_evidence(
                camera,
                evidence_index,
                evidence_output,
                evidence_resolution,
            )
    return paths, normalization, evidence


def main() -> None:
    args = parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    by_id = {
        str(obj.get("id")): obj
        for obj in plan.get("objects", [])
        if isinstance(obj, dict)
    }
    requested = [item.strip() for item in args.object_ids.split(",") if item.strip()]
    object_ids = [object_id for object_id in requested if object_id in by_id]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema": "scene_asset_turntable_manifest_v2",
        "view_profile": str(args.view_profile),
        "views": {},
        "normalization": {},
        "geometry_evidence": {},
        "missing": [],
    }
    view_specs = {
        "standard": STANDARD_VIEW_SPECS,
        "low_under": LOW_UNDER_VIEW_SPECS,
        "all": {**STANDARD_VIEW_SPECS, **LOW_UNDER_VIEW_SPECS},
    }[str(args.view_profile)]
    for object_id in object_ids:
        asset_path = args.asset_dir / f"{object_id}.glb"
        if not asset_path.exists():
            manifest["missing"].append(object_id)
            continue
        paths, normalization, evidence = render_asset(
            asset_path,
            by_id[object_id],
            args.output_dir,
            args.resolution,
            transparent=bool(args.transparent),
            fit_requested_dimensions=bool(args.fit_requested_dimensions),
            geometry_evidence=bool(args.geometry_evidence),
            evidence_resolution=int(args.evidence_resolution),
            view_specs=view_specs,
            engine=args.engine,
        )
        manifest["views"][object_id] = paths
        manifest["normalization"][object_id] = normalization
        if evidence:
            manifest["geometry_evidence"][object_id] = evidence
    (args.output_dir / "asset_turntable_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2), flush=True)


if __name__ == "__main__":
    main()
