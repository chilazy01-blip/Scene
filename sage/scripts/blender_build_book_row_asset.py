#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--output-glb", required=True, type=Path)
    return parser.parse_args(argv)


def material(name: str, color: list[float], roughness: float) -> bpy.types.Material:
    value = bpy.data.materials.new(name)
    value.diffuse_color = tuple(float(item) for item in color)
    value.use_nodes = True
    bsdf = value.node_tree.nodes.get("Principled BSDF") if value.node_tree else None
    if bsdf:
        bsdf.inputs["Base Color"].default_value = value.diffuse_color
        bsdf.inputs["Roughness"].default_value = roughness
    return value


def box(name: str, center: tuple[float, float, float], dimensions: tuple[float, float, float], mat: bpy.types.Material) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(location=center)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = dimensions
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(mat)
    return obj


def main() -> None:
    args = parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    if not bool((plan.get("audit") or {}).get("ok")):
        raise RuntimeError("book row plan has not passed its arrangement audit")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    root = bpy.data.objects.new(str(plan["row_id"]), None)
    bpy.context.scene.collection.objects.link(root)
    root["component_category"] = "single_book"
    root["component_count"] = len(plan["books"])
    root["arrangement"] = str(plan["arrangement"])
    root["dynamic_physics_status"] = str(plan["dynamic_physics_status"])
    for book in plan["books"]:
        component_id = str(book["component_id"])
        dims = book["dimensions"]
        pose = book["local_pose"]
        width = float(dims["width"])
        depth = float(dims["length"])
        height = float(dims["height"])
        x = float(pose["x"])
        y = float(pose["y"])
        cover = material(f"{component_id}_cover", book["cover_color"], 0.66)
        pages = material(f"{component_id}_pages", book["page_color"], 0.86)
        page = box(
            f"{component_id}_page_block",
            (x, y + 0.002, height / 2.0),
            (max(0.006, width - 0.007), max(0.02, depth - 0.010), max(0.02, height - 0.014)),
            pages,
        )
        board = min(0.0035, width * 0.10)
        for suffix, side in (("left_cover", -1.0), ("right_cover", 1.0)):
            cover_obj = box(
                f"{component_id}_{suffix}",
                (x + side * (width - board) / 2.0, y, height / 2.0),
                (board, depth, height),
                cover,
            )
            cover_obj.parent = root
        spine = box(
            f"{component_id}_spine",
            (x, y - depth / 2.0 + board / 2.0, height / 2.0),
            (width, board, height),
            cover,
        )
        page.parent = root
        spine.parent = root
        for obj in (page, spine):
            obj["single_book_component_id"] = component_id
    args.output_glb.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=str(args.output_glb),
        export_format="GLB",
        export_extras=True,
    )
    if not args.output_glb.is_file() or args.output_glb.stat().st_size <= 0:
        raise RuntimeError("book row GLB export failed")
    print(json.dumps({"output_glb": str(args.output_glb), "books": len(plan["books"])}))


if __name__ == "__main__":
    main()
