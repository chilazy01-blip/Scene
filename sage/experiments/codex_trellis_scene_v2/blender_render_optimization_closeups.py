#!/usr/bin/env python3
"""Render isolated relationship close-ups from an optimized delivery GLB."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene-glb", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--resolution", type=int, default=768)
    return parser.parse_args(argv)


def look_at(obj: bpy.types.Object, target: Vector) -> None:
    obj.rotation_euler = (target - obj.location).to_track_quat("-Z", "Y").to_euler()


def bounds(objects: list[bpy.types.Object]) -> tuple[Vector, Vector]:
    points = [obj.matrix_world @ Vector(corner) for obj in objects for corner in obj.bound_box]
    return (
        Vector(tuple(min(point[axis] for point in points) for axis in range(3))),
        Vector(tuple(max(point[axis] for point in points) for axis in range(3))),
    )


def setup() -> None:
    world = bpy.data.worlds.new("OptimizationCloseupWorld")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.08, 0.09, 0.11, 1.0)
    world.node_tree.nodes["Background"].inputs[1].default_value = 0.3
    bpy.context.scene.world = world
    for name, location, energy, size in (
        ("Key", (2.0, -3.5, 4.0), 850.0, 4.0),
        ("Fill", (-3.0, -1.0, 2.5), 420.0, 3.0),
        ("Top", (0.0, 0.0, 5.0), 500.0, 3.0),
    ):
        data = bpy.data.lights.new(name, "AREA")
        data.energy = energy
        data.shape = "DISK"
        data.size = size
        light = bpy.data.objects.new(name, data)
        bpy.context.scene.collection.objects.link(light)
        light.location = location
        look_at(light, Vector((0.0, 0.0, 1.0)))
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    try:
        scene.view_settings.look = "AgX - Medium High Contrast"
    except TypeError:
        pass


def render_group(name: str, prefixes: tuple[str, ...], output: Path, resolution: int) -> dict:
    mesh_objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    selected = [obj for obj in mesh_objects if obj.name.startswith(prefixes)]
    if not selected:
        raise RuntimeError(f"no objects selected for {name}")
    for obj in mesh_objects:
        obj.hide_render = obj not in selected
    minimum, maximum = bounds(selected)
    center = (minimum + maximum) * 0.5
    extents = maximum - minimum
    camera_data = bpy.data.cameras.new(f"{name}Camera")
    camera = bpy.data.objects.new(f"{name}Camera", camera_data)
    bpy.context.scene.collection.objects.link(camera)
    lateral_offset = -extents.x * 0.42 if name == "desk_chair" else extents.x * 0.08
    distance = max(1.4, float(max(extents.x, extents.z)) * 1.75)
    camera.location = (
        center.x + lateral_offset,
        minimum.y - distance,
        center.z + max(0.12, extents.z * 0.05),
    )
    camera_data.lens = 62
    look_at(camera, center)
    bpy.context.scene.camera = camera
    bpy.context.scene.render.resolution_x = resolution
    bpy.context.scene.render.resolution_y = resolution
    bpy.context.scene.render.filepath = str(output)
    bpy.ops.render.render(write_still=True)
    bpy.data.objects.remove(camera, do_unlink=True)
    return {
        "name": name,
        "path": str(output.resolve()),
        "mesh_count": len(selected),
        "mesh_names": sorted(obj.name for obj in selected),
    }


def main() -> None:
    parsed = args()
    parsed.output_dir.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(parsed.scene_glb))
    setup()
    rows = [
        render_group(
            "bookcase_books",
            ("sdf_open_bookcase_geometry_", "sdf_books_1_geometry_", "sdf_books_2_geometry_", "sdf_books_3_geometry_"),
            parsed.output_dir / "optimized_bookcase_books_closeup.png",
            parsed.resolution,
        ),
        render_group(
            "desk_chair",
            ("explicit_desk_geometry_", "explicit_office_chair_geometry_"),
            parsed.output_dir / "optimized_desk_chair_closeup.png",
            parsed.resolution,
        ),
    ]
    (parsed.output_dir / "closeup_manifest.json").write_text(
        json.dumps({"schema": "scene-v2-optimization-closeups/v1", "views": rows}, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
