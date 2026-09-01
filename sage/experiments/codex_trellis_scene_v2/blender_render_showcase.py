#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
from itertools import product
from pathlib import Path

import bpy
import numpy as np
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector


TARGET_TYPES = {"MESH", "CURVE", "SURFACE", "META", "FONT"}


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("candidates", "final"), required=True)
    parser.add_argument("--scene-glb", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--profiles", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--selection", type=Path)
    return parser.parse_args(argv)


def renderables() -> list[bpy.types.Object]:
    return [obj for obj in bpy.context.scene.objects if obj.type in TARGET_TYPES]


def objects_for_id(object_id: str) -> list[bpy.types.Object]:
    prefix = object_id.lower() + "_"
    return [
        obj
        for obj in renderables()
        if obj.name.lower() == object_id.lower()
        or obj.name.lower().startswith(prefix)
        or (
            getattr(obj, "data", None) is not None
            and str(obj.data.name).lower().startswith(prefix)
        )
    ]


def bounds(objects: list[bpy.types.Object]) -> tuple[Vector, Vector]:
    points = [obj.matrix_world @ Vector(corner) for obj in objects for corner in obj.bound_box]
    if not points:
        raise RuntimeError("no renderable bounds")
    return (
        Vector(tuple(min(point[axis] for point in points) for axis in range(3))),
        Vector(tuple(max(point[axis] for point in points) for axis in range(3))),
    )


def look_at(obj: bpy.types.Object, target: Vector) -> None:
    obj.rotation_euler = (target - obj.location).to_track_quat("-Z", "Y").to_euler()


def camera_specs(minimum: Vector, maximum: Vector) -> list[dict]:
    center = (minimum + maximum) * 0.5
    width = float(maximum.x - minimum.x)
    depth = float(maximum.y - minimum.y)
    eye = float(minimum.z + min(1.62, (maximum.z - minimum.z) * 0.72))
    target_z = float(minimum.z + min(1.12, (maximum.z - minimum.z) * 0.48))
    specs = []
    for side, location, target, hidden in (
        ("south", (center.x, minimum.y - depth * 1.25, eye), (center.x, center.y, target_z), "south"),
        ("north", (center.x, maximum.y + depth * 1.25, eye), (center.x, center.y, target_z), "north"),
        ("west", (minimum.x - width * 1.25, center.y, eye), (center.x, center.y, target_z), "west"),
        ("east", (maximum.x + width * 1.25, center.y, eye), (center.x, center.y, target_z), "east"),
    ):
        for offset_index, offset in enumerate((-0.16, 0.0, 0.16)):
            loc = list(location)
            aim = list(target)
            if side in {"south", "north"}:
                loc[0] += width * offset
                aim[0] -= width * offset * 0.25
            else:
                loc[1] += depth * offset
                aim[1] -= depth * offset * 0.25
            specs.append(
                {
                    "id": f"{side}_{offset_index}",
                    "room_side": side,
                    "location": [float(value) for value in loc],
                    "target": [float(value) for value in aim],
                    "lens_mm": 46.0 if offset_index == 1 else 43.0,
                    "hidden_wall": hidden,
                }
            )
    for index, (sx, sy) in enumerate(((-1, -1), (1, -1), (-1, 1), (1, 1))):
        specs.append(
            {
                "id": f"corner_{index}",
                "room_side": f"corner_{sx}_{sy}",
                "location": [
                    float(center.x + sx * width * 1.02),
                    float(center.y + sy * depth * 1.02),
                    float(maximum.z + max(width, depth) * 0.28),
                ],
                "target": [float(center.x), float(center.y), target_z],
                "lens_mm": 48.0,
                "hidden_wall": "west" if sx < 0 else "east",
                "secondary_hidden_wall": "south" if sy < 0 else "north",
            }
        )
    return specs


def wall_side(obj: bpy.types.Object) -> str | None:
    name = f"{obj.name} {getattr(obj.data, 'name', '')}".lower()
    for side in ("north", "south", "east", "west"):
        if f"wall_{side}" in name:
            return side
    return None


def apply_camera_shell(spec: dict) -> None:
    hidden = {spec.get("hidden_wall"), spec.get("secondary_hidden_wall")}
    for obj in renderables():
        side = wall_side(obj)
        obj.hide_render = bool(side and side in hidden)
        obj.hide_viewport = obj.hide_render


