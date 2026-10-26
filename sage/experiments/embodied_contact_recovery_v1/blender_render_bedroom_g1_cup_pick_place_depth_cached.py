#!/usr/bin/env python3
"""Render the mug task with cached room color and local depth correctness.

The complete room is cached once.  Every object that can overlap the task in
the selected camera (dresser, plant, clock, chair, mug, and robot) is then
rendered together in one transparent view layer, so Blender's depth buffer
resolves their occlusion.  Floor/rug shadow deltas are composited separately.
"""

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
    configure_delta_compositor,
    configure_render,
    find_layer_collection,
    is_contact_receiver,
    is_south_wall,
    move_objects_to_collection,
    render_exr,
    render_receiver_visibility_mask,
    sha256,
)


LOCAL_ROOT_NAMES = {
    "dresser_root",
    "dresser_plant_root",
    "bedside_clock_root",
    "explicit_office_chair_root",
}
LOCAL_NAME_TOKENS = (
    "dresser_geometry",
    "dresser_plant_geometry",
    "bedside_clock_geometry",
    "explicit_office_chair_geometry",
)


def descendants(root):
    result = []
    pending = list(root.children)
    while pending:
        obj = pending.pop()
        result.append(obj)
        pending.extend(obj.children)
    return result


def root_ancestor_name(obj) -> str:
    current = obj
    while current.parent is not None:
        current = current.parent
    return current.name


