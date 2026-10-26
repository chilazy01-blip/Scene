"""Bind a SAGE layout to a clean analytic task model while keeping G1 unchanged."""

from __future__ import annotations

import argparse
import math
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from sage.experiments.codex_trellis_scene_v2.p021_physics import _geometry, _read_glb
from sage.experiments.embodied_scene_bridge.adapter import export_visuals, pose

from .common import RUN_ROOT, SOURCE, read_json, sha256, write_json


TABLE_BINDINGS = {
    "desk": {"body": "table", "top": "table_top", "rgba": "0.48 0.27 0.10 0"},
    "side_table": {
        "body": "table_white",
        "top": "table_white_top",
        "rgba": "0.08 0.10 0.28 0",
    },
}
TABLETOP_HALF_HEIGHT_M = 0.02
LEG_RADIUS_M = 0.025
LEG_EDGE_INSET_M = 0.05
PICK_TABLE_SIM_XY = np.array([0.351, 0.0])


def _vector(values: Any) -> str:
    return " ".join(f"{float(value):.9g}" for value in values)


def _angle_is_axis_aligned(yaw_deg: float) -> bool:
    residual = ((float(yaw_deg) + 90.0) % 180.0) - 90.0
    return abs(residual) < 1e-6


def _replace_table_proxy(
    body: ET.Element,
    *,
    top_name: str,
    dimensions: np.ndarray,
    rgba: str,
) -> dict[str, Any]:
    for child in list(body):
        if child.tag == "geom":
            body.remove(child)
    width, length, height = map(float, dimensions)
    if min(width, length) <= 2 * (LEG_EDGE_INSET_M + LEG_RADIUS_M):
        raise ValueError("generated table is too narrow for the analytic leg proxy")
    if height <= 2 * TABLETOP_HALF_HEIGHT_M:
        raise ValueError("generated table is shorter than its tabletop proxy")
    ET.SubElement(
        body,
        "geom",
        name=top_name,
        type="box",
        size=_vector([width / 2, length / 2, TABLETOP_HALF_HEIGHT_M]),
        rgba=rgba,
        contype="1",
        conaffinity="1",
        friction="1 0.1 0.01",
    )
    leg_half_height = (height - 2 * TABLETOP_HALF_HEIGHT_M) / 2
    leg_z = -height / 2
    leg_x = width / 2 - LEG_EDGE_INSET_M
    leg_y = length / 2 - LEG_EDGE_INSET_M
    stem = top_name.removesuffix("_top")
    for index, (x, y) in enumerate(
        ((leg_x, leg_y), (-leg_x, leg_y), (leg_x, -leg_y), (-leg_x, -leg_y)),
        start=1,
    ):
        ET.SubElement(
            body,
            "geom",
            name=f"{stem}_leg_{index}",
            type="cylinder",
            size=_vector([LEG_RADIUS_M, leg_half_height]),
            pos=_vector([x, y, leg_z]),
            rgba=rgba,
            contype="1",
            conaffinity="1",
            friction="1 0.1 0.01",
        )
    return {
        "top_half_extents_m": [width / 2, length / 2, TABLETOP_HALF_HEIGHT_M],
        "leg_radius_m": LEG_RADIUS_M,
        "leg_half_height_m": leg_half_height,
        "method": "fresh analytic box tabletop plus four cylinder legs",
    }


