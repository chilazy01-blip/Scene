#!/usr/bin/env python3
"""Render G1 at higher FPS by caching the static generated bedroom.

The full bedroom is rendered once.  Per animation frame Blender renders only
the robot plus the floor/rug receivers.  A linear-space receiver delta keeps
the original room lighting and furniture shadows while adding the robot and
its changing contact shadows to the cached background.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import bpy
import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))
from blender_render_bedroom_g1_walk import (  # noqa: E402
    add_area,
    import_stl,
    material_for,
    point_at,
    set_transform,
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def configure_color_and_camera(scene, midpoint: np.ndarray) -> None:
    world = bpy.data.worlds.new("Bedroom daylight")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (
        0.65,
        0.72,
        0.82,
        1.0,
    )
    world.node_tree.nodes["Background"].inputs[1].default_value = 0.25
    scene.world = world

    add_area(
        scene,
        "Natural window light",
        (0.6, 2.6, 2.35),
        (3.0, 2.5, 0.8),
        360,
        1.6,
        (0.83, 0.91, 1.0),
    )
    add_area(
        scene,
        "Robot key light",
        (3.8, -1.2, 3.0),
        (2.6, 1.0, 0.8),
        650,
        3.0,
        (1.0, 0.88, 0.73),
    )
    add_area(
        scene,
        "Ceiling bounce",
        (3.0, 2.6, 4.5),
        (3.0, 2.6, 0.0),
        420,
        3.0,
        (1.0, 0.94, 0.84),
    )

    camera_data = bpy.data.cameras.new("Bedroom G1 camera")
    camera = bpy.data.objects.new(camera_data.name, camera_data)
    scene.collection.objects.link(camera)
    camera.location = (4.55, -3.35, 2.25)
    point_at(camera, (float(midpoint[0]), float(midpoint[1]) + 0.28, 0.82))
    camera_data.lens = 52
    camera_data.clip_start = 0.03
    camera_data.clip_end = 100
    scene.camera = camera


def configure_render(scene, width: int, height: int, fps: int, samples: int) -> None:
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.eevee.taa_render_samples = samples
    scene.eevee.taa_samples = samples
    scene.eevee.use_raytracing = False
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.fps = fps
    scene.render.use_file_extension = True
    scene.view_settings.view_transform = "AgX"
    try:
        scene.view_settings.look = "AgX - Medium High Contrast"
    except TypeError:
        pass
    scene.view_settings.exposure = -0.25


def is_south_wall(obj) -> bool:
    side = str(obj.get("architecture_wall", ""))
    return side == "south" or obj.name.startswith("wall_south_")


def is_contact_receiver(obj) -> bool:
    return bool(
        obj.get("floor_material_id")
        or str(obj.get("scene_category", "")) == "area_rug"
        or obj.name == "floor"
        or "explicit_area_rug" in obj.name
    )


def render_exr(scene, path: Path, samples: int, transparent: bool) -> None:
    scene.use_nodes = False
    scene.eevee.taa_render_samples = samples
    scene.eevee.taa_samples = samples
    scene.render.film_transparent = transparent
    scene.render.image_settings.file_format = "OPEN_EXR"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "16"
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def render_receiver_visibility_mask(
    scene,
    path: Path,
    room_meshes: list,
    receivers: list,
) -> None:
    for obj in room_meshes:
        obj.pass_index = 1 if obj in receivers else 0
    for view_layer in scene.view_layers:
        view_layer.use_pass_object_index = True
        view_layer.update_render_passes()
    scene.use_nodes = True
    tree = scene.node_tree
    tree.nodes.clear()
    render_layers = tree.nodes.new("CompositorNodeRLayers")
    output_names = [socket.name for socket in render_layers.outputs]
    if "IndexOB" not in output_names:
        raise RuntimeError(
            "Object-index pass unavailable; render-layer outputs="
            + repr(output_names)
        )
    receiver_mask = tree.nodes.new("CompositorNodeIDMask")
    receiver_mask.index = 1
    receiver_mask.use_antialiasing = True
    composite = tree.nodes.new("CompositorNodeComposite")
    index_ob = next(socket for socket in render_layers.outputs if socket.name == "IndexOB")
    tree.links.new(index_ob, receiver_mask.inputs["ID value"])
    tree.links.new(receiver_mask.outputs["Alpha"], composite.inputs["Image"])
    scene.eevee.taa_render_samples = 1
    scene.eevee.taa_samples = 1
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "OPEN_EXR"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.image_settings.color_depth = "16"
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    for obj in room_meshes:
        obj.pass_index = 0


def move_objects_to_collection(scene, name: str, objects: list):
    collection = bpy.data.collections.new(name)
    scene.collection.children.link(collection)
    for obj in objects:
        for source in list(obj.users_collection):
            source.objects.unlink(obj)
        collection.objects.link(obj)
    return collection


def find_layer_collection(layer_collection, collection):
    if layer_collection.collection == collection:
        return layer_collection
    for child in layer_collection.children:
        match = find_layer_collection(child, collection)
        if match is not None:
            return match
    return None


def configure_delta_compositor(
    scene,
    background: Path,
    baseline: Path,
    receiver_visibility: Path,
    dynamic_layer_name: str,
    robot_layer_name: str,
) -> None:
    scene.use_nodes = True
    tree = scene.node_tree
    tree.nodes.clear()

    render_layers = tree.nodes.new("CompositorNodeRLayers")
    render_layers.layer = dynamic_layer_name
    robot_layers = tree.nodes.new("CompositorNodeRLayers")
    robot_layers.layer = robot_layer_name
    static_node = tree.nodes.new("CompositorNodeImage")
    static_node.image = bpy.data.images.load(str(background), check_existing=True)
    baseline_node = tree.nodes.new("CompositorNodeImage")
    baseline_node.image = bpy.data.images.load(str(baseline), check_existing=True)
    visibility_node = tree.nodes.new("CompositorNodeImage")
    visibility_node.image = bpy.data.images.load(
        str(receiver_visibility), check_existing=True
    )

    receiver_delta = tree.nodes.new("CompositorNodeMixRGB")
    receiver_delta.blend_type = "SUBTRACT"
    receiver_delta.inputs[0].default_value = 1.0
    receiver_delta.use_clamp = False
    tree.links.new(render_layers.outputs["Image"], receiver_delta.inputs[1])
    tree.links.new(baseline_node.outputs["Image"], receiver_delta.inputs[2])

    inverse_robot_alpha = tree.nodes.new("CompositorNodeMath")
    inverse_robot_alpha.operation = "SUBTRACT"
    inverse_robot_alpha.inputs[0].default_value = 1.0
    tree.links.new(robot_layers.outputs["Alpha"], inverse_robot_alpha.inputs[1])

    shadow_only_delta = tree.nodes.new("CompositorNodeMixRGB")
    shadow_only_delta.blend_type = "MULTIPLY"
    shadow_only_delta.inputs[0].default_value = 1.0
    shadow_only_delta.use_clamp = False
    tree.links.new(receiver_delta.outputs["Image"], shadow_only_delta.inputs[1])
    tree.links.new(inverse_robot_alpha.outputs[0], shadow_only_delta.inputs[2])

    masked_delta = tree.nodes.new("CompositorNodeMixRGB")
    masked_delta.blend_type = "MULTIPLY"
    masked_delta.inputs[0].default_value = 1.0
    masked_delta.use_clamp = False
    tree.links.new(shadow_only_delta.outputs["Image"], masked_delta.inputs[1])
    tree.links.new(visibility_node.outputs["Image"], masked_delta.inputs[2])

    receiver_result = tree.nodes.new("CompositorNodeMixRGB")
    receiver_result.blend_type = "ADD"
    receiver_result.inputs[0].default_value = 1.0
    receiver_result.use_clamp = False
    tree.links.new(static_node.outputs["Image"], receiver_result.inputs[1])
    tree.links.new(masked_delta.outputs["Image"], receiver_result.inputs[2])

    robot_over_result = tree.nodes.new("CompositorNodeAlphaOver")
    robot_over_result.inputs[0].default_value = 1.0
    tree.links.new(receiver_result.outputs["Image"], robot_over_result.inputs[1])
    tree.links.new(robot_layers.outputs["Image"], robot_over_result.inputs[2])

    composite = tree.nodes.new("CompositorNodeComposite")
    tree.links.new(robot_over_result.outputs["Image"], composite.inputs["Image"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", type=Path, required=True)
    parser.add_argument("--trajectory", type=Path, required=True)
    parser.add_argument("--visuals", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--width", type=int, default=512)
    parser.add_argument("--height", type=int, default=384)
    parser.add_argument("--fps", type=int, default=15)
    parser.add_argument("--max-frames", type=int)
    parser.add_argument("--static-samples", type=int, default=16)
    parser.add_argument("--dynamic-samples", type=int, default=4)
    parser.add_argument("--preview-only", action="store_true")
    parser.add_argument("--reuse-cache", action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])
    args.output.mkdir(parents=True, exist_ok=True)
    cache = args.output / "cache"
    cache.mkdir(parents=True, exist_ok=True)

    trajectory = np.load(args.trajectory)
    positions = trajectory["positions"]
    matrices = trajectory["matrices"]
    times = trajectory["times"]
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
    static_visible = {obj.name: not obj.hide_render for obj in room_meshes}

    robot_objects = []
    for index, row in enumerate(visual_rows):
        obj = import_stl(Path(row["mesh_path"]))
        obj.name = "G1_" + row["geom_name"]
        obj.data.materials.clear()
        obj.data.materials.append(material_for(str(index), row["rgba"]))
        obj.rotation_mode = "QUATERNION"
        robot_objects.append(obj)

    if args.preview_only:
        frame_indices = [len(positions) // 2]
    elif args.max_frames and args.max_frames < len(positions):
        frame_indices = np.linspace(
            0, len(positions) - 1, args.max_frames, dtype=int
        ).tolist()
    else:
        frame_indices = list(range(len(positions)))

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

    for obj in robot_objects:
        if obj.animation_data and obj.animation_data.action:
            for curve in obj.animation_data.action.fcurves:
                for keyframe in curve.keyframe_points:
                    keyframe.interpolation = "LINEAR"

    pelvis_index = next(
        index for index, row in enumerate(visual_rows) if row["geom_name"] == "g0_vis"
    )
    configure_color_and_camera(scene, positions[len(positions) // 2, pelvis_index])
    configure_render(scene, args.width, args.height, args.fps, args.dynamic_samples)
    scene.frame_start = 1
    scene.frame_end = len(frame_indices)
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

    for obj in room_meshes:
        obj.hide_render = obj not in receivers
    for obj in robot_objects:
        obj.hide_render = False
    dynamic_layer = scene.view_layers[0]
    receiver_collection = move_objects_to_collection(
        scene,
        "G1 contact receivers",
        receivers,
    )
    robot_layer = scene.view_layers.new("RobotAlpha")
    robot_receiver_layer_collection = find_layer_collection(
        robot_layer.layer_collection,
        receiver_collection,
    )
    if robot_receiver_layer_collection is None:
        raise RuntimeError("receiver collection unavailable in robot alpha layer")
    robot_receiver_layer_collection.exclude = True
    configure_delta_compositor(
        scene,
        static_background,
        receiver_baseline,
        receiver_visibility,
        dynamic_layer.name,
        robot_layer.name,
    )
    scene.eevee.taa_render_samples = args.dynamic_samples
    scene.eevee.taa_samples = args.dynamic_samples
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.image_settings.color_depth = "8"
    scene.render.filepath = str(args.output / "frame_")

    if args.preview_only:
        scene.render.filepath = str(args.output / "preview.png")
        bpy.ops.render.render(write_still=True)
    else:
        bpy.ops.render.render(animation=True)

    source_frame_times = [float(times[index]) for index in frame_indices]
    metadata = {
        "schema": "cached_bedroom_robot_render_v1",
        "scene": str(args.scene),
        "scene_sha256": sha256(args.scene),
        "trajectory": str(args.trajectory),
        "visuals": str(args.visuals),
        "frames": len(frame_indices),
        "fps": args.fps,
        "duration_s": len(frame_indices) / args.fps,
        "source_frames": len(positions),
        "source_frame_indices": frame_indices,
        "source_frame_times_s": source_frame_times,
        "resolution": [args.width, args.height],
        "engine": "BLENDER_EEVEE_NEXT",
        "static_samples": args.static_samples,
        "dynamic_samples": args.dynamic_samples,
        "render_strategy": "linear_exr_static_cache_plus_receiver_delta_and_robot_alpha",
        "static_background": str(static_background),
        "static_background_sha256": sha256(static_background),
        "receiver_baseline": str(receiver_baseline),
        "receiver_baseline_sha256": sha256(receiver_baseline),
        "receiver_visibility": str(receiver_visibility),
        "receiver_visibility_sha256": sha256(receiver_visibility),
        "contact_receiver_objects": [obj.name for obj in receivers],
        "room_mesh_count": len(room_meshes),
        "robot_visual_mesh_count": len(robot_objects),
        "south_wall_hidden_for_cutaway": True,
        "debug_sites_rendered": False,
        "collision_geometries_rendered": False,
        "background_compositing_used": True,
        "robot_compositing_mask": "dedicated_rgba_view_layer_alpha",
        "object_index_used_for_robot_compositing": False,
        "synthetic_motion_interpolation_used": False,
    }
    (args.output / "RENDER.json").write_text(json.dumps(metadata, indent=2) + "\n")


if __name__ == "__main__":
    main()