def is_local_occluder(obj) -> bool:
    root_name = root_ancestor_name(obj)
    return root_name in LOCAL_ROOT_NAMES or any(
        token in obj.name for token in LOCAL_NAME_TOKENS
    )


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
    parser.add_argument("--static-samples", type=int, default=4)
    parser.add_argument("--dynamic-samples", type=int, default=8)
    parser.add_argument("--preview-index", type=int)
    parser.add_argument(
        "--preview-indices",
        help="comma-separated source-frame indices rendered as a short sequence",
    )
    parser.add_argument("--reuse-cache", action="store_true")
    parser.add_argument(
        "--start-frame",
        type=int,
        default=1,
        help="resume a full render at this one-based output frame",
    )
    parser.add_argument(
        "--end-frame",
        type=int,
        help="stop a full render at this inclusive one-based output frame",
    )
    parser.add_argument(
        "--parallel-chunk",
        action="store_true",
        help="allow a non-prefix frame range for coordinated parallel rendering",
    )
    parser.add_argument(
        "--physics-contact-trajectory",
        action="store_true",
        help="label the render as a recorded dynamic contact trajectory",
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
    cache = args.output / "cache"
    cache.mkdir(parents=True, exist_ok=True)

    trajectory = np.load(args.trajectory)
    positions = trajectory["positions"]
    matrices = trajectory["matrices"]
    times = trajectory["times"]
    cup_positions = trajectory["cup_positions"]
    cup_matrices = trajectory["cup_matrices"]
    visual_rows = json.loads(args.visuals.read_text())
    if positions.shape[:2] != (len(times), len(visual_rows)):
        raise RuntimeError("trajectory/visual manifest shape mismatch")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(args.scene))
    scene = bpy.context.scene
    for view_layer in scene.view_layers:
        view_layer.use_pass_object_index = True
        view_layer.update_render_passes()
    room_meshes = [obj for obj in scene.objects if obj.type == "MESH"]
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
    cup_material = material_for("cup_ceramic_depth_v3", cup_rgba)
    cup_bsdf = cup_material.node_tree.nodes.get("Principled BSDF")
    cup_bsdf.inputs["Metallic"].default_value = 0.02
    cup_bsdf.inputs["Roughness"].default_value = 0.34
    for obj in cup_meshes:
        obj.data.materials.clear()
        obj.data.materials.append(cup_material)

    static_visible = {obj.name: not obj.hide_render for obj in room_meshes}
    for obj in cup_meshes:
        static_visible[obj.name] = False
    local_occluders = [
        obj for obj in room_meshes if obj not in cup_meshes and is_local_occluder(obj)
    ]
    if not local_occluders:
        raise RuntimeError("no local depth occluders found")

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
    end_frame = args.end_frame if args.end_frame is not None else len(frame_indices)
    if args.start_frame < 1 or args.start_frame > len(frame_indices):
        raise RuntimeError("start frame is outside the output sequence")
    if end_frame < args.start_frame or end_frame > len(frame_indices):
        raise RuntimeError("end frame is outside the output sequence")
    if (args.preview_index is not None or args.preview_indices) and (
        args.start_frame != 1 or args.end_frame is not None
    ):
        raise RuntimeError("frame ranges are only supported for full renders")
    if args.start_frame > 1 and not args.parallel_chunk:
        missing = [
            index
            for index in range(1, args.start_frame)
            if not (args.output / f"frame_{index:04d}.png").is_file()
        ]
        if missing:
            raise RuntimeError(
                f"cannot resume: {len(missing)} earlier output frames are missing"
            )

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
    configure_render(scene, args.width, args.height, args.fps, args.dynamic_samples)
    scene.frame_start = args.start_frame
    scene.frame_end = end_frame
    scene.frame_set(1)

    static_background = cache / "static_background.exr"
    receiver_baseline = cache / "receiver_baseline.exr"
    receiver_visibility = cache / "receiver_visibility.exr"

    for obj in robot_objects:
        obj.hide_render = True
    for obj in room_meshes:
        obj.hide_render = not static_visible[obj.name]
    if not (args.reuse_cache and static_background.is_file()):
        render_exr(scene, static_background, args.static_samples, transparent=False)

    receivers = [obj for obj in room_meshes if is_contact_receiver(obj)]
    if not receivers:
        raise RuntimeError("no floor/rug contact receivers found")
    for obj in room_meshes:
        obj.hide_render = obj not in receivers
    if not (args.reuse_cache and receiver_baseline.is_file()):
        render_exr(scene, receiver_baseline, args.dynamic_samples, transparent=True)

    for obj in room_meshes:
        obj.hide_render = not static_visible[obj.name]
    if not (args.reuse_cache and receiver_visibility.is_file()):
        render_receiver_visibility_mask(
            scene,
            receiver_visibility,
            room_meshes,
            receivers,
        )

    dynamic_room_objects = set(receivers + local_occluders + cup_meshes)
    for obj in room_meshes:
        obj.hide_render = obj not in dynamic_room_objects
    for obj in robot_objects:
        obj.hide_render = False

    dynamic_layer = scene.view_layers[0]
    receiver_collection = move_objects_to_collection(
        scene,
        "G1 cup task floor receivers",
        receivers,
    )
    dynamic_alpha_layer = scene.view_layers.new("LocalDepthAlpha")
    excluded_receivers = find_layer_collection(
        dynamic_alpha_layer.layer_collection,
        receiver_collection,
    )
    if excluded_receivers is None:
        raise RuntimeError("receiver collection unavailable in local depth layer")
    excluded_receivers.exclude = True
    configure_delta_compositor(
        scene,
        static_background,
        receiver_baseline,
        receiver_visibility,
        dynamic_layer.name,
        dynamic_alpha_layer.name,
    )
    scene.eevee.taa_render_samples = args.dynamic_samples
    scene.eevee.taa_samples = args.dynamic_samples
    scene.render.film_transparent = True
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
        "schema": "depth_cached_bedroom_g1_cup_pick_place_render_v1",
        "label": (
            "fixed_base_dynamic_friction_lift_hold_demo"
            if args.physics_contact_trajectory
            else "task_level_kinematic_visual_demo_not_physics_validated"
        ),
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
        "rendered_frame_start": args.start_frame,
        "rendered_frame_end": end_frame,
        "parallel_chunk": args.parallel_chunk,
        "resolution": [args.width, args.height],
        "engine": "BLENDER_EEVEE_NEXT",
        "static_samples": args.static_samples,
        "dynamic_samples": args.dynamic_samples,
        "camera_location": list(args.camera_location),
        "camera_target": list(args.camera_target),
        "camera_lens_mm": args.camera_lens,
        "render_strategy": (
            "linear_static_cache_plus_floor_shadow_delta_and_"
            "depth_aware_local_occluder_rerender"
        ),
        "local_depth_layer_contents": [
            "G1 robot",
            "bedside mug",
            "dresser",
            "dresser plant",
            "bedside clock",
            "office chair",
        ],
        "local_occluder_meshes": [obj.name for obj in local_occluders],
        "local_depth_test_enabled": True,
        "full_room_dynamic_shadows": False,
        "floor_and_rug_dynamic_shadows": True,
        "dresser_dynamic_shadows": True,
        "background_compositing_used": True,
        "static_room_alpha_over_without_local_depth": False,
        "physical_simulation_executed": args.physics_contact_trajectory,
        "physics_scope": (
            "dynamic_free_mug_finger_contact_lift_and_hold_with_robot_base_stabilized"
            if args.physics_contact_trajectory
            else None
        ),
        "synthetic_video_interpolation_used": False,
        "debug_sites_rendered": False,
        "collision_geometries_rendered": False,
    }
    (args.output / "RENDER.json").write_text(json.dumps(metadata, indent=2) + "\n")


if __name__ == "__main__":
    main()
