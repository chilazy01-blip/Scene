#!/usr/bin/env python3
"""Render the dynamic upper-shelf books with a matched fixed-base G1 pose."""

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
)


def semantic_id(obj) -> str:
    for key in ("scene_object_id", "object_id", "instance_id", "semantic_id"):
        value = obj.get(key)
        if value:
            return str(value)
    return ""


def root_ancestor(obj):
    current = obj
    while current.parent is not None:
        current = current.parent
    return current


def descendants(root):
    result = []
    pending = list(root.children)
    while pending:
        obj = pending.pop()
        result.append(obj)
        pending.extend(obj.children)
    return result


def find_semantic_root(identifier: str):
    matches = [
        obj
        for obj in bpy.context.scene.objects
        if semantic_id(obj) == identifier or obj.name == identifier
    ]
    if not matches:
        raise RuntimeError(f"scene object not found: {identifier}")
    roots = {root_ancestor(obj) for obj in matches}
    if len(roots) != 1:
        raise RuntimeError(
            f"scene object {identifier} resolves to multiple roots: "
            + repr(sorted(obj.name for obj in roots))
        )
    return next(iter(roots))


def keep_for_action_vignette(obj) -> bool:
    identifier = semantic_id(obj)
    keep_exact = {"floor", "bookcase"}
    keep_prefixes = (
        "architecture_wall_south_",
        "baseboard_south_",
        "shelf_liner_",
        "bookend_",
        "leaning_book_",
        "upper_leaning_book",
        "upright_book_",
        "stacked_book_",
    )
    return identifier in keep_exact or identifier.startswith(keep_prefixes)


def delta_matrix(
    initial_position: np.ndarray,
    position: np.ndarray,
    rotation: np.ndarray,
) -> Matrix:
    translation_to_origin = np.eye(4)
    translation_to_origin[:3, 3] = -initial_position
    pose = np.eye(4)
    pose[:3, :3] = rotation
    pose[:3, 3] = position
    return Matrix((pose @ translation_to_origin).tolist())


def keyframe_matrix(obj, matrix: Matrix, frame: int) -> None:
    obj.matrix_world = matrix
    obj.rotation_mode = "QUATERNION"
    obj.keyframe_insert(data_path="location", frame=frame)
    obj.keyframe_insert(data_path="rotation_quaternion", frame=frame)
    obj.keyframe_insert(data_path="scale", frame=frame)


def set_linear_interpolation(obj) -> None:
    if not obj.animation_data or not obj.animation_data.action:
        return
    for curve in obj.animation_data.action.fcurves:
        for keyframe in curve.keyframe_points:
            keyframe.interpolation = "LINEAR"


def decimate_meshes(roots: list, ratio: float) -> list[dict]:
    rows = []
    seen = set()
    for root in roots:
        for obj in [root, *descendants(root)]:
            if obj.type != "MESH" or obj in seen:
                continue
            seen.add(obj)
            before = len(obj.data.polygons)
            if ratio < 0.999 and before > 2000:
                modifier = obj.modifiers.new("render_decimate", "DECIMATE")
                modifier.ratio = ratio
                bpy.context.view_layer.objects.active = obj
                obj.select_set(True)
                bpy.ops.object.modifier_apply(modifier=modifier.name)
                obj.select_set(False)
            rows.append(
                {
                    "object": obj.name,
                    "triangles_before": before,
                    "triangles_after": len(obj.data.polygons),
                }
            )
    return rows


def configure_static_compositor(scene, static_path: Path) -> None:
    scene.use_nodes = True
    tree = scene.node_tree
    tree.nodes.clear()
    render_layers = tree.nodes.new("CompositorNodeRLayers")
    background = tree.nodes.new("CompositorNodeImage")
    background.image = bpy.data.images.load(str(static_path), check_existing=False)
    alpha_over = tree.nodes.new("CompositorNodeAlphaOver")
    alpha_over.inputs[0].default_value = 1.0
    composite = tree.nodes.new("CompositorNodeComposite")
    tree.links.new(background.outputs["Image"], alpha_over.inputs[1])
    tree.links.new(render_layers.outputs["Image"], alpha_over.inputs[2])
    tree.links.new(alpha_over.outputs["Image"], composite.inputs["Image"])


