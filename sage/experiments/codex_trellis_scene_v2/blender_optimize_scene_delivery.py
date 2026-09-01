#!/usr/bin/env python3
"""Decimate a complete GLB by per-object budget while preserving scene semantics."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    return parser.parse_args(argv)


def bounds(obj: bpy.types.Object) -> tuple[list[float], list[float]]:
    coordinates = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    minimum = [min(point[index] for point in coordinates) for index in range(3)]
    maximum = [max(point[index] for point in coordinates) for index in range(3)]
    return minimum, maximum


def local_bounds(obj: bpy.types.Object) -> tuple[list[float], list[float]]:
    minimum = [min(vertex.co[index] for vertex in obj.data.vertices) for index in range(3)]
    maximum = [max(vertex.co[index] for vertex in obj.data.vertices) for index in range(3)]
    return minimum, maximum


def restore_local_bounds(
    obj: bpy.types.Object,
    expected: tuple[list[float], list[float]],
) -> None:
    actual = local_bounds(obj)
    expected_center = [(expected[0][axis] + expected[1][axis]) * 0.5 for axis in range(3)]
    actual_center = [(actual[0][axis] + actual[1][axis]) * 0.5 for axis in range(3)]
    scales = []
    for axis in range(3):
        expected_extent = expected[1][axis] - expected[0][axis]
        actual_extent = actual[1][axis] - actual[0][axis]
        scales.append(expected_extent / actual_extent if actual_extent > 1e-12 else 1.0)
    for vertex in obj.data.vertices:
        for axis in range(3):
            vertex.co[axis] = (vertex.co[axis] - actual_center[axis]) * scales[axis] + expected_center[axis]
    obj.data.update()


def restore_world_bounds(
    obj: bpy.types.Object,
    expected: tuple[list[float], list[float]],
) -> None:
    matrix = obj.matrix_world.copy()
    inverse = matrix.inverted()
    points = [matrix @ vertex.co for vertex in obj.data.vertices]
    actual_min = [min(point[axis] for point in points) for axis in range(3)]
    actual_max = [max(point[axis] for point in points) for axis in range(3)]
    actual_center = [(actual_min[axis] + actual_max[axis]) * 0.5 for axis in range(3)]
    expected_center = [(expected[0][axis] + expected[1][axis]) * 0.5 for axis in range(3)]
    scales = []
    for axis in range(3):
        expected_extent = expected[1][axis] - expected[0][axis]
        actual_extent = actual_max[axis] - actual_min[axis]
        scales.append(expected_extent / actual_extent if actual_extent > 1e-12 else 1.0)
    for vertex, point in zip(obj.data.vertices, points):
        for axis in range(3):
            point[axis] = (point[axis] - actual_center[axis]) * scales[axis] + expected_center[axis]
        vertex.co = inverse @ point
    obj.data.update()


def object_for_geometry(name: str) -> bpy.types.Object | None:
    exact = bpy.data.objects.get(name)
    if exact is not None and exact.type == "MESH":
        return exact
    candidates = [obj for obj in bpy.context.scene.objects if obj.type == "MESH" and (obj.name == name or obj.data.name == name)]
    return candidates[0] if len(candidates) == 1 else None


def mesh_signature(obj: bpy.types.Object) -> str:
    digest = hashlib.sha256()
    digest.update(str(len(obj.data.vertices)).encode())
    digest.update(str(len(obj.data.polygons)).encode())
    for vertex in obj.data.vertices:
        digest.update(("%.7g,%.7g,%.7g;" % tuple(vertex.co)).encode())
    for polygon in obj.data.polygons:
        digest.update((",".join(str(value) for value in polygon.vertices) + ";").encode())
    return digest.hexdigest()


def main() -> None:
    args = parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(config["source_glb"]))
    verified_instance_sources = {}
    for first_id, second_id in config.get("duplicate_instance_pairs", []):
        first = next((obj for obj in bpy.context.scene.objects if obj.type == "MESH" and obj.name.startswith(f"{first_id}_geometry_")), None)
        second = next((obj for obj in bpy.context.scene.objects if obj.type == "MESH" and obj.name.startswith(f"{second_id}_geometry_")), None)
        if first is None or second is None:
            raise RuntimeError(f"duplicate instance source missing: {first_id}/{second_id}")
        first_signature = mesh_signature(first)
        second_signature = mesh_signature(second)
        if first_signature != second_signature:
            raise RuntimeError(f"duplicate instance source differs before optimization: {first_id}/{second_id}")
        verified_instance_sources[(first_id, second_id)] = first_signature
    rows = []
    for item in config["meshes"]:
        obj = object_for_geometry(str(item["geometry_name"]))
        if obj is None:
            raise RuntimeError(f"cannot resolve mesh object: {item['geometry_name']}")
        before_faces = len(obj.data.polygons)
        before_bounds = bounds(obj)
        before_local_bounds = local_bounds(obj)
        uv_before = len(obj.data.uv_layers)
        materials_before = len(obj.data.materials)
        target = int(item["target_faces"])
        ratio = min(1.0, max(0.01, target / max(1, before_faces)))
        if ratio < 0.999 and before_faces >= 16:
            bpy.context.view_layer.objects.active = obj
            obj.select_set(True)
            modifier = obj.modifiers.new(name="SceneV2BudgetDecimate", type="DECIMATE")
            modifier.decimate_type = "COLLAPSE"
            modifier.ratio = ratio
            modifier.use_collapse_triangulate = True
            bpy.ops.object.modifier_apply(modifier=modifier.name)
            obj.select_set(False)
        restore_local_bounds(obj, before_local_bounds)
        restore_world_bounds(obj, before_bounds)
        obj.data.validate(clean_customdata=False)
        after_faces = len(obj.data.polygons)
        after_bounds = bounds(obj)
        zero_area = sum(1 for polygon in obj.data.polygons if polygon.area <= 1e-14)
        rows.append(
            {
                **item,
                "resolved_object": obj.name,
                "before_faces": before_faces,
                "after_faces": after_faces,
                "ratio": round(ratio, 8),
                "world_bounds_before": before_bounds,
                "world_bounds_after": after_bounds,
                "canonical_local_bounds_restored": True,
                "canonical_world_bounds_restored": True,
                "uv_layers_before": uv_before,
                "uv_layers_after": len(obj.data.uv_layers),
                "materials_before": materials_before,
                "materials_after": len(obj.data.materials),
                "zero_area_faces_after": zero_area,
                "finite_normals_after": all(all(math.isfinite(value) for value in polygon.normal) for polygon in obj.data.polygons),
            }
        )

    instance_rows = []
    for first_id, second_id in config.get("duplicate_instance_pairs", []):
        first = next((obj for obj in bpy.context.scene.objects if obj.type == "MESH" and obj.name.startswith(f"{first_id}_geometry_")), None)
        second = next((obj for obj in bpy.context.scene.objects if obj.type == "MESH" and obj.name.startswith(f"{second_id}_geometry_")), None)
        if first is None or second is None:
            instance_rows.append({"pair": [first_id, second_id], "ok": False, "reason": "mesh_missing"})
            continue
        second.data = first.data
        instance_rows.append(
            {
                "pair": [first_id, second_id],
                "ok": True,
                "source_mesh_signature": verified_instance_sources[(first_id, second_id)],
                "optimized_shared_mesh_signature": mesh_signature(first),
            }
        )

    image_rows = []
    maximum = int(config["texture_max_resolution"])
    for image in list(bpy.data.images):
        before = [int(image.size[0]), int(image.size[1])]
        if max(before) > maximum and min(before) > 0:
            scale = maximum / max(before)
            image.scale(max(1, int(round(before[0] * scale))), max(1, int(round(before[1] * scale))))
            image.pack()
        image_rows.append({"name": image.name, "before": before, "after": [int(image.size[0]), int(image.size[1])], "packed": image.packed_file is not None})

    args.output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=str(args.output),
        export_format="GLB",
        export_apply=True,
        export_materials="EXPORT",
        export_extras=True,
        export_image_format="AUTO",
    )
    report = {
        "schema": "scene-v2-blender-delivery-optimization/v1",
        "ok": all(row["uv_layers_after"] >= row["uv_layers_before"] and row["materials_after"] == row["materials_before"] and row["zero_area_faces_after"] == 0 and row["finite_normals_after"] for row in rows) and all(row["ok"] for row in instance_rows),
        "source_glb": config["source_glb"],
        "output_glb": str(args.output.resolve()),
        "output_bytes": args.output.stat().st_size,
        "meshes": rows,
        "instances": instance_rows,
        "images": image_rows,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not report["ok"]:
        raise RuntimeError("optimized GLB failed Blender-local UV/material/normal/instance checks")


if __name__ == "__main__":
    main()
