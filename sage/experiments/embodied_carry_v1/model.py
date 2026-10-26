"""Restore exact official hand meshes/joints into a NEW locomotion plant.

Execution is gated on complete main-goal delivery inside the user's 2h window.
No welds, mocap objects, altered old assets, or invented hand proxy geometry.
"""

import argparse
from copy import deepcopy
from datetime import datetime
import hashlib
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.audit_candidates import (
    canonical_sha256,
    write_json_atomic,
    sha256_file,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)
from sage.experiments.embodied_data_stability_v1.sonic_walk_official_model import (
    OFFICIAL_MODEL,
)
from sage.experiments.embodied_generated_scene_smoke_v1.common import SOURCE


def authorize(main_root):
    import json

    result = read_bound_json(main_root / "delivery/DELIVERY.json")
    clocks = json.loads((main_root / "CLOCK_ORIGIN.json").read_text())
    deadline = datetime.fromisoformat(
        clocks["two_hour_deadline_utc"].replace("Z", "+00:00")
    ).timestamp()
    if result["classification"] != "accepted_development_pipeline" or not all(
        result["gates"].values()
    ):
        raise RuntimeError("main goal not fully accepted")
    if result["accepted_utc_timestamp"] > deadline:
        raise RuntimeError("main goal exceeded conditional 2-hour window")
    return _file_binding(main_root / "delivery/DELIVERY.json")


def build(main_root, output):
    admitted = authorize(main_root)
    output.mkdir(parents=True, exist_ok=False)
    assets = output / "assets"
    assets.mkdir()
    scene = read_bound_json(main_root / "scenes/S01r2/physics_v2/SCENE.json")
    root = ET.parse(scene["model"]["path"]).getroot()
    original = ET.parse(OFFICIAL_MODEL).getroot()
    for asset in root.findall("asset/*"):
        if asset.get("file"):
            source = Path(scene["model"]["path"]).parent / asset.get("file")
            target = assets / source.name
            shutil.copyfile(source, target)
            asset.set("file", "assets/" + target.name)
    restored = []
    compiler_meshdir = original.find("compiler").get("meshdir", "")
    for mesh in original.findall("asset/mesh"):
        if "_hand_" not in mesh.get("name", ""):
            continue
        pointer = OFFICIAL_MODEL.parent / compiler_meshdir / mesh.get("file")
        text = pointer.read_text()
        expected = next(
            line.split(":", 1)[1]
            for line in text.splitlines()
            if line.startswith("oid sha256:")
        )
        source = SOURCE / "assets" / Path(mesh.get("file")).name
        if sha256_file(source) != expected:
            raise ValueError("local hand bytes do not match official LFS object")
        target = assets / source.name
        shutil.copyfile(source, target)
        node = deepcopy(mesh)
        node.set("file", "assets/" + target.name)
        root.find("asset").append(node)
        restored.append(
            {
                "name": mesh.get("name"),
                "official_pointer": _file_binding(pointer),
                "source": _file_binding(source),
                "local": _file_binding(target),
                "official_lfs_oid": expected,
            }
        )
    hand_joint_names = []
    for source_body in original.findall(".//body"):
        name = source_body.get("name", "")
        if "_hand_" not in name and not name.endswith("_wrist_yaw_link"):
            continue
        body = root.find(f".//body[@name='{name}']")
        if body is None:
            raise ValueError("missing preserved hand body " + name)
        if "_hand_" in name:
            for geom in list(body.findall("geom")):
                body.remove(geom)
            joint = source_body.find("joint")
            if joint is not None:
                body.append(deepcopy(joint))
                hand_joint_names.append(joint.get("name"))
        for geom in source_body.findall("geom"):
            if "_hand_" in name or "_hand_" in geom.get("mesh", ""):
                body.append(deepcopy(geom))
    for motor in original.findall("actuator/*"):
        if motor.get("joint") in hand_joint_names:
            node = deepcopy(motor)
            node.set("name", node.get("joint"))
            root.find("actuator").append(node)
    body = ET.SubElement(
        root.find("worldbody"), "body", name="payload", pos="-10 -10 1"
    )
    ET.SubElement(body, "freejoint", name="payload_free")
    ET.SubElement(
        body,
        "geom",
        name="payload_geom",
        type="cylinder",
        size=".02 .04",
        mass=".05",
        friction=".8 .005 .0001",
        rgba=".9 .12 .08 1",
    )
    # Object is a world child with an unconstrained free joint, never attached.
    model_path = output / "model.xml"
    model_path.write_text(ET.tostring(root, encoding="unicode"))
    import mujoco

    model = mujoco.MjModel.from_xml_path(str(model_path))
    if (model.nq, model.nv, model.nu) != (57, 55, 43):
        raise ValueError("unexpected hand/free-object plant")
    if model.neq or model.nmocap:
        raise ValueError("weld/mocap disallowed")
    result = {
        **scene,
        "schema": "conditional-contact-carry-model/v1",
        "main_goal_admission": admitted,
        "model": _file_binding(model_path),
        "assets": [_file_binding(p) for p in sorted(assets.iterdir())],
        "official_hand_meshes": restored,
        "restored_hand_joint_names": hand_joint_names,
        "payload": {
            "shape": "cylinder",
            "radius_m": 0.02,
            "half_height_m": 0.04,
            "mass_kg": 0.05,
            "free_joint": "payload_free",
            "parent": "world",
            "preloaded_initial_grasp_not_pickup": True,
        },
        "finger_control_source": {
            "model": _file_binding(SOURCE / "g1.xml"),
            "targets": _file_binding(SOURCE / "run.py"),
            "kp_thumb0": 2.0,
            "kp_other": 1.5,
            "kd": 0.1,
            "effort_limits": "unchanged official motors",
        },
        "implementation": _file_binding(Path(__file__)),
        "nq": model.nq,
        "nv": model.nv,
        "nu": model.nu,
        "physics_steps": 0,
        "collision_fidelity": "exact official hand mesh bytes with native MuJoCo convex collision; remaining robot collision-lite; conservative environment OBBs",
    }
    result.pop("content_sha256_excluding_this_field", None)
    result["content_sha256_excluding_this_field"] = canonical_sha256(result)
    write_json_atomic(output / "SCENE.json", result)
    print("conditional carry model compiled", model.nq, model.nv, model.nu)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--main-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    build(a.main_root, a.output)
