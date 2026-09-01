#!/usr/bin/env python3
"""Inject an auditable broad low platform into one GLB for localization tests."""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-glb", required=True, type=Path)
    parser.add_argument("--output-glb", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--variant", choices=("cylinder", "box"), required=True)
    return parser.parse_args(argv)


def _world_points(meshes: list[bpy.types.Object]) -> list[Vector]:
    return [
        obj.matrix_world @ vertex.co
        for obj in meshes
        for vertex in obj.data.vertices
    ]


def inject(args: argparse.Namespace) -> dict:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(args.input_glb.resolve()))
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    points = _world_points(meshes)
    if not points:
        raise RuntimeError("input GLB contains no mesh vertices")
    minimum = Vector(
        tuple(min(getattr(point, axis) for point in points) for axis in ("x", "y", "z"))
    )
    maximum = Vector(
        tuple(max(getattr(point, axis) for point in points) for axis in ("x", "y", "z"))
    )
    extents = maximum - minimum
    rng = random.Random(int(args.seed))
    width_factor = 1.16 + 0.08 * rng.random()
    length_factor = 1.16 + 0.08 * rng.random()
    thickness = max(float(extents.z) * (0.09 + 0.02 * rng.random()), 1e-4)
    center = (
        (float(minimum.x) + float(maximum.x)) * 0.5,
        (float(minimum.y) + float(maximum.y)) * 0.5,
        float(minimum.z) - thickness * 0.35,
    )
    if args.variant == "cylinder":
        bpy.ops.mesh.primitive_cylinder_add(
            vertices=64,
            radius=0.5,
            depth=1.0,
            location=center,
        )
    else:
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=center)
    defect = bpy.context.object
    defect.name = "SyntheticBroadLowPlatform"
    defect.scale = (
        max(float(extents.x) * width_factor, 1e-4),
        max(float(extents.y) * length_factor, 1e-4),
        thickness,
    )
    bpy.context.view_layer.objects.active = defect
    defect.select_set(True)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

    material = next(
        (
            slot.material
            for obj in meshes
            for slot in obj.material_slots
            if slot.material is not None
        ),
        None,
    )
    if material is None:
        material = bpy.data.materials.new("SyntheticDefectInheritedNeutral")
        material.diffuse_color = (0.55, 0.55, 0.55, 1.0)
    defect.data.materials.append(material)
    for polygon in defect.data.polygons:
        polygon.material_index = 0

    args.output_glb.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=str(args.output_glb.resolve()),
        export_format="GLB",
        export_apply=True,
    )
    report = {
        "schema": "scene_detail_synthetic_defect_ground_truth_v1",
        "input_glb": str(args.input_glb.resolve()),
        "output_glb": str(args.output_glb.resolve()),
        "seed": int(args.seed),
        "variant": str(args.variant),
        "defect_type": "broad_low_platform",
        "defect_object_name": str(defect.name),
        "defect_polygon_ids": list(range(len(defect.data.polygons))),
        "defect_polygon_count": len(defect.data.polygons),
        "protected_source_face_count": sum(len(obj.data.polygons) for obj in meshes),
        "source_bounds_min_xyz": [round(float(value), 9) for value in minimum],
        "source_bounds_max_xyz": [round(float(value), 9) for value in maximum],
        "injection": {
            "width_factor": round(width_factor, 6),
            "length_factor": round(length_factor, 6),
            "thickness_to_source_height": round(thickness / max(float(extents.z), 1e-8), 6),
            "intersects_source_lowest_region": True,
            "material_reused_from_source": material.name != "SyntheticDefectInheritedNeutral",
        },
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> None:
    report = inject(parse_args())
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