def make_camera(spec: dict) -> bpy.types.Object:
    data = bpy.data.cameras.new(f"Camera_{spec['id']}")
    data.lens = float(spec["lens_mm"])
    data.sensor_width = 36.0
    data.clip_start = 0.05
    data.clip_end = 100.0
    camera = bpy.data.objects.new(f"Camera_{spec['id']}", data)
    bpy.context.scene.collection.objects.link(camera)
    camera.location = tuple(spec["location"])
    look_at(camera, Vector(spec["target"]))
    bpy.context.scene.camera = camera
    bpy.context.view_layer.update()
    return camera


def projection(objects: list[bpy.types.Object], camera: bpy.types.Object) -> dict:
    if not objects:
        return {"matched_mesh_count": 0, "bbox_inside_frame": False}
    minimum, maximum = bounds(objects)
    coordinates = [
        world_to_camera_view(bpy.context.scene, camera, Vector((x, y, z)))
        for x, y, z in product(
            (minimum.x, maximum.x),
            (minimum.y, maximum.y),
            (minimum.z, maximum.z),
        )
    ]
    xs, ys = [float(item.x) for item in coordinates], [float(item.y) for item in coordinates]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    return {
        "matched_mesh_count": len(objects),
        "bbox_normalized": [x0, y0, x1, y1],
        "bbox_inside_frame": bool(x0 >= 0 and y0 >= 0 and x1 <= 1 and y1 <= 1),
    }


def setup_world_and_lights() -> None:
    world = bpy.data.worlds.new("ShowcaseWorld")
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    background.inputs[0].default_value = (0.045, 0.065, 0.095, 1.0)
    background.inputs[1].default_value = 0.28
    bpy.context.scene.world = world
    for name, location, energy, size, color in (
        ("ShowcaseKey", (2.0, -2.0, 4.8), 950.0, 4.0, (1.0, 0.82, 0.68)),
        ("ShowcaseFill", (-3.5, 1.5, 3.2), 520.0, 5.0, (0.65, 0.78, 1.0)),
        ("ShowcaseTop", (2.6, 2.3, 5.2), 720.0, 3.5, (1.0, 0.93, 0.82)),
    ):
        data = bpy.data.lights.new(name, "AREA")
        data.energy = energy
        data.shape = "DISK"
        data.size = size
        data.color = color
        light = bpy.data.objects.new(name, data)
        bpy.context.scene.collection.objects.link(light)
        light.location = location
        look_at(light, Vector((2.6, 2.3, 0.8)))


def set_color_management(profile: dict) -> dict:
    scene = bpy.context.scene
    applied = {}
    try:
        scene.view_settings.view_transform = str(profile["view_transform"])
    except (TypeError, ValueError):
        scene.view_settings.view_transform = "Filmic"
    try:
        scene.view_settings.look = str(profile["look"])
    except (TypeError, ValueError):
        pass
    scene.view_settings.exposure = float(profile["exposure"])
    scene.view_settings.gamma = 1.0
    if hasattr(scene.view_settings, "use_white_balance"):
        scene.view_settings.use_white_balance = True
        scene.view_settings.white_balance_temperature = float(profile["white_balance_kelvin"])
        applied["white_balance_api"] = True
    else:
        applied["white_balance_api"] = False
    applied.update(
        {
            "view_transform": scene.view_settings.view_transform,
            "look": scene.view_settings.look,
            "exposure": float(scene.view_settings.exposure),
            "white_balance_kelvin_requested": int(profile["white_balance_kelvin"]),
        }
    )
    return applied


