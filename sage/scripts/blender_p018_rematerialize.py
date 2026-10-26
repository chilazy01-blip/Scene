#!/usr/bin/env python3
"""Apply an explicit P018 material-slot plan without modifying geometry."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from pathlib import Path

import bpy


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-glb", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output-glb", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    return parser.parse_args(argv)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def reset() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for datablocks in (bpy.data.meshes, bpy.data.materials, bpy.data.images):
        for datablock in list(datablocks):
            if datablock.users == 0:
                datablocks.remove(datablock)


def mesh_signature() -> dict:
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    digest = hashlib.sha256()
    vertex_count = 0
    polygon_count = 0
    for obj in sorted(meshes, key=lambda item: item.name):
        mesh = obj.data
        digest.update(obj.name.encode("utf-8"))
        digest.update(mesh.name.encode("utf-8"))
        for row in obj.matrix_world:
            for value in row:
                digest.update(f"{float(value):.9f},".encode("ascii"))
        for vertex in mesh.vertices:
            vertex_count += 1
            digest.update(
                ("%.9f,%.9f,%.9f;" % tuple(float(value) for value in vertex.co)).encode(
                    "ascii"
                )
            )
        for polygon in mesh.polygons:
            polygon_count += 1
            digest.update((",".join(str(int(index)) for index in polygon.vertices) + ";").encode("ascii"))
    return {
        "sha256": digest.hexdigest(),
        "mesh_count": len(meshes),
        "vertex_count": vertex_count,
        "polygon_count": polygon_count,
    }


def slot_uv_metrics(material: bpy.types.Material) -> dict:
    world_area = 0.0
    uv_area = 0.0
    polygon_count = 0
    missing_uv = 0
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH" or material.name not in obj.data.materials:
            continue
        slot_indices = {
            index for index, candidate in enumerate(obj.data.materials) if candidate == material
        }
        uv_layer = obj.data.uv_layers.active
        for polygon in obj.data.polygons:
            if polygon.material_index not in slot_indices:
                continue
            polygon_count += 1
            world_area += float(polygon.area) * abs(float(obj.scale.x * obj.scale.y))
            if uv_layer is None or len(polygon.loop_indices) < 3:
                missing_uv += 1
                continue
            points = [uv_layer.data[index].uv for index in polygon.loop_indices]
            anchor = points[0]
            for index in range(1, len(points) - 1):
                a = points[index] - anchor
                b = points[index + 1] - anchor
                uv_area += abs(float(a.x * b.y - a.y * b.x)) * 0.5
    return {
        "polygon_count": polygon_count,
        "missing_uv_polygon_count": missing_uv,
        "uv_complete": polygon_count > 0 and missing_uv == 0,
        "world_area_proxy_m2": world_area,
        "uv_area": uv_area,
    }


def principled_input(node: bpy.types.Node, name: str):
    socket = node.inputs.get(name)
    if socket is None:
        raise RuntimeError(f"Principled BSDF has no input {name}")
    return socket


def make_material(binding: dict, package: dict) -> tuple[bpy.types.Material, dict]:
    material = bpy.data.materials.new(f"p018_{package['package_id']}_{binding['binding_id']}")
    material.use_nodes = True
    material.use_backface_culling = not bool(package["pbr"].get("double_sided", False))
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    pbr = package["pbr"]
    base = list(pbr["base_color_srgb"])
    if len(base) == 3:
        base.append(1.0)
    principled_input(shader, "Base Color").default_value = tuple(float(value) for value in base)
    principled_input(shader, "Metallic").default_value = float(pbr["metallic"])
    principled_input(shader, "Roughness").default_value = float(pbr["roughness"])
    principled_input(shader, "Alpha").default_value = float(base[3])
    if shader.inputs.get("IOR") is not None:
        shader.inputs["IOR"].default_value = float(pbr.get("ior", 1.5))
    links.new(shader.outputs["BSDF"], output.inputs["Surface"])
    texture_path = binding.get("texture_path")
    image_report = None
    if texture_path:
        image = bpy.data.images.load(str(Path(texture_path).resolve()), check_existing=False)
        image.colorspace_settings.name = "sRGB"
        texture = nodes.new("ShaderNodeTexImage")
        texture.image = image
        texture.interpolation = "Linear"
        texture.extension = "REPEAT"
        links.new(texture.outputs["Color"], principled_input(shader, "Base Color"))
        image_report = {
            "path": str(Path(texture_path).resolve()),
            "sha256": sha256(Path(texture_path)),
            "color_space": image.colorspace_settings.name,
            "size": [int(image.size[0]), int(image.size[1])],
        }
    material["p018_package_id"] = str(package["package_id"])
    material["p018_package_hash"] = str(package["package_hash"])
    material["p018_semantic_role"] = str(binding["semantic_role"])
    material["p018_base_color_color_space"] = "sRGB"
    return material, {
        "created_material": material.name,
        "image": image_report,
        "alpha_mode": str(pbr.get("alpha_mode") or "OPAQUE"),
        "double_sided": bool(pbr.get("double_sided", False)),
    }


def main() -> int:
    args = parse_args()
    started = time.perf_counter()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    packages = {str(row["package_id"]): row for row in plan["packages"]}
    reset()
    bpy.ops.import_scene.gltf(filepath=str(args.source_glb.resolve()))
    bpy.context.view_layer.update()
    before = mesh_signature()
    material_names_before = sorted(material.name for material in bpy.data.materials)
    reports = []
    for binding in plan["bindings"]:
        source_names = [str(name) for name in binding["source_material_names"]]
        found = [bpy.data.materials.get(name) for name in source_names]
        missing = [name for name, material in zip(source_names, found) if material is None]
        if missing:
            raise RuntimeError(f"material binding {binding['binding_id']} missing {missing}")
        package = packages[str(binding["target_package_id"])]
        replacement, report = make_material(binding, package)
        replaced_slots = 0
        uv_reports = []
        for source in found:
            assert source is not None
            uv_reports.append({"source_material": source.name, **slot_uv_metrics(source)})
            for obj in bpy.context.scene.objects:
                if obj.type != "MESH":
                    continue
                for index, candidate in enumerate(obj.data.materials):
                    if candidate == source:
                        obj.data.materials[index] = replacement
                        replaced_slots += 1
        if replaced_slots == 0:
            raise RuntimeError(f"material binding {binding['binding_id']} matched no mesh slots")
        reports.append(
            {
                "binding_id": binding["binding_id"],
                "semantic_role": binding["semantic_role"],
                "source_material_names": source_names,
                "target_package_id": package["package_id"],
                "replaced_mesh_slot_count": replaced_slots,
                "uv": uv_reports,
                **report,
            }
        )
    bpy.context.view_layer.update()
    after = mesh_signature()
    if before != after:
        raise RuntimeError(f"geometry changed during rematerialization: {before} != {after}")
    args.output_glb.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=str(args.output_glb.resolve()),
        export_format="GLB",
        export_materials="EXPORT",
        export_image_format="AUTO",
        export_extras=True,
        export_yup=True,
    )
    report = {
        "schema": "scene-v2-p018-blender-rematerialization/v1",
        "ok": True,
        "source_glb": str(args.source_glb.resolve()),
        "source_glb_sha256": sha256(args.source_glb),
        "output_glb": str(args.output_glb.resolve()),
        "output_glb_sha256": sha256(args.output_glb),
        "blender_version": bpy.app.version_string,
        "geometry_before": before,
        "geometry_after_in_memory": after,
        "geometry_unchanged_before_export": before == after,
        "source_material_count": len(material_names_before),
        "output_material_count_in_memory": len(bpy.data.materials),
        "bindings": reports,
        "elapsed_seconds": round(time.perf_counter() - started, 6),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
