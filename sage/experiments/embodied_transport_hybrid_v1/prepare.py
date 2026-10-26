"""New controller contract, independently qualified before full transport."""

import argparse
from pathlib import Path
import time
import xml.etree.ElementTree as ET
import numpy as np
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


def save(path, value):
    value.pop("content_sha256_excluding_this_field", None)
    value["content_sha256_excluding_this_field"] = canonical_sha256(value)
    write_json_atomic(path, value)


def prepare(root, parent, mode):
    import mujoco

    model_dir = root / "model"
    model_dir.mkdir(parents=True, exist_ok=False)
    scene = read_bound_json(parent / "model/SCENE.json")
    tree = ET.parse(scene["model"]["path"])
    xml = tree.getroot()
    for node in xml.findall("asset/*"):
        if node.get("file"):
            node.set(
                "file", str(Path(scene["model"]["path"]).parent / node.get("file"))
            )
    target = [1.60 if mode == "standing_pick_place" else 1.85, 2.45, 0.86]
    xml.find(".//body[@name='task_target']").set("pos", f"{target[0]} {target[1]} 0")
    path = model_dir / "model.xml"
    path.write_text(ET.tostring(xml, encoding="unicode"))
    m = mujoco.MjModel.from_xml_path(str(path))
    if (m.nq, m.nv, m.nu, m.neq, m.nmocap) != (57, 55, 43, 0, 0):
        raise ValueError("unexpected plant")
    scene.update(
        model=_file_binding(path),
        implementation=_file_binding(Path(__file__)),
        parent_scene=_file_binding(parent / "model/SCENE.json"),
    )
    scene["task_fixtures"]["target"]["center_m"] = target
    save(model_dir / "SCENE.json", scene)
    case = read_bound_json(parent / "CASE.json")
    start = [1.31, 2.77] if mode == "standing_pick_place" else [0.85, 2.8]
    case.update(
        task_mode=mode,
        protocol_root=str(root),
        start_xy_m=start,
        source_root_goal_xy_m=start if mode == "standing_pick_place" else [1.25, 2.8],
        target_root_goal_xy_m=start if mode == "standing_pick_place" else [1.65, 2.72],
        goal_xy_m=start if mode == "standing_pick_place" else [1.65, 2.72],
        target_object_xyz_m=target,
        model_path=str(path),
        scene_manifest_path=str(model_dir / "SCENE.json"),
        scene_manifest=_file_binding(model_dir / "SCENE.json"),
    )
    save(root / "CASE.json", case)
    print({"prepared": mode, "dimensions": [m.nq, m.nv, m.nu]})


def preflight(root):
    import mujoco
    from scipy.spatial.transform import Rotation
    from sage.experiments.embodied_transport_v1.kinematics import solve, ARM_NAMES
    from sage.experiments.embodied_transport_v1.metrics_r5 import observe
    from sage.experiments.embodied_carry_v1.grasp import RIGHT_CLOSED

    case = read_bound_json(root / "CASE.json")
    parent = (
        root.parent
        / "embodied_transport_20261020_v6/attempt_01/active_1000/REPORT.json"
    )
    report = read_bound_json(parent)
    trace = read_bound_json(Path(report["trace"]["path"]))
    rows = [r for r in trace["records"] if r["sonic_candidate_consumed_by_physics"]]
    m = mujoco.MjModel.from_xml_path(case["model_path"])
    d = mujoco.MjData(m)
    d.qpos[:] = rows[179]["substeps"][-1]["full_qpos_after"]
    adr = int(m.joint("payload_free").qposadr[0])
    d.qpos[adr : adr + 7] = [*case["source_object_xyz_m"], 1, 0, 0, 0]
    for name, value in RIGHT_CLOSED.items():
        d.qpos[int(m.joint(name).qposadr[0])] = value * case["ready_fraction"]
    mujoco.mj_forward(m, d)
    w = m.body("right_wrist_yaw_link").id
    origin = d.xpos[w].copy()
    R = d.xmat[w].reshape(3, 3).copy()
    grasp = np.array(case["source_object_xyz_m"]) - np.array(case["grasp_local_xyz_m"])
    place = np.array(case["target_object_xyz_m"]) - np.array(case["grasp_local_xyz_m"])
    segments = [
        ("withdraw", origin + [-0.16, 0.06, 0.15], R),
        ("orient", origin + [-0.16, 0.06, 0.15], np.eye(3)),
        ("preinsert", grasp + [-0.1, 0, 0.01], np.eye(3)),
        ("insert", grasp, np.eye(3)),
        ("lift", grasp + [0, 0, 0.08], np.eye(3)),
        ("place", place, np.eye(3)),
    ]
    checks = []
    for phase, goal, target_R in segments:
        start = d.xpos[w].copy()
        start_R = d.xmat[w].reshape(3, 3).copy()
        delta = Rotation.from_matrix(start_R.T @ target_R).as_rotvec()
        for i in range(1, 21):
            f = i / 20
            s = solve(
                mujoco,
                m,
                d.qpos,
                start * (1 - f) + goal * f,
                start_R @ Rotation.from_rotvec(delta * f).as_matrix(),
            )
            for name, value in zip(ARM_NAMES, s["angles_rad"]):
                d.qpos[int(m.joint(name).qposadr[0])] = value
            mujoco.mj_forward(m, d)
            p = observe(mujoco, m, d)
            checks.append(
                {
                    "phase": phase,
                    "sample": i,
                    "position_error_m": s["position_error_m"],
                    "orientation_error_rad": s["orientation_error_rad"],
                    "fixture": p["body_fixture_violation"],
                    "scene": p["scene_violation"],
                }
            )
    passed = all(
        c["position_error_m"] < 0.005
        and c["orientation_error_rad"] < 0.05
        and not c["fixture"]
        and not c["scene"]
        for c in checks
    )
    save(
        root / "PREFLIGHT.json",
        {
            "passed": passed,
            "samples": checks,
            "physics_steps": 0,
            "case": _file_binding(root / "CASE.json"),
            "implementation": _file_binding(Path(__file__)),
            "scope": "reference feasibility; payload kept at source in FK sandbox, not physical pickup",
        },
    )
    print(
        {
            "preflight_passed": passed,
            "rejected": [
                c
                for c in checks
                if c["position_error_m"] >= 0.005
                or c["orientation_error_rad"] >= 0.05
                or c["fixture"]
                or c["scene"]
            ],
        }
    )