def setup_render(profile: dict, output: Path) -> dict:
    scene = bpy.context.scene
    scene.render.resolution_x = int(profile["resolution"][0])
    scene.render.resolution_y = int(profile["resolution"][1])
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.filepath = str(output)
    scene.render.film_transparent = False
    color = set_color_management(profile)
    engine = profile["engine"]
    try:
        scene.render.engine = engine
    except Exception:
        if engine == "BLENDER_EEVEE_NEXT":
            scene.render.engine = "BLENDER_EEVEE"
        else:
            raise
    device = "CPU"
    if engine == "CYCLES":
        scene.cycles.samples = int(profile["samples"])
        scene.cycles.use_denoising = bool(profile["denoise"])
        scene.cycles.use_adaptive_sampling = True
        scene.cycles.adaptive_threshold = 0.015
        scene.cycles.max_bounces = 8
        scene.cycles.diffuse_bounces = 3
        scene.cycles.glossy_bounces = 3
        scene.cycles.transparent_max_bounces = 4
        try:
            preferences = bpy.context.preferences.addons["cycles"].preferences
            for compute_type in ("OPTIX", "CUDA"):
                try:
                    preferences.compute_device_type = compute_type
                    preferences.get_devices()
                    active = [item for item in preferences.devices if item.type != "CPU"]
                    if active:
                        for item in preferences.devices:
                            item.use = item in active
                        scene.cycles.device = "GPU"
                        device = compute_type
                        break
                except Exception:
                    continue
        except Exception:
            pass
    return {"engine": scene.render.engine, "device": device, "color_management": color}


def normalize_materials() -> dict:
    material_rows = []
    window_adjusted = []
    for material in bpy.data.materials:
        if not material.use_nodes or not material.node_tree:
            continue
        bsdf = material.node_tree.nodes.get("Principled BSDF")
        if bsdf is None:
            continue
        roughness = bsdf.inputs.get("Roughness")
        if roughness and not roughness.is_linked:
            roughness.default_value = min(0.78, max(0.32, float(roughness.default_value)))
        material_rows.append(material.name)
    for obj in renderables():
        if not obj.name.lower().startswith("window_main"):
            continue
        for material in obj.data.materials:
            if not material or not material.use_nodes or not material.node_tree:
                continue
            bsdf = material.node_tree.nodes.get("Principled BSDF")
            if bsdf is None:
                continue
            base = bsdf.inputs.get("Base Color")
            if base and base.is_linked:
                source = base.links[0].from_socket
                material.node_tree.links.remove(base.links[0])
                screen = material.node_tree.nodes.new("ShaderNodeMixRGB")
                screen.name = "ShowcaseWindowBlackFloor"
                screen.blend_type = "SCREEN"
                screen.inputs[0].default_value = 1.0
                screen.inputs[2].default_value = (0.08, 0.20, 0.35, 1.0)
                material.node_tree.links.new(source, screen.inputs[1])
                material.node_tree.links.new(screen.outputs[0], base)
                window_adjusted.append(material.name)
            elif base and max(base.default_value[:3]) < 0.06:
                base.default_value = (0.035, 0.085, 0.14, 1.0)
                roughness = bsdf.inputs.get("Roughness")
                if roughness and not roughness.is_linked:
                    roughness.default_value = 0.28
                window_adjusted.append(material.name)
    texture_nodes = sum(
        node.type == "TEX_IMAGE"
        for material in bpy.data.materials
        if material.use_nodes and material.node_tree
        for node in material.node_tree.nodes
    )
    return {
        "material_count": len(bpy.data.materials),
        "principled_material_count": len(material_rows),
        "image_texture_node_count": texture_nodes,
        "roughness_clamp": [0.32, 0.78],
        "material_scale_m": 1.0,
        "dark_window_materials_adjusted": sorted(set(window_adjusted)),
    }


