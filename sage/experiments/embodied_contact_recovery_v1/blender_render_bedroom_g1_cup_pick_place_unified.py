#!/usr/bin/env python3
"""Render the G1 mug task in one depth-aware full-scene Blender pass."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import bpy
from mathutils import Matrix
import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))
from blender_render_bedroom_g1_walk import (  # noqa: E402
    import_stl,
    material_for,
    point_at,
    set_transform,
)
from blender_render_bedroom_g1_walk_cached import (  # noqa: E402
    configure_color_and_camera,
    configure_render,
    is_south_wall,
    sha256,
)


def descendants(root):
    result = []
    pending = list(root.children)
    while pending:
        obj = pending.pop()
        result.append(obj)
        pending.extend(obj.children)
    return result


def parse_vector(value: str) -> tuple[float, float, float]:
    parts = [float(item) for item in value.split(",")]
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("expected comma-separated x,y,z")
    return tuple(parts)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", type=Path, required=True)
    parser.add_argument("--trajectory", type=Path, required=True)
    parser.add_argument("--visuals", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--width", type=int, default=512)
    parser.add_argument("--height", type=int, default=384)
    parser.add_argument("--fps", type=int, default=20)
    parser.add_argument("--samples", type=int, default=8)
    parser.add_argument("--preview-index", type=int)
    parser.add_argument(
        "--preview-indices",
        help="comma-separated source-frame indices rendered as a short sequence",
    )
    parser.add_argument(
        "--camera-location",
        type=parse_vector,
        default=(0.8, -1.3, 1.9),
    )
    parser.add_argument(
        "--camera-target",
        type=parse_vector,
        default=(1.6, 0.42, 1.05),
    )
    parser.add_argument("--camera-lens", type=float, default=52.0)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])
    args.output.mkdir(parents=True, exist_ok=True)

    trajectory = np.load(args.trajectory)
    positions = trajectory["positions"]
    matrices = trajectory["matrices"]
    times = trajectory["times"]
    cup_positions = trajectory["cup_positions"]
    cup_matrices = trajectory["cup_matrices"]
    visual_rows = json.loads(args.visuals.read_text())
    if positions.shape[:2] != (len(times), len(visual_rows)):
        raise RuntimeError("trajectory/visual manifest shape mismatch")
    if cup_positions.shape != (len(times), 3):
        raise RuntimeError("cup trajectory shape mismatch")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(args.scene))
    scene = bpy.context.scene
    for obj in scene.objects:
        if obj.type in {"LIGHT", "CAMERA"}:
            obj.hide_render = True
        if is_south_wall(obj):
            obj.hide_render = True

    cup_root = bpy.data.objects.get("bedside_mug_root")
    if cup_root is None:
        raise RuntimeError("bedside mug root not found in bedroom scene")
    cup_objects = [cup_root, *descendants(cup_root)]
    cup_meshes = [obj for obj in cup_objects if obj.type == "MESH"]
    if not cup_meshes:
        raise RuntimeError("bedside mug has no renderable mesh")
    cup_rgba = [0.10, 0.34, 0.66, 1.0]
    cup_material = material_for("cup_ceramic_v3", cup_rgba)
    cup_bsdf = cup_material.node_tree.nodes.get("Principled BSDF")
    cup_bsdf.inputs["Metallic"].default_value = 0.02
    cup_bsdf.inputs["Roughness"].default_value = 0.34
    for obj in cup_meshes:
        obj.data.materials.clear()
        obj.data.materials.append(cup_material)

    robot_objects = []
    for index, row in enumerate(visual_rows):
        obj = import_stl(Path(row["mesh_path"]))
        obj.name = "G1_" + row["geom_name"]
        obj.data.materials.clear()
        obj.data.materials.append(material_for(str(index), row["rgba"]))
        obj.rotation_mode = "QUATERNION"
        robot_objects.append(obj)

    if args.preview_index is not None and args.preview_indices:
        raise RuntimeError("use either --preview-index or --preview-indices")
    if args.preview_index is not None:
        if not 0 <= args.preview_index < len(times):
            raise RuntimeError("preview index out of range")
        frame_indices = [args.preview_index]
    elif args.preview_indices:
        frame_indices = [int(value) for value in args.preview_indices.split(",")]
        if not frame_indices or any(
            index < 0 or index >= len(times) for index in frame_indices
        ):
            raise RuntimeError("preview indices out of range")
    else:
        frame_indices = list(range(len(times)))

    for output_frame, source_frame in enumerate(frame_indices, 1):
        for visual_index, obj in enumerate(robot_objects):
            set_transform(
                obj,
                positions[source_frame, visual_index],
                matrices[source_frame, visual_index],
                visual_rows[visual_index]["mujoco_mesh_pos"],
                visual_rows[visual_index]["mujoco_mesh_quat_wxyz"],
            )
            obj.keyframe_insert(data_path="location", frame=output_frame)
            obj.keyframe_insert(data_path="rotation_quaternion", frame=output_frame)
        cup_root.location = cup_positions[source_frame]
        cup_root.rotation_mode = "QUATERNION"
        cup_root.rotation_quaternion = Matrix(
            cup_matrices[source_frame].tolist()
        ).to_quaternion()
        cup_root.keyframe_insert(data_path="location", frame=output_frame)
        cup_root.keyframe_insert(data_path="rotation_quaternion", frame=output_frame)

    for obj in [*robot_objects, cup_root]:
        if obj.animation_data and obj.animation_data.action:
            for curve in obj.animation_data.action.fcurves:
                for keyframe in curve.keyframe_points:
                    keyframe.interpolation = "LINEAR"

    configure_color_and_camera(scene, np.asarray(args.camera_target))
    scene.camera.location = args.camera_location
    point_at(scene.camera, args.camera_target)
    scene.camera.data.lens = args.camera_lens
    configure_render(scene, args.width, args.height, args.fps, args.samples)
    scene.use_nodes = False
    scene.frame_start = 1
    scene.frame_end = len(frame_indices)
    scene.frame_set(1)
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.image_settings.color_depth = "8"
    scene.render.filepath = str(args.output / "frame_")

    if args.preview_index is not None:
        scene.render.filepath = str(args.output / "preview.png")
        bpy.ops.render.render(write_still=True)
    else:
        bpy.ops.render.render(animation=True)

    metadata = {
        "schema": "unified_bedroom_g1_cup_pick_place_render_v1",
        "label": "task_level_kinematic_visual_demo_not_physics_validated",
        "scene": str(args.scene),
        "scene_sha256": sha256(args.scene),
        "trajectory": str(args.trajectory),
        "trajectory_sha256": sha256(args.trajectory),
        "visuals": str(args.visuals),
        "frames": len(frame_indices),
        "fps": args.fps,
        "duration_s": len(frame_indices) / args.fps,
        "source_frame_indices": frame_indices,
        "source_frame_times_s": [float(times[index]) for index in frame_indices],
        "resolution": [args.width, args.height],
        "engine": "BLENDER_EEVEE_NEXT",
        "samples": args.samples,
        "camera_location": list(args.camera_location),
        "camera_target": list(args.camera_target),
        "camera_lens_mm": args.camera_lens,
        "render_strategy": "single_depth_aware_full_scene_pass",
        "depth_tested_contents": ["complete room", "G1 robot", "bedside mug"],
        "full_room_dynamic_shadows": True,
        "cup_source_object": "bedside_mug_root",
        "cup_geometry_reused_from_scene": True,
        "cup_material_display_override": "blue ceramic for task visibility",
        "background_compositing_used": False,
        "alpha_over_static_room_used": False,
        "physical_simulation_executed": False,
        "synthetic_video_interpolation_used": False,
        "debug_sites_rendered": False,
        "collision_geometries_rendered": False,
    }
    (args.output / "RENDER.json").write_text(json.dumps(metadata, indent=2) + "\n")


if __name__ == "__main__":
    main()