def freeze(root):
    path = root / "PROTOCOL.json"
    if path.exists():
        raise FileExistsError(path)
    if not read_bound_json(root / "PREFLIGHT.json")["passed"]:
        raise ValueError("preflight rejected")
    p = {
        "schema": "authorized-hybrid-transport/v1",
        "created_utc_timestamp": time.time(),
        "user_authorization": "2026-10-20 user: 可以，先按照这个想法去调整; permit independent upper-limb precise control while retaining SONIC locomotion",
        "case": _file_binding(root / "CASE.json"),
        "preflight": _file_binding(root / "PREFLIGHT.json"),
        "active_budgets_ticks": [100, 300, 500, 1000, 1500, 2000],
        "per_process_wall_s": 180,
        "max_causal_versions": 3,
        "repeat_rejected_identical_case": False,
        "controller": "unchanged raw SONIC targets for22 joints; seven right-arm Cartesian reference IK targets using unchanged official kp/kd/effort plus explicitly declared right-arm qfrc_bias gravity compensation; finger PD unchanged",
        "applied_action_history": "all29 actually applied mixed targets mapped back to raw action space, not unused SONIC arm outputs",
        "physical_thresholds": "unchanged .65m pelvis/.5up/.01m penetration/600N/.5433987842330933 slew; no active support or applied force; gravity compensation only as declared arm motor torque",
        "source_guard": "before stable acquisition, >20mm displacement during reach or >4 physical substeps unsupported/nonopposing rejects",
        "scope": "standing pickup/place is only a new-controller qualification, not full autonomous transport; generated room retained, privileged simulator state feedback",
        "task_contract": "genuine free-body pickup with opposing contact and whole object bottom>=20mm above source for100substeps; target support before release; retract and stable hand-free placement100substeps; full mode additionally real approach/carry walking/stop",
        "dependencies": {
            p.name: _file_binding(p)
            for p in sorted(Path(__file__).parent.glob("*.py"))
            if not p.name.startswith("test")
        },
        "parent_dependencies": {
            p.name: _file_binding(p)
            for p in sorted(
                (Path(__file__).parent.parent / "embodied_transport_v1").glob("*.py")
            )
            if not p.name.startswith("test")
        },
    }
    save(path, p)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--parent", type=Path)
    p.add_argument(
        "--mode",
        choices=["standing_pick_place", "full_transport"],
        default="standing_pick_place",
    )
    p.add_argument("--stage", choices=["prepare", "preflight", "freeze"], required=True)
    a = p.parse_args()
    if a.stage == "prepare":
        prepare(a.root, a.parent, a.mode)
    elif a.stage == "preflight":
        preflight(a.root)
    else:
        freeze(a.root)