def render_candidate_masks(
    plan: dict,
    specs: list[dict],
    output_dir: Path,
    resolution: int | tuple[int, int] = 256,
) -> list[dict]:
    scene = bpy.context.scene
    planned = [row for row in plan.get("objects", []) if isinstance(row, dict) and row.get("id")]
    architecture = plan.get("architecture", {})
    for row in architecture.get("windows", []) if isinstance(architecture, dict) else []:
        if isinstance(row, dict) and row.get("id"):
            planned.append(row)
    denominator = max(1, len(planned))
    object_indices = {obj.name: 0 for obj in renderables()}
    matched_by_id = {}
    for index, row in enumerate(planned, start=1):
        matched = objects_for_id(str(row["id"]))
        matched_by_id[str(row["id"])] = matched
        for obj in matched:
            object_indices[obj.name] = index
    materials = {}
    for index in range(denominator + 1):
        value = float(index) / denominator
        material = bpy.data.materials.new(f"CandidateIndex_{index}")
        material.use_nodes = True
        nodes = material.node_tree.nodes
        nodes.clear()
        output_node = nodes.new("ShaderNodeOutputMaterial")
        emission = nodes.new("ShaderNodeEmission")
        emission.inputs["Color"].default_value = (value, value, value, 1.0)
        emission.inputs["Strength"].default_value = 1.0
        material.node_tree.links.new(emission.outputs["Emission"], output_node.inputs["Surface"])
        materials[index] = material
    original_materials = {}
    for obj in renderables():
        slots = getattr(obj.data, "materials", None)
        if slots is None:
            continue
        original_materials[obj.name] = list(slots)
        slots.clear()
        slots.append(materials[object_indices[obj.name]])
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    resolution_x, resolution_y = (
        (resolution, resolution) if isinstance(resolution, int) else resolution
    )
    scene.render.resolution_x = resolution_x
    scene.render.resolution_y = resolution_y
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "BW"
    scene.render.image_settings.color_depth = "8"
    scene.render.film_transparent = False
    scene.view_settings.view_transform = "Raw"
    scene.view_settings.look = "None"
    background = scene.world.node_tree.nodes.get("Background")
    background.inputs[0].default_value = (0, 0, 0, 1)
    background.inputs[1].default_value = 0.0
    reports = []
    output_dir.mkdir(parents=True, exist_ok=True)
    for spec in specs:
        apply_camera_shell(spec)
        camera = make_camera(spec)
        object_projections = {
            object_id: projection(objects, camera)
            for object_id, objects in matched_by_id.items()
        }
        path = output_dir / f"{spec['id']}_index.png"
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        rendered_image = bpy.data.images.load(str(path), check_existing=False)
        rendered_image.colorspace_settings.name = "Non-Color"
        pixels = np.asarray(rendered_image.pixels[:], dtype=np.float32)
        pixels = pixels.reshape((resolution_y, resolution_x, 4))[:, :, 0]
        bpy.data.images.remove(rendered_image)
        decoded = np.rint(pixels * denominator).astype(np.int32)
        nonzero_y, nonzero_x = np.nonzero(decoded > 0)
        if len(nonzero_x):
            centroid_x = float(np.mean(nonzero_x) / max(1, resolution_x - 1))
            centroid_y = float(np.mean(nonzero_y) / max(1, resolution_y - 1))
            centeredness = max(
                0.0, 1.0 - math.hypot(centroid_x - 0.5, centroid_y - 0.5) / 0.7072
            )
        else:
            centeredness = 0.0
        object_reports = {}
        for index, row in enumerate(planned, start=1):
            object_id = str(row["id"])
            mask = decoded == index
            ys, xs = np.nonzero(mask)
            touches = bool(
                len(xs)
                and (
                    xs.min() == 0
                    or ys.min() == 0
                    or xs.max() == resolution_x - 1
                    or ys.max() == resolution_y - 1
                )
            )
            object_reports[object_id] = {
                "visible_pixels": int(np.count_nonzero(mask)),
                "touches_image_border": touches,
                "projection_inside_frame": object_projections[object_id].get(
                    "bbox_inside_frame", False
                ),
                "projection": object_projections[object_id],
                "pass_index": index,
            }
        reports.append(
            {
                **spec,
                "mask_path": str(path.resolve()),
                "object_index_denominator": denominator,
                "objects": object_reports,
                "scene_occupancy_fraction": float(np.mean(decoded > 0)),
                "visible_centroid_centeredness": centeredness,
            }
        )
        bpy.data.objects.remove(camera, do_unlink=True)
    for obj in renderables():
        if obj.name not in original_materials:
            continue
        obj.data.materials.clear()
        for material in original_materials[obj.name]:
            obj.data.materials.append(material)
    for material in materials.values():
        bpy.data.materials.remove(material)
    return reports


