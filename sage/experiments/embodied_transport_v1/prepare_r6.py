"""Freeze a finite single-scene source-support to target-support task."""

import argparse
from pathlib import Path
import shutil
import time
import xml.etree.ElementTree as ET
from sage.experiments.embodied_data_stability_v1.audit_candidates import (
    canonical_sha256,
    write_json_atomic,
)
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def prepare(root, prior):
    import mujoco

    output = root / "model"
    output.mkdir(parents=True, exist_ok=False)
    (output / "assets").mkdir()
    previous = read_bound_json(prior / "continuation_01/walking_full/REPORT.json")
    scene = read_bound_json(Path(previous["case_config"]["scene_manifest_path"]))
    tree = ET.parse(scene["model"]["path"])
    xml = tree.getroot()
    for node in xml.findall("asset/*"):
        if node.get("file"):
            source = Path(scene["model"]["path"]).parent / node.get("file")
            destination = output / "assets" / source.name
            shutil.copyfile(source, destination)
            node.set("file", "assets/" + source.name)
    source = [1.45, 2.45, 0.86]
    target = [1.85, 2.45, 0.86]
    for name, center, radius, color in (
        ("source", source, 0.015, ".25 .4 .7 1"),
        ("target", target, 0.05, ".15 .6 .35 1"),
    ):
        body = ET.SubElement(
            xml.find("worldbody"),
            "body",
            name="task_" + name,
            pos=f"{center[0]} {center[1]} 0",
        )
        ET.SubElement(
            body,
            "geom",
            name="task_" + name + "_support",
            type="cylinder",
            size=f"{radius} .005",
            pos="0 0 .795",
            rgba=color,
            friction=".8 .005 .0001",
        )
        ET.SubElement(
            body,
            "geom",
            name="task_" + name + "_shaft",
            type="cylinder",
            size=".015 .39",
            pos="0 0 .39",
            rgba=color,
        )
        ET.SubElement(
            body,
            "geom",
            name="task_" + name + "_base",
            type="box",
            size=".09 .07 .015",
            pos="0 0 .015",
            rgba=color,
        )
    payload = xml.find(".//body[@name='payload']")
    payload.set("pos", " ".join(map(str, source)))
    payload.set("quat", "1 0 0 0")
    payload.find("geom").set("size", ".02 .06")
    path = output / "model.xml"
    path.write_text(ET.tostring(xml, encoding="unicode"))
    model = mujoco.MjModel.from_xml_path(str(path))
    if (model.nq, model.nv, model.nu, model.neq, model.nmocap) != (57, 55, 43, 0, 0):
        raise ValueError("unexpected free-payload model")
    description = {
        **scene,
        "schema": "continuous-transport-task-model/v1",
        "model": _file_binding(path),
        "assets": [_file_binding(p) for p in sorted((output / "assets").iterdir())],
        "parent_scene": _file_binding(
            Path(previous["case_config"]["scene_manifest_path"])
        ),
        "implementation": _file_binding(Path(__file__)),
        "task_fixtures": {
            "source": {"center_m": source, "top_m": 0.80, "radius_m": 0.015},
            "target": {"center_m": target, "top_m": 0.80, "radius_m": 0.05},
            "provenance": "explicit procedural task fixtures added to prior actual SAGE generated layout; not generated furniture meshes",
        },
        "initial_object": "upright on source support, not in hand",
        "physics_steps": 0,
    }
    description.pop("content_sha256_excluding_this_field", None)
    description["content_sha256_excluding_this_field"] = canonical_sha256(description)
    write_json_atomic(output / "SCENE.json", description)
    print("task plant prepared", model.nq, model.nv, model.nu)


