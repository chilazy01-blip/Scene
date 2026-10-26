"""Bind real public-generator geometry to G1, preserving the official body.

Background colliders are conservative OBBs; room floor/walls derive from the
generator's metric plan. Meshes are visual-only. This is not full-mesh physics.
"""

import argparse
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

from sage.experiments.embodied_scene_bridge.adapter import export_visuals, pose
from sage.experiments.codex_trellis_scene_v2.p021_physics import _read_glb
from sage.experiments.embodied_data_stability_v1.sonic_walk_official_model import (
    official_body_model_xml,
)
from sage.experiments.embodied_data_stability_v1.audit_candidates import (
    canonical_sha256,
    write_json_atomic,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def vec(values):
    return " ".join(format(float(x), ".12g") for x in values)


def build(scene):
    generator = scene / "generator"
    output = scene / "physics_v2"
    output.mkdir(exist_ok=False)
    (output / "assets").mkdir()
    plan = json.loads((generator / "layout_plan_final.json").read_text())
    validation = json.loads((generator / "validation_final.json").read_text())
    if not validation["ok"] or plan["coordinate_contract"]["world_up"] != "+z":
        raise ValueError("generator rejected")
    payload, base = official_body_model_xml()
    root = ET.fromstring(payload)
    root.find("compiler").set("meshdir", ".")
    root.find("compiler").set("texturedir", ".")
    world = root.find("worldbody")
    world.remove(world.find("geom[@name='floor']"))
    w, l, h = [plan["room"][k] for k in ("width", "length", "height")]
    ET.SubElement(
        world,
        "geom",
        name="floor",
        type="box",
        pos=vec((w / 2, l / 2, -0.05)),
        size=vec((w / 2, l / 2, 0.05)),
        friction="1 .005 .0001",
        rgba=".58 .56 .51 1",
    )
    for name, position, size in [
        ("west", (0, l / 2, h / 2), (0.04, l / 2, h / 2)),
        ("east", (w, l / 2, h / 2), (0.04, l / 2, h / 2)),
        ("south", (w / 2, 0, h / 2), (w / 2, 0.04, h / 2)),
        ("north", (w / 2, l, h / 2), (w / 2, 0.04, h / 2)),
    ]:
        ET.SubElement(
            world,
            "geom",
            name="room_wall_" + name,
            type="box",
            pos=vec(position),
            size=vec(size),
            rgba="0 0 0 0",
        )
    poses = {}
    bodies = {}
    obstacles = []
    for obj in plan["objects"]:
        name = obj["id"]
        matrix = pose(obj)
        dimensions = [obj["dimensions"][k] for k in ("width", "length", "height")]
        yaw = math.radians(obj["yaw"])
        body = ET.SubElement(
            world,
            "body",
            name="generated_" + name,
            pos=vec(matrix[:3, 3]),
            quat=vec((math.cos(yaw / 2), 0, 0, math.sin(yaw / 2))),
        )
        ET.SubElement(
            body,
            "geom",
            name="scene_proxy_" + name,
            type="box",
            size=vec(np.asarray(dimensions) / 2),
            rgba="0 0 0 0",
            friction=".8 .005 .0001",
        )
        poses[name] = matrix
        bodies[name] = body
        obstacles.append(
            {
                "id": name,
                "center": matrix[:3, 3].tolist(),
                "yaw_rad": yaw,
                "dimensions": dimensions,
            }
        )
    glb = generator / "scene_codex_trellis_v2.glb"
    document, _ = _read_glb(glb)
    extras = (
        {node.get("extras", {}).get("scene_object_id") for node in document["nodes"]}
        - {None}
        - set(bodies)
    )
    for name in sorted(extras):
        poses[name] = np.eye(4)
        bodies[name] = ET.SubElement(world, "body", name="opening_visual_" + name)
    visuals = export_visuals(glb, root, poses, bodies, output)
    xml = ET.tostring(root, encoding="unicode")
    (output / "model.xml").write_text(xml)
    import mujoco

    model = mujoco.MjModel.from_xml_path(str(output / "model.xml"))
    if (model.nq, model.nv, model.nu) != (36, 35, 29):
        raise ValueError("body contract changed")
    metadata = {
        "schema": "generated-g1-locomotion-scene/v1",
        "scene_id": scene.name,
        "base_model": base,
        "room": plan["room"],
        "obstacles": obstacles,
        "visual_parts": len(visuals),
        "collision_fidelity": "official collision-lite robot; conservative scene OBBs and analytic room",
        "sources": {
            p.name: _file_binding(p)
            for p in (
                generator / "layout_plan_final.json",
                generator / "validation_final.json",
                glb,
                scene / "GENERATION.json",
            )
        },
        "model": _file_binding(output / "model.xml"),
        "assets": [_file_binding(p) for p in sorted((output / "assets").iterdir())],
        "implementation": _file_binding(Path(__file__)),
        "physics_steps": 0,
        "nq": model.nq,
        "nv": model.nv,
        "nu": model.nu,
    }
    metadata["content_sha256_excluding_this_field"] = canonical_sha256(metadata)
    write_json_atomic(output / "SCENE.json", metadata)
    print(scene.name, model.ngeom, "geoms", len(visuals), "visual parts")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", type=Path, required=True)
    build(parser.parse_args().scene)