def build_model(run_root: Path) -> dict[str, Any]:
    generator = run_root / "generator"
    validation = read_json(generator / "validation_final.json")
    if validation.get("ok") is not True:
        raise RuntimeError("SAGE layout did not pass its final validation")
    plan = read_json(generator / "layout_plan_final.json")
    objects_by_category = {row["category"]: row for row in plan["objects"]}
    if not set(TABLE_BINDINGS) <= set(objects_by_category):
        raise RuntimeError(
            f"missing task tables from generated categories: {sorted(objects_by_category)}"
        )
    if not all(
        _angle_is_axis_aligned(objects_by_category[category]["yaw"])
        for category in TABLE_BINDINGS
    ):
        raise RuntimeError("controller-isolation tables must remain axis aligned")

    output = run_root / "model"
    output.mkdir(exist_ok=False)
    assets = output / "assets"
    shutil.copytree(SOURCE / "assets", assets)
    shutil.copy2(SOURCE / "g1.xml", output / "g1.xml")

    scene_glb = generator / "scene_codex_trellis_v2.glb"
    document, _ = _read_glb(scene_glb)
    scene_ids = {
        node.get("extras", {}).get("scene_object_id") for node in document["nodes"]
    } - {None}
    declared = {row["id"] for row in plan["objects"]}
    openings = {
        row["id"]
        for key in ("doors", "windows")
        for row in plan.get("architecture", {}).get(key, [])
    }
    if not declared <= scene_ids or not scene_ids - declared <= openings:
        raise RuntimeError("assembled GLB object IDs do not match the final layout")
    groups, _floor = _geometry(
        scene_glb,
        {"room": plan["room"], "objects": [{"id": name} for name in sorted(scene_ids)]},
    )

    root = ET.parse(SOURCE / "scene.xml").getroot()
    world = root.find("worldbody")
    asset = root.find("asset")
    if world is None or asset is None:
        raise RuntimeError("source scene has no asset/worldbody section")

    pick = objects_by_category["desk"]
    offset_xy = np.array([float(pick["x"]), float(pick["y"])]) - PICK_TABLE_SIM_XY
    visual_poses: dict[str, np.ndarray] = {}
    visual_bodies: dict[str, ET.Element] = {}
    table_reports = []
    for category, binding in TABLE_BINDINGS.items():
        obj = objects_by_category[category]
        dimensions = np.array(
            [obj["dimensions"][key] for key in ("width", "length", "height")],
            dtype=float,
        )
        matrix = pose(obj)
        vertices = np.concatenate([part["vertices"] for part in groups[obj["id"]]])
        local = (vertices - matrix[:3, 3]) @ matrix[:3, :3]
        actual_dimensions = np.ptp(local, axis=0)
        dimension_error = float(np.max(np.abs(actual_dimensions - dimensions)))
        if dimension_error > 1e-4:
            raise RuntimeError(f"assembled dimension mismatch for {obj['id']}: {dimension_error}")

        body = world.find(f"body[@name='{binding['body']}']")
        if body is None:
            raise RuntimeError(f"missing controller-facing body {binding['body']}")
        yaw = math.radians(float(obj["yaw"]))
        top_center_z = float(obj.get("z", 0.0)) + dimensions[2] - TABLETOP_HALF_HEIGHT_M
        body.set(
            "pos",
            _vector(
                [
                    float(obj["x"]) - offset_xy[0],
                    float(obj["y"]) - offset_xy[1],
                    top_center_z,
                ]
            ),
        )
        body.set("quat", _vector([math.cos(yaw / 2), 0, 0, math.sin(yaw / 2)]))
        proxy = _replace_table_proxy(
            body,
            top_name=binding["top"],
            dimensions=dimensions,
            rgba=binding["rgba"],
        )
        visual_body = ET.SubElement(
            body,
            "body",
            name=f"generated_visual_{category}",
            pos=_vector([0, 0, -dimensions[2] / 2 + TABLETOP_HALF_HEIGHT_M]),
        )
        visual_poses[obj["id"]] = matrix
        visual_bodies[obj["id"]] = visual_body
        table_reports.append(
            {
                "category": category,
                "scene_object_id": obj["id"],
                "asset_id": obj["asset_id"],
                "generated_pose": {
                    key: obj[key] for key in ("x", "y", "z", "yaw") if key in obj
                },
                "simulation_xy_m": [
                    float(obj["x"]) - offset_xy[0],
                    float(obj["y"]) - offset_xy[1],
                ],
                "dimensions_m": dimensions.tolist(),
                "assembled_dimension_error_m": dimension_error,
                "proxy": proxy,
            }
        )

    background_reports = []
    for obj in plan["objects"]:
        if obj["category"] in TABLE_BINDINGS:
            continue
        dimensions = np.array(
            [obj["dimensions"][key] for key in ("width", "length", "height")],
            dtype=float,
        )
        matrix = pose(obj)
        vertices = np.concatenate([part["vertices"] for part in groups[obj["id"]]])
        local = (vertices - matrix[:3, 3]) @ matrix[:3, :3]
        dimension_error = float(np.max(np.abs(np.ptp(local, axis=0) - dimensions)))
        if dimension_error > 1e-4:
            raise RuntimeError(f"assembled dimension mismatch for {obj['id']}: {dimension_error}")
        yaw = math.radians(float(obj["yaw"]))
        body = ET.SubElement(
            world,
            "body",
            name=f"generated_background_{obj['id']}",
            pos=_vector(
                [
                    float(obj["x"]) - offset_xy[0],
                    float(obj["y"]) - offset_xy[1],
                    float(obj.get("z", 0.0)) + dimensions[2] / 2,
                ]
            ),
            quat=_vector([math.cos(yaw / 2), 0, 0, math.sin(yaw / 2)]),
        )
        ET.SubElement(
            body,
            "geom",
            name=f"generated_background_proxy_{obj['id']}",
            type="box",
            size=_vector(dimensions / 2),
            rgba="0 0 0 0",
            contype="1",
            conaffinity="1",
            friction="0.8 0.05 0.005",
        )
        visual_poses[obj["id"]] = matrix
        visual_bodies[obj["id"]] = body
        background_reports.append(
            {
                "scene_object_id": obj["id"],
                "category": obj["category"],
                "asset_id": obj["asset_id"],
                "dimensions_m": dimensions.tolist(),
                "assembled_dimension_error_m": dimension_error,
                "proxy": "conservative oriented bounding box; placed outside task corridor",
            }
        )

    architecture = ET.SubElement(
        world,
        "body",
        name="generated_architecture_visual",
        pos=_vector([-offset_xy[0], -offset_xy[1], 0]),
    )
    direct_children_before = {id(child) for child in list(world)}
    visuals = export_visuals(scene_glb, root, visual_poses, visual_bodies, output)
    for child in list(world):
        if id(child) not in direct_children_before and child.tag == "geom":
            world.remove(child)
            architecture.append(child)
    # g1.xml establishes meshdir="assets" globally. export_visuals emits
    # assets/foo.obj, so normalize only the freshly exported meshes to foo.obj.
    for mesh in asset.findall("mesh"):
        filename = mesh.get("file", "")
        if mesh.get("name", "").startswith("scene_visual_") and filename.startswith("assets/"):
            mesh.set("file", filename.removeprefix("assets/"))

    ET.indent(root)
    model_path = output / "MODEL.xml"
    ET.ElementTree(root).write(model_path, encoding="unicode")
    manifest = read_json(run_root / "generator_request/asset_manifest.json")
    report = {
        "schema": "embodied-generated-scene-model-binding/v1",
        "model_path": str(model_path),
        "model_sha256": sha256(model_path),
        "source_scene_sha256": sha256(SOURCE / "scene.xml"),
        "source_robot_sha256": sha256(SOURCE / "g1.xml"),
        "generated_scene_glb_sha256": sha256(scene_glb),
        "layout_plan_sha256": sha256(generator / "layout_plan_final.json"),
        "generator_to_sim_xy_offset_m": offset_xy.tolist(),
        "tables": table_reports,
        "background_objects": background_reports,
        "visual_primitives": len(visuals),
        "visual_asset_sources": [
            {
                "asset_id": row["asset_id"],
                "path": row["glb_path"],
                "sha256": row["experiment_source_sha256"],
                "source_pipeline": row.get("source", {}).get("pipeline"),
            }
            for row in manifest["assets"]
        ],
        "physics_scope": (
            "generated tables use new semantic analytic proxies; G1 hand collision meshes "
            "and the analytic task cylinder remain unchanged for controlled comparison"
        ),
        "physics_steps": 0,
        "production_accepted": False,
    }
    write_json(output / "BINDING.json", report)
    return report


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, default=RUN_ROOT)
    args = parser.parse_args(argv)
    print(build_model(args.run_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

