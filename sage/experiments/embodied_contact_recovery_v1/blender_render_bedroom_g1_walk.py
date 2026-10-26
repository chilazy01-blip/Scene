#!/usr/bin/env python3
"""Render recorded G1 visual transforms in the accepted bedroom GLB."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Vector
import numpy as np


def point_at(obj, target) -> None:
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()


def add_area(scene, name, location, target, energy, size, color) -> None:
    data = bpy.data.lights.new(name, "AREA")
    data.energy = energy
    data.shape = "DISK"
    data.size = size
    data.color = color
    obj = bpy.data.objects.new(name, data)
    scene.collection.objects.link(obj)
    obj.location = location
    point_at(obj, target)


def import_stl(path: Path):
    before = set(bpy.context.scene.objects)
    if hasattr(bpy.ops.wm, "stl_import"):
        bpy.ops.wm.stl_import(filepath=str(path))
    else:
        bpy.ops.import_mesh.stl(filepath=str(path))
    created = [obj for obj in bpy.context.scene.objects if obj not in before]
    if len(created) != 1:
        raise RuntimeError(f"Expected one STL object for {path}, got {len(created)}")
    return created[0]


def material_for(name: str, rgba: list[float]):
    material = bpy.data.materials.new("robot_material_" + name)
    material.diffuse_color = tuple(rgba)
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = tuple(rgba)
    bsdf.inputs["Metallic"].default_value = 0.28
    bsdf.inputs["Roughness"].default_value = 0.32
    return material


def set_transform(
    obj,
    position: np.ndarray,
    rotation: np.ndarray,
    mesh_pos: list[float],
    mesh_quat_wxyz: list[float],
) -> None:
    # MuJoCo compiles a raw mesh as R(q)^T @ (vertex - mesh_pos).
    # data.geom_xpos/xmat locate that compiled frame.  Blender imports the
    # original STL vertices, so append the same raw-to-compiled transform.
    w, x, y, z = mesh_quat_wxyz
    q_rotation = np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )
    raw_to_compiled = np.eye(4)
    raw_to_compiled[:3, :3] = q_rotation.T
    raw_to_compiled[:3, 3] = -q_rotation.T @ np.asarray(mesh_pos)
    geom_world = np.eye(4)
    geom_world[:3, :3] = rotation
    geom_world[:3, 3] = position
    obj.matrix_world = Matrix((geom_world @ raw_to_compiled).tolist())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", type=Path, required=True)
    parser.add_argument("--trajectory", type=Path, required=True)
    parser.add_argument("--visuals", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--width", type=int, default=960)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--samples", type=int, default=24)
    parser.add_argument("--fps", type=int, default=20)
    parser.add_argument("--max-frames", type=int)
    parser.add_argument("--preview-only", action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])
    args.output.mkdir(parents=True, exist_ok=True)

    trajectory = np.load(args.trajectory)
    positions = trajectory["positions"]
    matrices = trajectory["matrices"]
    visual_rows = json.loads(args.visuals.read_text())
    if positions.shape[:2] != (len(trajectory["times"]), len(visual_rows)):
        raise RuntimeError("trajectory/visual manifest shape mismatch")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(args.scene))
    scene = bpy.context.scene
    for obj in scene.objects:
        if obj.type in {"LIGHT", "CAMERA"}:
            obj.hide_render = True
        side = str(obj.get("architecture_wall", ""))
        if side == "south" or obj.name.startswith("wall_south_"):
            obj.hide_render = True

    world = bpy.data.worlds.new("Bedroom daylight")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.65, 0.72, 0.82, 1.0)
    world.node_tree.nodes["Background"].inputs[1].default_value = 0.25
    scene.world = world

    add_area(scene, "Natural window light", (0.6, 2.6, 2.35), (3.0, 2.5, 0.8), 360, 1.6, (0.83, 0.91, 1.0))
    add_area(scene, "Robot key light", (3.8, -1.2, 3.0), (2.6, 1.0, 0.8), 650, 3.0, (1.0, 0.88, 0.73))
    add_area(scene, "Ceiling bounce", (3.0, 2.6, 4.5), (3.0, 2.6, 0.0), 420, 3.0, (1.0, 0.94, 0.84))

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
    midpoint = positions[len(positions) // 2, pelvis_index]
    camera_data = bpy.data.cameras.new("Bedroom G1 camera")
    camera = bpy.data.objects.new(camera_data.name, camera_data)
    scene.collection.objects.link(camera)
    camera.location = (4.55, -3.35, 2.25)
    point_at(camera, (float(midpoint[0]), float(midpoint[1]) + 0.28, 0.82))
    camera_data.lens = 52
    camera_data.clip_start = 0.03
    camera_data.clip_end = 100
    scene.camera = camera

    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.eevee.taa_render_samples = args.samples
    scene.eevee.taa_samples = args.samples
    scene.eevee.use_raytracing = False
    scene.render.resolution_x = args.width
    scene.render.resolution_y = args.height
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.render.fps = args.fps
    scene.frame_start = 1
    scene.frame_end = len(frame_indices)
    scene.view_settings.view_transform = "AgX"
    try:
        scene.view_settings.look = "AgX - Medium High Contrast"
    except TypeError:
        pass
    scene.view_settings.exposure = -0.25
    scene.render.image_settings.color_mode = "RGB"
    scene.render.filepath = str(args.output / "frame_")
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.image_settings.color_depth = "8"
    scene.render.use_file_extension = True

    if args.preview_only:
        scene.frame_set(1)
        scene.render.filepath = str(args.output / "preview.png")
        bpy.ops.render.render(write_still=True)
    else:
        bpy.ops.render.render(animation=True)

    metadata = {
        "scene": str(args.scene),
        "trajectory": str(args.trajectory),
        "visuals": str(args.visuals),
        "frames": len(frame_indices),
        "fps": args.fps,
        "source_frames": len(positions),
        "resolution": [args.width, args.height],
        "engine": "BLENDER_EEVEE_NEXT",
        "south_wall_hidden_for_cutaway": True,
        "debug_sites_rendered": False,
        "collision_geometries_rendered": False,
        "robot_visual_mesh_count": len(robot_objects),
        "background_compositing_used": False,
    }
    (args.output / "RENDER.json").write_text(json.dumps(metadata, indent=2) + "\n")


if __name__ == "__main__":
    main()
