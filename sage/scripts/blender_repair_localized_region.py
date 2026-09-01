#!/usr/bin/env python3
"""Apply an evidence-bound face repair without modifying unrelated mesh regions."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import bpy
import bmesh
from mathutils import Matrix, Vector


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-glb", required=True, type=Path)
    parser.add_argument("--localization", required=True, type=Path)
    parser.add_argument("--output-glb", required=True, type=Path)
    return parser.parse_args(argv)


def _plain(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    try:
        return [round(float(item), 9) for item in value]
    except Exception:
        return str(value)


def _material_signature() -> tuple[str, dict]:
    rows = []
    for material in sorted(bpy.data.materials, key=lambda item: item.name):
        row = {
            "name": str(material.name),
            "diffuse_color": _plain(material.diffuse_color),
            "use_nodes": bool(material.use_nodes),
            "nodes": [],
        }
        if material.use_nodes and material.node_tree is not None:
            for node in sorted(material.node_tree.nodes, key=lambda item: item.name):
                node_row = {
                    "name": str(node.name),
                    "type": str(node.bl_idname),
                    "inputs": [],
                }
                for socket in node.inputs:
                    if hasattr(socket, "default_value"):
                        node_row["inputs"].append(
                            {"name": str(socket.name), "value": _plain(socket.default_value)}
                        )
                image = getattr(node, "image", None)
                if image is not None:
                    node_row["image"] = {
                        "name": str(image.name),
                        "filepath": str(image.filepath or ""),
                        "packed": bool(image.packed_file),
                        "size": [int(image.size[0]), int(image.size[1])],
                    }
                row["nodes"].append(node_row)
        rows.append(row)
    payload = {"materials": rows}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), payload


def _world_extents(meshes: list[bpy.types.Object]) -> list[float]:
    points = [obj.matrix_world @ vert.co for obj in meshes for vert in obj.data.vertices]
    if not points:
        return [0.0, 0.0, 0.0]
    return [
        float(max(getattr(point, axis) for point in points) - min(getattr(point, axis) for point in points))
        for axis in ("x", "y", "z")
    ]


def repair(args: argparse.Namespace) -> dict:
    localization = json.loads(args.localization.read_text(encoding="utf-8"))
    if not localization.get("accepted_for_automatic_repair"):
        raise RuntimeError("localization is not accepted for automatic repair")
    selected = localization.get("selected_seed_polygons") or {}
    if not selected:
        raise RuntimeError("localization has no selected seed polygons")
    root_matrix = Matrix(localization["normalization_root_matrix"])
    z_min = float(localization["geometry_limits"]["normalized_z_min"])
    z_max = float(localization["geometry_limits"]["normalized_z_max"])
    z_ratio = float(localization["repair_policy"]["maximum_face_z_ratio"])
    z_limit = z_min + max(z_max - z_min, 1e-8) * z_ratio
    maximum_removed_fraction = float(
        localization["repair_policy"].get("maximum_removed_face_fraction", 0.50)
    )

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(args.input_glb.resolve()))
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    before_material_hash, material_payload = _material_signature()
    original_faces = sum(len(obj.data.polygons) for obj in meshes)
    removed_faces = 0
    seed_faces = 0
    filled_faces = 0
    repair_boundary_edges = 0
    edited_objects = []
    removed_faces_by_object = {}
    surviving_material_assignments_preserved = True

    for obj in meshes:
        polygon_ids = selected.get(str(obj.name))
        if not polygon_ids:
            continue
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bm.faces.ensure_lookup_table()
        bm.faces.index_update()
        original_polygon_layer = bm.faces.layers.int.new(
            "scene_detail_original_polygon_index"
        )
        original_material_by_polygon = {}
        for face in bm.faces:
            face[original_polygon_layer] = int(face.index)
            original_material_by_polygon[int(face.index)] = int(face.material_index)
        valid_ids = sorted({int(index) for index in polygon_ids if 0 <= int(index) < len(bm.faces)})
        if not valid_ids:
            bm.free()
            continue
        seeds = {bm.faces[index] for index in valid_ids}
        seed_faces += len(seeds)
        normalized_matrix = root_matrix @ obj.matrix_world

        def is_low(face) -> bool:
            return max(float((normalized_matrix @ vert.co).z) for vert in face.verts) <= z_limit + 1e-7

        doomed = {face for face in seeds if is_low(face)}
        queue = list(doomed)
        while queue:
            face = queue.pop()
            for edge in face.edges:
                for neighbor in edge.link_faces:
                    if neighbor not in doomed and is_low(neighbor):
                        doomed.add(neighbor)
                        queue.append(neighbor)
        if not doomed:
            bm.free()
            continue
        boundary = {
            edge
            for face in doomed
            for edge in face.edges
            if any(neighbor not in doomed for neighbor in edge.link_faces)
        }
        removed_faces += len(doomed)
        removed_faces_by_object[str(obj.name)] = len(doomed)
        bmesh.ops.delete(bm, geom=list(doomed), context="FACES")
        loose = [vert for vert in bm.verts if not vert.link_faces]
        if loose:
            bmesh.ops.delete(bm, geom=loose, context="VERTS")
        boundary = [edge for edge in boundary if edge.is_valid and len(edge.link_faces) == 1]
        repair_boundary_edges += len(boundary)
        if boundary:
            before_fill = len(bm.faces)
            fill_result = bmesh.ops.holes_fill(bm, edges=boundary, sides=0)
            for face in fill_result.get("faces", []):
                face[original_polygon_layer] = -1
            filled_faces += len(bm.faces) - before_fill
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        for face in bm.faces:
            original_index = int(face[original_polygon_layer])
            if original_index < 0:
                continue
            if int(face.material_index) != original_material_by_polygon[original_index]:
                surviving_material_assignments_preserved = False
                break
        bm.faces.layers.int.remove(original_polygon_layer)
        bm.to_mesh(obj.data)
        bm.free()
        obj.data.update()
        edited_objects.append(str(obj.name))

    if removed_faces <= 0:
        raise RuntimeError("localized repair found no removable evidence-bound faces")
    removed_fraction = removed_faces / float(max(1, original_faces))
    if removed_fraction > maximum_removed_fraction:
        raise RuntimeError(
            f"localized repair would remove {removed_fraction:.3f} of faces; "
            f"limit is {maximum_removed_fraction:.3f}"
        )
    after_material_hash, _ = _material_signature()
    if before_material_hash != after_material_hash:
        raise RuntimeError("localized geometry edit unexpectedly changed material signature")
    if not surviving_material_assignments_preserved:
        raise RuntimeError(
            "localized geometry edit unexpectedly changed a surviving face material assignment"
        )

    args.output_glb.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=str(args.output_glb.resolve()),
        export_format="GLB",
        export_apply=True,
    )
    extents = _world_extents(meshes)
    return {
        "schema": "scene_detail_localized_mesh_repair_v1",
        "input_glb": str(args.input_glb.resolve()),
        "output_glb": str(args.output_glb.resolve()),
        "localization_path": str(args.localization.resolve()),
        "localization_schema": localization.get("schema"),
        "evidence_grounded": bool(localization.get("evidence_grounded")),
        "multi_view_confirmed": bool(localization.get("multi_view_confirmed")),
        "supporting_views": list(localization.get("supporting_views") or []),
        "seed_face_count": seed_faces,
        "expanded_removed_face_count": removed_faces,
        "original_face_count": original_faces,
        "removed_face_fraction": round(removed_fraction, 6),
        "repair_boundary_edge_count": repair_boundary_edges,
        "filled_boundary_face_count": filled_faces,
        "edited_objects": edited_objects,
        "removed_faces_by_object": removed_faces_by_object,
        "maximum_normalized_z_ratio": z_ratio,
        "maximum_removed_face_fraction": maximum_removed_fraction,
        "output_extents_xyz": [round(value, 6) for value in extents],
        "material_preservation": {
            "verified": before_material_hash == after_material_hash,
            "before_sha256": before_material_hash,
            "after_sha256": after_material_hash,
            "material_count": len(material_payload["materials"]),
            "surviving_face_material_assignments_preserved": (
                surviving_material_assignments_preserved
            ),
            "texture_and_node_parameters_modified": False,
        },
        "scope_certificate": {
            "only_seed_connected_faces_below_height_limit_removed": True,
            "preexisting_open_boundaries_filled": False,
            "whole_asset_regeneration_used": False,
        },
    }


def main() -> None:
    args = parse_args()
    report = repair(args)
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