def freeze(root, prior):
    path = root / "PROTOCOL.json"
    if path.exists():
        raise FileExistsError(path)
    if not read_bound_json(root / "PATH_PREFLIGHT.json")["passed"]:
        raise ValueError("swept exact-model preflight rejected")
    description = read_bound_json(root / "model/SCENE.json")
    case = read_bound_json(prior / "continuation_01/walking_full/REPORT.json")[
        "case_config"
    ]
    geometric = read_bound_json(
        root.parent / "embodied_transport_20261020_v4/ERGONOMIC_PROBE.json"
    )
    selected = geometric["selected"]
    if not selected or not selected["eligible"]:
        raise ValueError("ergonomic geometry certificate required")
    case.update(
        schema="continuous-transport-case/v1",
        protocol_root=str(root),
        model_path=description["model"]["path"],
        scene_manifest_path=str(root / "model/SCENE.json"),
        scene_manifest=_file_binding(root / "model/SCENE.json"),
        carry_mode="transport",
        start_xy_m=[0.85, 2.8],
        joint_noise_std_rad=0.0,
        source_root_goal_xy_m=[1.25, 2.8],
        target_root_goal_xy_m=[1.65, 2.72],
        goal_xy_m=[1.65, 2.72],
        source_object_xyz_m=[1.45, 2.45, 0.86],
        target_object_xyz_m=[1.85, 2.45, 0.86],
        grasp_local_xyz_m=selected["grasp_local_xyz_m"],
        support_top_m=0.8,
        ready_fraction=selected["fraction"],
        grasp_local_rotation=[[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        desired_wrist_rotation=[[1, 0, 0], [0, 1, 0], [0, 0, 1]],
        initial_right_hand_targets={},
        preloaded_grasp_not_pickup=False,
    )
    case.pop("standing_report", None)
    case.pop("standing_audit", None)
    case.pop("content_sha256_excluding_this_field", None)
    case["content_sha256_excluding_this_field"] = canonical_sha256(case)
    write_json_atomic(root / "CASE.json", case)
    p = {
        "schema": "continuous-autonomous-transport-protocol/v1",
        "created_utc_timestamp": time.time(),
        "case": _file_binding(root / "CASE.json"),
        "prior_delivery": _file_binding(prior / "delivery/DELIVERY.json"),
        "geometric_preflight": _file_binding(
            root.parent / "embodied_transport_20261020_v4/ERGONOMIC_PROBE.json"
        ),
        "revision": {
            "parent_protocol": _file_binding(
                root.parent / "embodied_transport_20261020_v5/PROTOCOL.json"
            ),
            "evidence": _file_binding(
                root.parent
                / "embodied_transport_20261020_v5/attempt_01/active_0300/REPORT.json"
            ),
            "reason": "R5 actual wrist transient +8cm X while turning despite safe reference. Withdraw further and orient in safe corridor before moving Y; final second version of bounded batch",
        },
        "new_batch": {
            "max_versions": 2,
            "first_batch_versions": 4,
            "first_batch_physics_steps": 13545,
            "reason": "old reach path hit support or stalled; ergonomic side grasp with full pose feedback",
            "profile_changed": True,
            "object_height_m": 0.12,
            "support_top_m": 0.8,
        },
        "swept_preflight": _file_binding(root / "PATH_PREFLIGHT.json"),
        "additional_task_audit": "actual100substep lift clearance/opposing/no support; left/right complete carry foot swing then load; final100substep hand-free target support/object speed<.02m/s/body speed<.04m/s/pelvis>=.7/up>=.97",
        "scope": "single generated room and two explicit narrow support fixtures, 50g upright cylinder, privileged simulator state feedback; not vision or held-out",
        "active_budgets_ticks": [100, 300, 500, 1000, 1500, 2000],
        "budget_rule": "new independent admission then2s short; every extension requires accepted preceding exact prefix and all physical guards; total hard maximum40s active, no resetting across phases",
        "per_process_wall_s": 180,
        "stage_limits_ticks": {
            "approach": 300,
            "source_stop": 150,
            "reach": 600,
            "close": 150,
            "lift": 150,
            "carry": 300,
            "target_stop": 150,
            "place": 250,
            "release": 100,
            "retract": 150,
            "settle": 100,
        },
        "max_causal_revisions": 2,
        "repeat_rejected_identical_case": False,
        "control": "unchanged raw SONIC29 body, official PD/effort; upper-body task goals only through smooth reference IK, separate native finger PD; no body-command overrides or SourceA body controls",
        "physical_thresholds": "unchanged .65m pelvis/.5up/.01m penetration/600N/.5433987842330933rad slew; active external forces and bias prohibited",
        "task_contract": "empty hand at initial object-on-source; true opposing contact then >=20mm source clearance >=.5s; carry object >=.2m with no source/target support; controlled destination placement/contact; release, retract >=50mm, target object stable and hand-free >=.5s; no weld/state reset/pose assignment after initialization",
        "dependencies": {
            p.name: _file_binding(p)
            for p in sorted(Path(__file__).parent.glob("*.py"))
            if not p.name.startswith("test")
        },
    }
    p["content_sha256_excluding_this_field"] = canonical_sha256(p)
    write_json_atomic(path, p)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--prior", type=Path, required=True)
    p.add_argument("--freeze", action="store_true")
    a = p.parse_args()
    freeze(a.root, a.prior) if a.freeze else prepare(a.root, a.prior)
