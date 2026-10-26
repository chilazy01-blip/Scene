#!/usr/bin/env python3
"""Audit rendered G1 meshes against the current generated bookcase geometry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import bpy
from mathutils import Matrix
from mathutils.bvhtree import BVHTree
import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parent))
from blender_render_bedroom_g1_walk import import_stl, set_transform  # noqa: E402


STATIC_IDS = (
    "bookcase",
    "shelf_liner_2",
    "bookend_2",
    "upper_leaning_book",
)


def semantic_id(obj) -> str:
    return str(obj.get("scene_object_id", ""))


def world_bvh(obj) -> BVHTree:
    vertices = [obj.matrix_world @ vertex.co for vertex in obj.data.vertices]
    polygons = [tuple(poly.vertices) for poly in obj.data.polygons]
    return BVHTree.FromPolygons(vertices, polygons, all_triangles=True)


def world_bounds(obj) -> dict[str, list[float]]:
    points = np.asarray([obj.matrix_world @ vertex.co for vertex in obj.data.vertices])
    return {
        "min": points.min(axis=0).tolist(),
        "max": points.max(axis=0).tolist(),
    }


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


def delta_matrix(initial_position, position, rotation) -> Matrix:
    translation_to_origin = np.eye(4)
    translation_to_origin[:3, 3] = -initial_position
    pose = np.eye(4)
    pose[:3, :3] = rotation
    pose[:3, 3] = position
    return Matrix((pose @ translation_to_origin).tolist())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", type=Path, required=True)
    parser.add_argument("--trajectory", type=Path, required=True)
    parser.add_argument("--visuals", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frame-stride", type=int, default=2)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])
    args.output.parent.mkdir(parents=True, exist_ok=True)

    trajectory = np.load(args.trajectory)
    visual_rows = json.loads(args.visuals.read_text())
    robot_indices = tuple(range(len(visual_rows)))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(args.scene))

    static_objects = []
    for identifier in STATIC_IDS:
        matches = [
            obj
            for obj in bpy.context.scene.objects
            if obj.type == "MESH" and semantic_id(obj) == identifier
        ]
        if len(matches) != 1:
            raise RuntimeError(f"expected one mesh for {identifier}, got {len(matches)}")
        static_objects.append(matches[0])
    static_bvhs = [(obj, world_bvh(obj)) for obj in static_objects]

    book_names = [str(value) for value in trajectory["book_names"]]
    dynamic_books = []
    for name in book_names:
        matches = [
            obj for obj in bpy.context.scene.objects if semantic_id(obj) == name
        ]
        roots = {root_ancestor(obj) for obj in matches}
        if len(roots) != 1:
            raise RuntimeError(f"expected one root for {name}, got {len(roots)}")
        root = next(iter(roots))
        meshes = [
            obj for obj in [root, *descendants(root)] if obj.type == "MESH"
        ]
        if not meshes:
            raise RuntimeError(f"no mesh under dynamic book root {name}")
        dynamic_books.append((name, root, root.matrix_world.copy(), meshes))

    robot_objects = []
    for row in visual_rows:
        obj = import_stl(Path(row["mesh_path"]))
        obj.name = "G1_" + row["geom_name"]
        robot_objects.append(obj)

    frame_indices = list(range(0, len(trajectory["times"]), args.frame_stride))
    if frame_indices[-1] != len(trajectory["times"]) - 1:
        frame_indices.append(len(trajectory["times"]) - 1)
    contacts = []
    for source_frame in frame_indices:
        dynamic_bvhs = []
        for book_index, (name, root, initial_world, meshes) in enumerate(dynamic_books):
            root.matrix_world = delta_matrix(
                trajectory["book_positions"][0, book_index],
                trajectory["book_positions"][source_frame, book_index],
                trajectory["book_matrices"][source_frame, book_index],
            ) @ initial_world
            for mesh in meshes:
                dynamic_bvhs.append((name, mesh, world_bvh(mesh)))
        for visual_index in robot_indices:
            row = visual_rows[visual_index]
            obj = robot_objects[visual_index]
            set_transform(
                obj,
                trajectory["positions"][source_frame, visual_index],
                trajectory["matrices"][source_frame, visual_index],
                row["mujoco_mesh_pos"],
                row["mujoco_mesh_quat_wxyz"],
            )
            robot_bvh = world_bvh(obj)
            for static_obj, static_bvh in static_bvhs:
                overlap = robot_bvh.overlap(static_bvh)
                if overlap:
                    contacts.append(
                        {
                            "source_frame": source_frame,
                            "time_s": float(trajectory["times"][source_frame]),
                            "robot_visual_index": visual_index,
                            "robot_geom": row["geom_name"],
                            "robot_mesh": row["mesh_name"],
                            "scene_object": semantic_id(static_obj),
                            "overlapping_triangle_pairs": len(overlap),
                        }
                    )
            for book_name, _, book_bvh in dynamic_bvhs:
                overlap = robot_bvh.overlap(book_bvh)
                if overlap:
                    contacts.append(
                        {
                            "source_frame": source_frame,
                            "time_s": float(trajectory["times"][source_frame]),
                            "robot_visual_index": visual_index,
                            "robot_geom": row["geom_name"],
                            "robot_mesh": row["mesh_name"],
                            "scene_object": book_name,
                            "overlapping_triangle_pairs": len(overlap),
                        }
                    )

    intentional_contacts = [
        row
        for row in contacts
        if row["scene_object"].startswith("upright_book_")
        and row["robot_mesh"]
        in {"right_hand_index_0_link", "right_hand_index_1_link"}
        and 0.80 <= row["time_s"] <= 2.35
    ]
    intentional_ids = {id(row) for row in intentional_contacts}
    forbidden_contacts = [row for row in contacts if id(row) not in intentional_ids]
    report = {
        "schema": "bedroom_g1_book_push_current_scene_mesh_collision_audit_v1",
        "scene": str(args.scene),
        "trajectory": str(args.trajectory),
        "source_frames_checked": frame_indices,
        "static_scene_objects": list(STATIC_IDS),
        "dynamic_scene_objects": book_names,
        "static_scene_bounds": {
            semantic_id(obj): world_bounds(obj) for obj in static_objects
        },
        "robot_visual_indices": list(robot_indices),
        "intentional_contact_policy": {
            "robot_meshes": [
                "right_hand_index_0_link",
                "right_hand_index_1_link",
            ],
            "scene_object_prefix": "upright_book_",
            "time_window_s": [0.80, 2.35],
        },
        "intentional_contact_rows": intentional_contacts,
        "collision_rows": forbidden_contacts,
        "passed": not forbidden_contacts,
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    pairs = sorted(
        {
            (row["robot_mesh"], row["scene_object"])
            for row in forbidden_contacts
        }
    )
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "frames_checked": len(frame_indices),
                "intentional_contact_rows": len(intentional_contacts),
                "collision_rows": len(forbidden_contacts),
                "collision_pairs": pairs,
                "report": str(args.output),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
