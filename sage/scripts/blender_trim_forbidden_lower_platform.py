#!/usr/bin/env python3
"""Trim an oversized low platform while preserving the upper subject mesh."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-glb", required=True, type=Path)
    parser.add_argument("--output-glb", required=True, type=Path)
    parser.add_argument("--upper-start-ratio", type=float, default=0.42)
    parser.add_argument("--lower-cutoff-ratio", type=float, default=0.34)
    parser.add_argument("--footprint-expand", type=float, default=1.45)
    parser.add_argument(
        "--trim-mode",
        choices=(
            "outside_upper_footprint",
            "remove_low_slab",
            "remove_low_broad_components",
        ),
        default="outside_upper_footprint",
    )
    return parser.parse_args(argv)


def world_vertices(meshes: list[bpy.types.Object]) -> list[Vector]:
    return [obj.matrix_world @ vert.co for obj in meshes for vert in obj.data.vertices]


def trim(args: argparse.Namespace) -> dict:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(args.input_glb.resolve()))
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    points = world_vertices(meshes)
    if not points:
        raise RuntimeError("input GLB has no mesh vertices")
    minimum = Vector((min(v.x for v in points), min(v.y for v in points), min(v.z for v in points)))
    maximum = Vector((max(v.x for v in points), max(v.y for v in points), max(v.z for v in points)))
    height = max(float(maximum.z - minimum.z), 1e-8)
    upper_start = float(minimum.z) + height * float(args.upper_start_ratio)
    lower_cutoff = float(minimum.z) + height * float(args.lower_cutoff_ratio)
    upper = [point for point in points if float(point.z) >= upper_start]
    if len(upper) < 16:
        raise RuntimeError("not enough upper-subject vertices to define a safe footprint")
    upper_min_x, upper_max_x = min(v.x for v in upper), max(v.x for v in upper)
    upper_min_y, upper_max_y = min(v.y for v in upper), max(v.y for v in upper)
    center_x = 0.5 * (upper_min_x + upper_max_x)
    center_y = 0.5 * (upper_min_y + upper_max_y)
    half_x = max(
        0.5 * (upper_max_x - upper_min_x) * float(args.footprint_expand),
        0.16 * float(maximum.x - minimum.x),
    )
    half_y = max(
        0.5 * (upper_max_y - upper_min_y) * float(args.footprint_expand),
        0.16 * float(maximum.y - minimum.y),
    )
    keep_bounds = [
        float(center_x - half_x),
        float(center_y - half_y),
        float(center_x + half_x),
        float(center_y + half_y),
    ]
    removed_faces = 0
    original_faces = 0
    filled_boundary_faces = 0
    cut_boundary_edge_count = 0
    removed_component_count = 0
    for obj in meshes:
        inverse = obj.matrix_world.inverted()
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        doomed = []
        original_faces += len(bm.faces)
        if args.trim_mode == "remove_low_broad_components":
            pending = set(bm.faces)
            full_area = max(
                float(maximum.x - minimum.x) * float(maximum.y - minimum.y),
                1e-8,
            )
            while pending:
                first = pending.pop()
                component = [first]
                stack = [first]
                while stack:
                    face = stack.pop()
                    for edge in face.edges:
                        for neighbor in edge.link_faces:
                            if neighbor in pending:
                                pending.remove(neighbor)
                                component.append(neighbor)
                                stack.append(neighbor)
                component_points = [
                    obj.matrix_world @ vert.co
                    for face in component
                    for vert in face.verts
                ]
                comp_min_x = min(point.x for point in component_points)
                comp_max_x = max(point.x for point in component_points)
                comp_min_y = min(point.y for point in component_points)
                comp_max_y = max(point.y for point in component_points)
                comp_min_z = min(point.z for point in component_points)
                comp_max_z = max(point.z for point in component_points)
                area_ratio = float(
                    (comp_max_x - comp_min_x) * (comp_max_y - comp_min_y)
                ) / full_area
                height_ratio = float(comp_max_z - comp_min_z) / height
                is_low = float(comp_max_z) <= float(minimum.z) + 0.45 * height
                if (
                    len(component) >= 50
                    and area_ratio >= 0.55
                    and height_ratio <= 0.40
                    and is_low
                ):
                    doomed.extend(component)
                    removed_component_count += 1
        else:
            for face in bm.faces:
                world = [obj.matrix_world @ vert.co for vert in face.verts]
                center = sum(world, Vector()) / float(len(world))
                below = max(float(point.z) for point in world) <= lower_cutoff
                outside = not (
                    keep_bounds[0] <= float(center.x) <= keep_bounds[2]
                    and keep_bounds[1] <= float(center.y) <= keep_bounds[3]
                )
                selected = outside if args.trim_mode == "outside_upper_footprint" else True
                if below and selected:
                    doomed.append(face)
        removed_faces += len(doomed)
        if doomed:
            bmesh.ops.delete(bm, geom=doomed, context="FACES")
            loose = [vert for vert in bm.verts if not vert.link_faces]
            if loose:
                bmesh.ops.delete(bm, geom=loose, context="VERTS")
            boundary = (
                []
                if args.trim_mode == "remove_low_broad_components"
                else [edge for edge in bm.edges if len(edge.link_faces) == 1]
            )
            cut_boundary_edge_count += len(boundary)
            if boundary:
                before_fill = len(bm.faces)
                bmesh.ops.holes_fill(bm, edges=boundary, sides=0)
                filled_boundary_faces += len(bm.faces) - before_fill
                bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        bm.to_mesh(obj.data)
        bm.free()
        obj.data.update()
    if removed_faces <= 0:
        raise RuntimeError("safe platform trim found no removable low faces")
    removed_fraction = removed_faces / float(max(1, original_faces))
    if removed_fraction > 0.60:
        raise RuntimeError(
            f"platform trim would remove {removed_fraction:.3f} of faces; refusing unsafe edit"
        )
    final_points = world_vertices(meshes)
    final_minimum = Vector(
        (
            min(v.x for v in final_points),
            min(v.y for v in final_points),
            min(v.z for v in final_points),
        )
    )
    final_maximum = Vector(
        (
            max(v.x for v in final_points),
            max(v.y for v in final_points),
            max(v.z for v in final_points),
        )
    )
    final_extents = final_maximum - final_minimum
    args.output_glb.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=str(args.output_glb.resolve()),
        export_format="GLB",
        export_apply=True,
    )
    return {
        "schema": "scene_detail_lower_platform_trim_v1",
        "input_glb": str(args.input_glb.resolve()),
        "output_glb": str(args.output_glb.resolve()),
        "upper_start_ratio": float(args.upper_start_ratio),
        "lower_cutoff_ratio": float(args.lower_cutoff_ratio),
        "footprint_expand": float(args.footprint_expand),
        "trim_mode": str(args.trim_mode),
        "keep_bounds_xy": keep_bounds,
        "original_face_count": original_faces,
        "removed_face_count": removed_faces,
        "removed_face_fraction": round(removed_fraction, 6),
        "cut_boundary_edge_count": cut_boundary_edge_count,
        "filled_boundary_face_count": filled_boundary_faces,
        "cut_boundary_fill_applied": bool(filled_boundary_faces > 0),
        "removed_broad_low_component_count": removed_component_count,
        "component_gate": {
            "minimum_face_count": 50,
            "minimum_horizontal_area_ratio": 0.55,
            "maximum_height_ratio": 0.40,
            "maximum_top_height_fraction": 0.45,
        },
        "output_extents_xyz": [
            round(float(final_extents.x), 6),
            round(float(final_extents.y), 6),
            round(float(final_extents.z), 6),
        ],
        "safety_maximum_removed_face_fraction": 0.60,
    }


def main() -> None:
    args = parse_args()
    try:
        report = trim(args)
        print(json.dumps(report, indent=2), flush=True)
    except Exception as exc:
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}), flush=True)
        raise


if __name__ == "__main__":
    main()
