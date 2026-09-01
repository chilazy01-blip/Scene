#!/usr/bin/env python3
"""Render SAGE scene and asset diagnostic views from Blender.

Run with:
  blender --background --python scripts/blender_render_sage_diagnostics.py -- ...
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import traceback
from itertools import product
from pathlib import Path

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector


TARGET_TYPES = {"MESH", "CURVE", "SURFACE", "META", "FONT"}


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []
    parser = argparse.ArgumentParser(description="Render visual diagnostics for a SAGE-style GLB scene.")
    parser.add_argument("--scene-glb", required=True, type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--asset-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--resolution", type=int, default=900)
    parser.add_argument("--skip-assets", action="store_true")
    parser.add_argument(
        "--qa-passes",
        action="store_true",
        help="Write a visible object-index image plus a normalized depth PNG for each scene view.",
    )
    parser.add_argument(
        "--allow-non-z-up",
        action="store_true",
        help="Render even when a named floor is not horizontal in Blender Z-up coordinates.",
    )
    return parser.parse_args(argv)


def clear_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def renderable_objects() -> list[bpy.types.Object]:
    return [obj for obj in bpy.context.scene.objects if obj.type in TARGET_TYPES]


def mesh_bbox_world(objects: list[bpy.types.Object]) -> tuple[Vector, Vector]:
    corners: list[Vector] = []
    for obj in objects:
        if obj.type not in TARGET_TYPES:
            continue
        for corner in obj.bound_box:
            corners.append(obj.matrix_world @ Vector(corner))
    if not corners:
        raise RuntimeError("No renderable geometry found.")
    min_v = Vector((min(c.x for c in corners), min(c.y for c in corners), min(c.z for c in corners)))
    max_v = Vector((max(c.x for c in corners), max(c.y for c in corners), max(c.z for c in corners)))
    return min_v, max_v


def look_at(camera_obj: bpy.types.Object, target: Vector) -> None:
    direction = target - camera_obj.location
    camera_obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def setup_world() -> None:
    world = bpy.data.worlds.new("DiagnosticWorld")
    world.use_nodes = True
    bpy.context.scene.world = world
    bg = world.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (0.16, 0.18, 0.22, 1.0)
    bg.inputs[1].default_value = 0.22


def add_area_light(name: str, location: tuple[float, float, float], energy: float, size: float) -> None:
    light_data = bpy.data.lights.new(name=name, type="AREA")
    light_data.energy = energy
    light_data.size = size
    light_data.size_y = size
    light_obj = bpy.data.objects.new(name, light_data)
    bpy.context.scene.collection.objects.link(light_obj)
    light_obj.location = location
    look_at(light_obj, Vector((0.0, 0.0, 0.0)))


def setup_lighting() -> None:
    add_area_light("KeyLight", (3.0, -4.0, 4.2), 650.0, 5.0)
    add_area_light("FillLight", (-4.0, 2.5, 3.0), 250.0, 6.0)
    add_area_light("TopLight", (0.0, 0.0, 5.0), 350.0, 5.5)


def setup_render(output: Path, resolution: int) -> None:
    scene = bpy.context.scene
    try:
        scene.render.engine = "BLENDER_EEVEE_NEXT"
    except Exception:
        scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = resolution
    scene.render.resolution_y = resolution
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(output)
    try:
        scene.view_settings.look = "AgX - Medium High Contrast"
    except TypeError:
        pass
    if hasattr(scene, "eevee"):
        if hasattr(scene.eevee, "taa_render_samples"):
            scene.eevee.taa_render_samples = 32
        if hasattr(scene.eevee, "use_gtao"):
            scene.eevee.use_gtao = True


def add_camera(name: str, location: tuple[float, float, float], target: tuple[float, float, float]) -> bpy.types.Object:
    cam_data = bpy.data.cameras.new(name)
    cam_obj = bpy.data.objects.new(name, cam_data)
    bpy.context.scene.collection.objects.link(cam_obj)
    cam_obj.location = location
    look_at(cam_obj, Vector(target))
    bpy.context.scene.camera = cam_obj
    return cam_obj


def render_current(output: Path, resolution: int) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    setup_render(output, resolution)
    bpy.ops.render.render(write_still=True)


def _planned_object_rows(plan: dict) -> list[dict]:
    return [
        obj
        for obj in plan.get("objects", [])
        if isinstance(obj, dict) and obj.get("id")
    ]


def _objects_for_plan_id(object_id: str) -> list[bpy.types.Object]:
    prefix = str(object_id).lower() + "_"
    return [
        obj
        for obj in renderable_objects()
        if obj.name.lower() == str(object_id).lower()
        or obj.name.lower().startswith(prefix)
        or (
            getattr(obj, "data", None) is not None
            and str(obj.data.name).lower().startswith(prefix)
        )
    ]


def _projected_bbox(
    objects: list[bpy.types.Object], camera: bpy.types.Object, resolution: int
) -> dict:
    if not objects:
        return {"matched_mesh_count": 0, "bbox_normalized": None, "bbox_pixels": None}
    min_v, max_v = mesh_bbox_world(objects)
    coordinates = [
        world_to_camera_view(
            bpy.context.scene,
            camera,
            Vector((x, y, z)),
        )
        for x, y, z in product(
            (float(min_v.x), float(max_v.x)),
            (float(min_v.y), float(max_v.y)),
            (float(min_v.z), float(max_v.z)),
        )
    ]
    xs = [float(item.x) for item in coordinates]
    ys = [float(item.y) for item in coordinates]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    clipped = (
        max(0.0, min(1.0, x0)),
        max(0.0, min(1.0, y0)),
        max(0.0, min(1.0, x1)),
        max(0.0, min(1.0, y1)),
    )
    return {
        "matched_mesh_count": len(objects),
        "bbox_normalized": [x0, y0, x1, y1],
        "bbox_pixels": [
            int(round(clipped[0] * resolution)),
            int(round((1.0 - clipped[3]) * resolution)),
            int(round(clipped[2] * resolution)),
            int(round((1.0 - clipped[1]) * resolution)),
        ],
        "projected_bbox_area_pixels": int(
            round(
                max(0.0, clipped[2] - clipped[0])
                * max(0.0, clipped[3] - clipped[1])
                * resolution
                * resolution
            )
        ),
        "bbox_inside_frame": bool(x0 >= 0.0 and y0 >= 0.0 and x1 <= 1.0 and y1 <= 1.0),
    }


def render_object_index_pass(output: Path, plan: dict, resolution: int) -> None:
    """Render an occlusion-aware grayscale object-id image.

    Blender 4.3 exposes the Eevee IndexOB socket but does not consistently
    execute a File Output branch connected to it in background mode.  An
    emission-material override is deterministic, requires one extra render per
    view, and measures the same final-camera occlusion without rendering once
    per object.  Emission avoids Workbench's theme/background and display-color
    transforms, which otherwise make numeric ids ambiguous.
    """

    scene = bpy.context.scene
    original_view_transform = scene.view_settings.view_transform
    original_look = scene.view_settings.look
    original_color_mode = scene.render.image_settings.color_mode
    original_color_depth = scene.render.image_settings.color_depth
    background = None
    original_background_color = None
    original_background_strength = None
    if scene.world and scene.world.use_nodes:
        background = scene.world.node_tree.nodes.get("Background")
        if background is not None:
            original_background_color = tuple(background.inputs[0].default_value)
            original_background_strength = float(background.inputs[1].default_value)
    planned_rows = _planned_object_rows(plan)
    denominator = max(1, len(planned_rows))
    object_indices = {obj.name: 0 for obj in renderable_objects()}
    for index, row in enumerate(planned_rows, start=1):
        for obj in _objects_for_plan_id(str(row["id"])):
            object_indices[obj.name] = index

    index_materials: dict[int, bpy.types.Material] = {}
    for index in range(denominator + 1):
        value = float(index) / float(denominator)
        material = bpy.data.materials.new(f"DiagnosticObjectIndex_{index:03d}")
        material.use_nodes = True
        nodes = material.node_tree.nodes
        nodes.clear()
        output_node = nodes.new("ShaderNodeOutputMaterial")
        emission = nodes.new("ShaderNodeEmission")
        emission.inputs["Color"].default_value = (value, value, value, 1.0)
        emission.inputs["Strength"].default_value = 1.0
        material.node_tree.links.new(emission.outputs["Emission"], output_node.inputs["Surface"])
        index_materials[index] = material

    original_materials: dict[str, list[bpy.types.Material | None]] = {}
    for obj in renderable_objects():
        materials = getattr(getattr(obj, "data", None), "materials", None)
        if materials is None:
            continue
        original_materials[obj.name] = list(materials)
        materials.clear()
        materials.append(index_materials[object_indices[obj.name]])

    scene.use_nodes = False
    setup_render(output, resolution)
    scene.use_nodes = False
    scene.render.image_settings.color_mode = "BW"
    scene.render.image_settings.color_depth = "8"
    if background is not None:
        background.inputs[0].default_value = (0.0, 0.0, 0.0, 1.0)
        background.inputs[1].default_value = 0.0
    try:
        scene.view_settings.view_transform = "Raw"
    except (TypeError, ValueError):
        scene.view_settings.view_transform = "Standard"
    try:
        scene.view_settings.look = "None"
    except (TypeError, ValueError):
        pass
    bpy.ops.render.render(write_still=True)

    for obj in renderable_objects():
        if obj.name not in original_materials:
            continue
        materials = obj.data.materials
        materials.clear()
        for material in original_materials[obj.name]:
            materials.append(material)
    for material in index_materials.values():
        bpy.data.materials.remove(material)
    if background is not None:
        background.inputs[0].default_value = original_background_color
        background.inputs[1].default_value = original_background_strength
    scene.view_settings.view_transform = original_view_transform
    scene.view_settings.look = original_look
    scene.render.image_settings.color_mode = original_color_mode
    scene.render.image_settings.color_depth = original_color_depth


def configure_qa_passes(
    *,
    view_name: str,
    output_dir: Path,
    plan: dict,
    camera: bpy.types.Object,
    resolution: int,
) -> dict:
    scene = bpy.context.scene
    try:
        scene.render.engine = "BLENDER_EEVEE_NEXT"
    except Exception:
        scene.render.engine = "BLENDER_EEVEE"
    scene.use_nodes = True
    view_layer = scene.view_layers[0]
    view_layer.use_pass_object_index = True
    view_layer.use_pass_z = True
    tree = scene.node_tree
    tree.nodes.clear()
    render_layers = tree.nodes.new("CompositorNodeRLayers")
    render_layers.layer = view_layer.name
    composite = tree.nodes.new("CompositorNodeComposite")
    tree.links.new(render_layers.outputs["Image"], composite.inputs["Image"])

    qa_root = output_dir / "qa_passes" / view_name
    qa_root.mkdir(parents=True, exist_ok=True)
    object_rows: dict[str, dict] = {}
    planned_rows = _planned_object_rows(plan)
    bpy.context.view_layer.update()
    for index, row in enumerate(planned_rows, start=1):
        object_id = str(row["id"])
        matched = _objects_for_plan_id(object_id)
        for obj in matched:
            obj.pass_index = index
        safe_id = "".join(
            character if character.isalnum() or character in "_-" else "_"
            for character in object_id
        )
        object_rows[object_id] = {
            "required": bool(row.get("required", True)),
            "category": str(row.get("category") or ""),
            "pass_index": index,
            "object_index_path": str(qa_root / "object_index.png"),
            "object_index_denominator": max(1, len(planned_rows)),
            "object_index_max_pixel_value": 255,
            "object_index_transfer": "linear",
            "projection": _projected_bbox(matched, camera, resolution),
        }

    map_range = tree.nodes.new("CompositorNodeMapRange")
    map_range.inputs[1].default_value = float(camera.data.clip_start)
    map_range.inputs[2].default_value = float(camera.data.clip_end)
    map_range.inputs[3].default_value = 1.0
    map_range.inputs[4].default_value = 0.0
    map_range.use_clamp = True
    depth_socket = next(
        (socket for socket in render_layers.outputs if socket.name == "Depth"),
        None,
    )
    if depth_socket is None:
        raise RuntimeError("Blender compositor did not expose the depth pass")
    tree.links.new(depth_socket, map_range.inputs[0])
    depth_output = tree.nodes.new("CompositorNodeOutputFile")
    depth_output.base_path = str(qa_root)
    depth_output.format.file_format = "PNG"
    depth_output.format.color_mode = "BW"
    depth_output.format.color_depth = "16"
    depth_output.file_slots[0].path = "depth_"
    tree.links.new(map_range.outputs[0], depth_output.inputs[0])
    return {
        "view": view_name,
        "depth_path": str(qa_root / "depth_0001.png"),
        "object_index_path": str(qa_root / "object_index.png"),
        "object_index_denominator": max(1, len(planned_rows)),
        "object_index_max_pixel_value": 255,
        "object_index_transfer": "linear",
        "camera": {
            "name": camera.name,
            "clip_start": float(camera.data.clip_start),
            "clip_end": float(camera.data.clip_end),
        },
        "objects": object_rows,
    }


def set_material_alpha_mode() -> None:
    for mat in bpy.data.materials:
        mat.blend_method = "BLEND"
        mat.use_screen_refraction = False


def add_neutral_material_to_unmaterialed_meshes() -> None:
    material = None
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH" or len(obj.data.materials) > 0:
            continue
        if material is None:
            material = bpy.data.materials.new("DiagnosticNeutralMaterial")
            material.diffuse_color = (0.18, 0.24, 0.32, 1.0)
            material.use_nodes = True
            bsdf = material.node_tree.nodes.get("Principled BSDF") if material.node_tree else None
            if bsdf is not None:
                bsdf.inputs["Base Color"].default_value = material.diffuse_color
                bsdf.inputs["Roughness"].default_value = 0.68
        obj.data.materials.append(material)


def is_room_shell(obj: bpy.types.Object) -> bool:
    name = obj.name.lower()
    data_name = obj.data.name.lower() if getattr(obj, "data", None) else ""
    return (
        name == "floor"
        or data_name == "floor"
        or name.startswith("floor.")
        or data_name.startswith("floor.")
        or name.startswith("wall_")
        or data_name.startswith("wall_")
    )


def set_room_shell_hidden(hidden: bool, hide_floor: bool = False) -> None:
    for obj in bpy.context.scene.objects:
        if obj.type not in TARGET_TYPES:
            continue
        if is_room_shell(obj) and (hide_floor or "floor" not in obj.name.lower()):
            obj.hide_render = hidden
            obj.hide_viewport = hidden


def object_world_extents(obj: bpy.types.Object) -> Vector:
    corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    return Vector(
        (
            max(corner.x for corner in corners) - min(corner.x for corner in corners),
            max(corner.y for corner in corners) - min(corner.y for corner in corners),
            max(corner.z for corner in corners) - min(corner.z for corner in corners),
        )
    )


def validate_scene_z_up(*, strict: bool) -> dict:
    # Match explicit architectural floor object names, not arbitrary semantic
    # names containing the substring (for example ``floor_lamp_geometry_0``).
    # Blender may append a numeric ``.001`` suffix when names collide.
    accepted_floor_names = {
        "floor",
        "room_floor",
        "scene_floor",
        "architecture_floor",
    }

    def is_architectural_floor(obj: bpy.types.Object) -> bool:
        names = [obj.name, getattr(obj.data, "name", "")]
        return any(
            str(name).lower().rsplit(".", 1)[0] in accepted_floor_names
            for name in names
            if name
        )

    floors = [
        obj
        for obj in bpy.context.scene.objects
        if obj.type in TARGET_TYPES and is_architectural_floor(obj)
    ]
    if not floors:
        return {"ok": True, "status": "skipped_no_named_floor", "floors": []}

    floor_reports = []
    for obj in floors:
        extents = object_world_extents(obj)
        horizontal_min = min(float(extents.x), float(extents.y))
        maximum_thickness = max(0.08, horizontal_min * 0.10)
        horizontal = horizontal_min > 1e-4 and float(extents.z) <= maximum_thickness
        floor_reports.append(
            {
                "object": obj.name,
                "world_extents_m": [float(extents.x), float(extents.y), float(extents.z)],
                "maximum_z_thickness_m": maximum_thickness,
                "horizontal": horizontal,
            }
        )

    report = {
        "ok": all(item["horizontal"] for item in floor_reports),
        "status": "checked_named_floor",
        "coordinate_system": "blender_z_up",
        "floors": floor_reports,
    }
    if strict and not report["ok"]:
        raise RuntimeError(
            "Scene is not Z-up after Blender GLB import; a named floor is vertical. "
            f"Axis report: {json.dumps(report, sort_keys=True)}"
        )
    return report


def object_bbox_by_keywords(keywords: tuple[str, ...]) -> tuple[Vector, Vector] | None:
    matched = []
    for obj in bpy.context.scene.objects:
        if obj.type not in TARGET_TYPES:
            continue
        text = f"{obj.name} {obj.data.name if getattr(obj, 'data', None) else ''}".lower()
        if any(keyword in text for keyword in keywords):
            matched.append(obj)
    if not matched:
        return None
    return mesh_bbox_world(matched)


def render_scene_views(
    scene_glb: Path,
    plan: dict,
    output_dir: Path,
    resolution: int,
    *,
    strict_z_up: bool,
    qa_passes: bool,
) -> tuple[list[Path], dict, dict]:
    clear_scene()
    bpy.ops.import_scene.gltf(filepath=str(scene_glb))
    set_material_alpha_mode()
    add_neutral_material_to_unmaterialed_meshes()
    axis_validation = validate_scene_z_up(strict=strict_z_up)
    setup_world()
    setup_lighting()

    objects = renderable_objects()
    min_v, max_v = mesh_bbox_world(objects)
    center_v = (min_v + max_v) * 0.5
    extents = max_v - min_v
    width = max(float(extents.x), 1e-3)
    length = max(float(extents.y), 1e-3)
    height = max(float(extents.z), 1e-3)
    center = (float(center_v.x), float(center_v.y), float(center_v.z))
    diag = max(width, length, height)
    views: list[Path] = []
    qa_views: dict[str, dict] = {}

    set_room_shell_hidden(True)
    top = add_camera("SceneTopCamera", (center[0], center[1], float(max_v.z) + diag * 1.05), center)
    top.data.type = "ORTHO"
    top.data.ortho_scale = max(width, length) * 1.12
    top_path = output_dir / "scene_top.png"
    if qa_passes:
        qa_views["top"] = configure_qa_passes(
            view_name="top", output_dir=output_dir, plan=plan, camera=top, resolution=resolution
        )
    render_current(top_path, resolution)
    if qa_passes:
        qa_views["top"]["rgb_path"] = str(top_path)
        render_object_index_pass(
            Path(qa_views["top"]["object_index_path"]), plan, resolution
        )
    views.append(top_path)

    corner = add_camera(
        "SceneCornerCamera",
        (center[0] + width * 0.90, center[1] - length * 1.10, float(max_v.z) + diag * 0.48),
        (center[0], center[1], float(min_v.z) + height * 0.38),
    )
    corner.data.lens = 45
    corner_path = output_dir / "scene_corner.png"
    if qa_passes:
        qa_views["corner"] = configure_qa_passes(
            view_name="corner", output_dir=output_dir, plan=plan, camera=corner, resolution=resolution
        )
    render_current(corner_path, resolution)
    if qa_passes:
        qa_views["corner"]["rgb_path"] = str(corner_path)
        render_object_index_pass(
            Path(qa_views["corner"]["object_index_path"]), plan, resolution
        )
    views.append(corner_path)

    front = add_camera(
        "SceneFrontCamera",
        (
            center[0],
            center[1] - length * 2.30,
            float(min_v.z) + min(1.55, height * 0.82),
        ),
        (
            center[0],
            center[1],
            float(min_v.z) + min(1.25, height * 0.55),
        ),
    )
    # A true south-to-north, approximately standing-eye-height inspection.
    # This is intentionally distinct from the high corner/dollhouse view.
    front.data.lens = 65
    front_path = output_dir / "scene_front.png"
    if qa_passes:
        qa_views["front"] = configure_qa_passes(
            view_name="front", output_dir=output_dir, plan=plan, camera=front, resolution=resolution
        )
    render_current(front_path, resolution)
    if qa_passes:
        qa_views["front"]["rgb_path"] = str(front_path)
        render_object_index_pass(
            Path(qa_views["front"]["object_index_path"]), plan, resolution
        )
    views.append(front_path)

    desk_bbox = object_bbox_by_keywords(("desk",))
    if desk_bbox:
        if qa_passes:
            # The close-up is a human diagnostic only. Do not overwrite the
            # front camera's depth/index outputs with a different camera.
            bpy.context.scene.use_nodes = False
        desk_min, desk_max = desk_bbox
        desk_center = (desk_min + desk_max) * 0.5
        desk_extents = desk_max - desk_min
        dx = float(desk_center.x)
        dy = float(desk_center.y)
        dz = float(desk_center.z)
        close = add_camera(
            "DeskCloseCamera",
            (
                dx + max(float(desk_extents.x), 0.5) * 0.75,
                dy - max(float(desk_extents.y), 0.5) * 1.55,
                dz + max(float(desk_extents.z), 0.5) * 0.72,
            ),
            (dx, dy, dz + float(desk_extents.z) * 0.08),
        )
        close.data.lens = 48
        close_path = output_dir / "scene_desk_close.png"
        render_current(close_path, resolution)
        views.append(close_path)

    set_room_shell_hidden(False)
    return views, axis_validation, {"enabled": qa_passes, "views": qa_views}


def normalize_asset(objects: list[bpy.types.Object]) -> None:
    mesh_objects = [obj for obj in objects if obj.type in TARGET_TYPES]
    if not mesh_objects:
        raise RuntimeError("Imported asset contains no renderable objects.")
    min_v, max_v = mesh_bbox_world(mesh_objects)
    center = (min_v + max_v) * 0.5
    extents = max_v - min_v
    max_extent = max(float(extents.x), float(extents.y), float(extents.z), 1e-6)
    root = bpy.data.objects.new("AssetRoot", None)
    bpy.context.scene.collection.objects.link(root)
    imported_set = set(objects)
    root_candidates = [obj for obj in objects if obj.parent not in imported_set]
    for obj in root_candidates:
        obj.parent = root
        obj.matrix_parent_inverse = root.matrix_world.inverted()
    root.location = -center
    root.scale = (1.35 / max_extent, 1.35 / max_extent, 1.35 / max_extent)


def render_asset_views(asset_dir: Path, plan: dict, output_dir: Path, resolution: int) -> list[Path]:
    views: list[Path] = []
    asset_output = output_dir / "assets"
    asset_output.mkdir(parents=True, exist_ok=True)

    for obj in plan.get("objects", []):
        object_id = str(obj.get("id"))
        asset_path = asset_dir / f"{object_id}.glb"
        if not asset_path.exists():
            continue
        clear_scene()
        bpy.ops.import_scene.gltf(filepath=str(asset_path))
        imported = list(bpy.context.scene.objects)
        normalize_asset(imported)
        setup_world()
        setup_lighting()

        front = add_camera("AssetFrontCamera", (2.2, -2.8, 1.45), (0.0, 0.0, 0.1))
        front.data.type = "ORTHO"
        front.data.ortho_scale = 1.95
        front_path = asset_output / f"{object_id}_front.png"
        render_current(front_path, max(520, resolution // 2))
        views.append(front_path)

        side = add_camera("AssetSideCamera", (2.8, 0.0, 1.45), (0.0, 0.0, 0.1))
        side.data.type = "ORTHO"
        side.data.ortho_scale = 1.95
        side_path = asset_output / f"{object_id}_side.png"
        render_current(side_path, max(520, resolution // 2))
        views.append(side_path)

    return views


def main() -> None:
    args = parse_args()
    if not args.scene_glb.exists():
        raise FileNotFoundError(f"Missing scene GLB: {args.scene_glb}")
    if not args.plan.exists():
        raise FileNotFoundError(f"Missing plan: {args.plan}")
    if not args.asset_dir.exists():
        raise FileNotFoundError(f"Missing asset dir: {args.asset_dir}")

    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    scene_views, axis_validation, qa_passes = render_scene_views(
        args.scene_glb,
        plan,
        args.output_dir,
        args.resolution,
        strict_z_up=not args.allow_non_z_up,
        qa_passes=bool(args.qa_passes),
    )
    asset_views = [] if args.skip_assets else render_asset_views(args.asset_dir, plan, args.output_dir, args.resolution)
    manifest = {
        "scene_views": [str(path) for path in scene_views],
        "asset_views": [str(path) for path in asset_views],
        "axis_validation": axis_validation,
        "qa_passes": qa_passes,
    }
    (args.output_dir / "render_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