def configure_depth_compositor(scene, static_path: Path) -> None:
    """Combine a cached static render and live geometry using their Z passes."""
    scene.use_nodes = True
    tree = scene.node_tree
    tree.nodes.clear()
    render_layers = tree.nodes.new("CompositorNodeRLayers")
    background = tree.nodes.new("CompositorNodeImage")
    background.image = bpy.data.images.load(str(static_path), check_existing=False)
    z_combine = tree.nodes.new("CompositorNodeZcombine")
    z_combine.use_alpha = True
    composite = tree.nodes.new("CompositorNodeComposite")
    background_image = background.outputs.get("Image") or background.outputs.get(
        "Combined"
    )
    background_depth = background.outputs.get("Depth") or background.outputs.get("Z")
    live_depth = render_layers.outputs.get("Depth") or render_layers.outputs.get("Z")
    if background_image is None or background_depth is None or live_depth is None:
        raise RuntimeError(
            "cached image/depth pass unavailable for Z compositor; outputs="
            + repr([socket.name for socket in background.outputs])
        )
    tree.links.new(background_image, z_combine.inputs[0])
    tree.links.new(background_depth, z_combine.inputs[1])
    tree.links.new(render_layers.outputs["Image"], z_combine.inputs[2])
    tree.links.new(live_depth, z_combine.inputs[3])
    tree.links.new(z_combine.outputs["Image"], composite.inputs["Image"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", type=Path, required=True)
    parser.add_argument("--trajectory", type=Path, required=True)
    parser.add_argument("--visuals", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=int, default=20)
    parser.add_argument("--samples", type=int, default=12)
    parser.add_argument(
        "--engine", choices=("workbench", "eevee"), default="workbench"
    )
    parser.add_argument("--book-decimate-ratio", type=float, default=0.12)
    parser.add_argument("--static-decimate-ratio", type=float, default=0.05)
    parser.add_argument(
        "--composite-static",
        action="store_true",
        help="Legacy fast mode; does not provide shared scene/robot depth.",
    )
    parser.add_argument(
        "--z-composite-static",
        action="store_true",
        help="Cache the static scene with depth and Z-combine dynamic geometry.",
    )
    parser.add_argument("--reuse-static", action="store_true")
    parser.add_argument("--frame-stride", type=int, default=1)
    parser.add_argument("--preview-index", type=int)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])
    if args.composite_static and args.z_composite_static:
        raise RuntimeError("choose at most one static compositing mode")
    args.output.mkdir(parents=True, exist_ok=True)

    trajectory = np.load(args.trajectory)
    times = trajectory["times"]
    robot_positions = trajectory["positions"]
    robot_matrices = trajectory["matrices"]
    book_names = [str(value) for value in trajectory["book_names"]]
    book_positions = trajectory["book_positions"]
    book_matrices = trajectory["book_matrices"]
    visual_rows = json.loads(args.visuals.read_text())
    if robot_positions.shape[:2] != (len(times), len(visual_rows)):
        raise RuntimeError("robot trajectory/visual manifest shape mismatch")
    if book_positions.shape[:2] != (len(times), len(book_names)):
        raise RuntimeError("book trajectory/name shape mismatch")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(args.scene))
    scene = bpy.context.scene
    for obj in scene.objects:
        if obj.type in {"LIGHT", "CAMERA"}:
            obj.hide_render = True
        elif obj.type == "MESH" and not keep_for_action_vignette(obj):
            obj.hide_render = True

    book_roots = [find_semantic_root(name) for name in book_names]
    if len(set(book_roots)) != len(book_roots):
        raise RuntimeError("book identifiers did not resolve to distinct roots")
    initial_book_world = [root.matrix_world.copy() for root in book_roots]
    decimation_rows = decimate_meshes(book_roots, args.book_decimate_ratio)

    robot_objects = []
    for index, row in enumerate(visual_rows):
        obj = import_stl(Path(row["mesh_path"]))
        obj.name = "G1_" + row["geom_name"]
        obj.data.materials.clear()
        obj.data.materials.append(material_for(str(index), row["rgba"]))
        obj.rotation_mode = "QUATERNION"
        robot_objects.append(obj)

    if args.preview_index is None:
        if args.frame_stride < 1:
            raise RuntimeError("frame stride must be positive")
        frame_indices = list(range(0, len(times), args.frame_stride))
        if frame_indices[-1] != len(times) - 1:
            frame_indices.append(len(times) - 1)
    else:
        if not 0 <= args.preview_index < len(times):
            raise RuntimeError("preview index outside trajectory")
        frame_indices = [args.preview_index]

    initial_physics_positions = book_positions[0]
    for output_frame, source_frame in enumerate(frame_indices, 1):
        for visual_index, obj in enumerate(robot_objects):
            set_transform(
                obj,
                robot_positions[source_frame, visual_index],
                robot_matrices[source_frame, visual_index],
                visual_rows[visual_index]["mujoco_mesh_pos"],
                visual_rows[visual_index]["mujoco_mesh_quat_wxyz"],
            )
            obj.keyframe_insert(data_path="location", frame=output_frame)
            obj.keyframe_insert(data_path="rotation_quaternion", frame=output_frame)
        for book_index, root in enumerate(book_roots):
            delta = delta_matrix(
                initial_physics_positions[book_index],
                book_positions[source_frame, book_index],
                book_matrices[source_frame, book_index],
            )
            keyframe_matrix(
                root,
                delta @ initial_book_world[book_index],
                output_frame,
            )

    for obj in [*robot_objects, *book_roots]:
        set_linear_interpolation(obj)

    configure_color_and_camera(scene, np.array([1.50, 0.42, 1.15]))
    scene.camera.location = (0.68, 1.68, 1.66)
    point_at(scene.camera, (1.50, 0.41, 1.16))
    scene.camera.data.lens = 55
    configure_render(scene, args.width, args.height, args.fps, args.samples)
    if args.engine == "workbench":
        scene.render.engine = "BLENDER_WORKBENCH"
        scene.display.shading.light = "STUDIO"
        scene.display.shading.studio_light = "paint.sl"
        scene.display.shading.color_type = "TEXTURE"
        scene.display.shading.show_shadows = True
        scene.display.shading.show_cavity = True
        scene.display.shading.cavity_type = "WORLD"
        scene.display.shading.curvature_ridge_factor = 1.2
        scene.display.shading.curvature_valley_factor = 0.8
        scene.display.shading.background_type = "WORLD"
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.image_settings.color_depth = "8"
    scene.frame_start = 1
    scene.frame_end = len(frame_indices)
    scene.render.filepath = str(args.output / "frame_")

    dynamic_book_objects = {
        obj for root in book_roots for obj in [root, *descendants(root)]
    }
    dynamic_book_meshes = {
        obj for obj in dynamic_book_objects if obj.type == "MESH"
    }
    static_meshes = {
        obj
        for obj in scene.objects
        if obj.type == "MESH"
        and obj not in dynamic_book_meshes
        and obj not in robot_objects
        and not obj.hide_render
    }
    static_path = args.output / (
        "static_background.exr" if args.z_composite_static else "static_background.png"
    )
    static_decimation_rows = decimate_meshes(
        list(static_meshes), args.static_decimate_ratio
    )
    if args.composite_static or args.z_composite_static:
        if not args.reuse_static or not static_path.is_file():
            for obj in static_meshes:
                obj.hide_render = False
            for obj in [*dynamic_book_meshes, *robot_objects]:
                obj.hide_render = True
            scene.use_nodes = False
            scene.render.film_transparent = False
            scene.render.filepath = str(static_path)
            if args.z_composite_static:
                scene.view_layers[0].use_pass_z = True
                scene.render.image_settings.file_format = "OPEN_EXR_MULTILAYER"
                scene.render.image_settings.color_mode = "RGBA"
                scene.render.image_settings.color_depth = "32"
            scene.frame_set(1)
            bpy.ops.render.render(write_still=True)
        for obj in static_meshes:
            obj.hide_render = True
        for obj in [*dynamic_book_meshes, *robot_objects]:
            obj.hide_render = False
        scene.render.image_settings.file_format = "PNG"
        scene.render.image_settings.color_mode = "RGB"
        scene.render.image_settings.color_depth = "8"
        if args.z_composite_static:
            scene.view_layers[0].use_pass_z = True
            configure_depth_compositor(scene, static_path)
        else:
            configure_static_compositor(scene, static_path)
        scene.render.film_transparent = True
    else:
        for obj in [*static_meshes, *dynamic_book_meshes, *robot_objects]:
            obj.hide_render = False
        scene.use_nodes = False
        scene.render.film_transparent = False
    scene.render.filepath = str(args.output / "frame_")

    if args.preview_index is not None:
        scene.frame_set(1)
        scene.render.filepath = str(args.output / f"preview_{args.preview_index:03d}.png")
        bpy.ops.render.render(write_still=True)
    else:
        bpy.ops.render.render(animation=True)

    render_manifest = {
        "schema": "bedroom_g1_book_push_render_v1",
        "scene": str(args.scene),
        "trajectory": str(args.trajectory),
        "book_objects": book_names,
        "robot_visual_count": len(robot_objects),
        "source_frames": frame_indices,
        "width": args.width,
        "height": args.height,
        "fps": args.fps,
        "camera_location": list(scene.camera.location),
        "camera_target": [1.50, 0.41, 1.16],
        "renderer": scene.render.engine,
        "samples": args.samples,
        "depth_consistent_unified_render": not (
            args.composite_static or args.z_composite_static
        ),
        "depth_consistent_z_composite": args.z_composite_static,
        "static_background": (
            str(static_path)
            if args.composite_static or args.z_composite_static
            else None
        ),
        "static_background_reused": (
            args.reuse_static
            if args.composite_static or args.z_composite_static
            else False
        ),
        "dynamic_book_decimation": decimation_rows,
        "static_scene_decimation": static_decimation_rows,
    }
    (args.output / "RENDER_MANIFEST.json").write_text(
        json.dumps(render_manifest, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