def render_relationship_evidence(
    output_dir: Path, profile: dict
) -> list[dict]:
    output_dir.mkdir(parents=True, exist_ok=True)
    background = bpy.context.scene.world.node_tree.nodes.get("Background")
    background.inputs[0].default_value = (0.045, 0.065, 0.095, 1.0)
    background.inputs[1].default_value = 0.28
    rows = []
    all_objects = renderables()
    groups = (
        (
            "bookcase_books",
            ("sdf_open_bookcase", "sdf_books_1", "sdf_books_2", "sdf_books_3"),
        ),
        ("desk_chair", ("explicit_desk", "explicit_office_chair")),
    )
    for name, object_ids in groups:
        selected = [obj for object_id in object_ids for obj in objects_for_id(object_id)]
        for obj in all_objects:
            obj.hide_render = obj not in selected
            obj.hide_viewport = obj.hide_render
        minimum, maximum = bounds(selected)
        center = (minimum + maximum) * 0.5
        extent = maximum - minimum
        spec = {
            "id": f"relation_{name}",
            "location": [
                float(center.x - extent.x * (0.35 if name == "desk_chair" else 0.05)),
                float(minimum.y - max(1.4, max(extent.x, extent.z) * 1.75)),
                float(center.z + extent.z * 0.06),
            ],
            "target": [float(center.x), float(center.y), float(center.z)],
            "lens_mm": 58.0,
        }
        camera = make_camera(spec)
        path = output_dir / f"relationship_{name}.png"
        applied = setup_render(profile, path)
        bpy.ops.render.render(write_still=True)
        rows.append(
            {
                "id": name,
                "rgb_path": str(path.resolve()),
                "object_ids": list(object_ids),
                "profile": profile["name"],
                "applied": applied,
            }
        )
        bpy.data.objects.remove(camera, do_unlink=True)
    for obj in all_objects:
        obj.hide_render = False
        obj.hide_viewport = False
    return rows


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    profiles = json.loads(args.profiles.read_text(encoding="utf-8"))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(args.scene_glb))
    setup_world_and_lights()
    material_audit = normalize_materials()
    minimum, maximum = bounds(renderables())
    specs = camera_specs(minimum, maximum)
    if args.phase == "candidates":
        candidates = render_candidate_masks(
            plan, specs, args.output_dir / "camera_candidates"
        )
        output = {
            "schema": "codex_trellis_showcase_camera_candidates_v1",
            "scene_glb": str(args.scene_glb.resolve()),
            "candidate_count": len(candidates),
            "candidates": candidates,
            "material_audit": material_audit,
        }
        (args.output_dir / "camera_candidates.json").write_text(
            json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return
    if args.selection is None:
        raise ValueError("--selection is required for final phase")
    selection = json.loads(args.selection.read_text(encoding="utf-8"))
    selected_ids = selection["selected_candidate_ids"]
    candidate_index = {row["id"]: row for row in selection["candidates"]}
    selected_views = []
    for view_index, candidate_id in enumerate(selected_ids):
        candidate = candidate_index[candidate_id]
        apply_camera_shell(candidate)
        camera = make_camera(candidate)
        path = args.output_dir / (
            "showcase_hero.png" if view_index == 0 else "showcase_secondary.png"
        )
        applied = setup_render(profiles["final_showcase"], path)
        bpy.ops.render.render(write_still=True)
        selected_views.append(
            {
                "id": candidate_id,
                "role": "hero" if view_index == 0 else "secondary",
                "rgb_path": str(path.resolve()),
                "profile": "final_showcase",
                "cropped_required_ids": candidate["score_report"][
                    "cropped_required_ids"
                ],
                "visible_required_ids": candidate["score_report"][
                    "visible_required_ids"
                ],
                "complete_required_ids": candidate["score_report"][
                    "complete_required_ids"
                ],
                "camera": {
                    key: candidate[key]
                    for key in (
                        "location",
                        "target",
                        "lens_mm",
                        "room_side",
                        "hidden_wall",
                    )
                },
                "applied": applied,
            }
        )
        bpy.data.objects.remove(camera, do_unlink=True)
    final_masks = render_candidate_masks(
        plan,
        [candidate_index[candidate_id] for candidate_id in selected_ids],
        args.output_dir / "final_object_masks",
        resolution=tuple(profiles["final_showcase"]["resolution"]),
    )
    final_mask_index = {row["id"]: row for row in final_masks}
    for row in selected_views:
        mask = final_mask_index[row["id"]]
        row["object_index_mask_path"] = mask["mask_path"]
        row["object_index_denominator"] = mask["object_index_denominator"]
        row["object_mask_observations"] = mask["objects"]
    evidence = render_relationship_evidence(
        args.output_dir / "relationship_evidence",
        profiles["relationship_evidence"],
    )
    output = {
        "schema": "codex_trellis_showcase_render_manifest_v1",
        "profiles": profiles,
        "camera_selection": selection,
        "selected_views": selected_views,
        "relationship_evidence": evidence,
        "material_audit": material_audit,
    }
    (args.output_dir / "showcase_render_manifest.json").write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
