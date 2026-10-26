"""Preserve native admission solver failure; collision detection only, no stepping."""

import argparse
from pathlib import Path
import time
import numpy as np
from .engine import authorize
from .model import load_model
from .contacts import contact_pair
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)
from sage.experiments.embodied_data_stability_v1.sonic_semantic_shadow import (
    DEFAULT_ANGLES,
)
from sage.experiments.embodied_data_stability_v1 import (
    sonic_native_dynamic_shadow as native,
)
from sage.experiments.embodied_carry_v1.grasp import RIGHT_CLOSED


def run(root, failed_build):
    import mujoco
    import cv2

    started = time.monotonic()
    authorize(root)
    directory = root / "static_diagnostic"
    directory.mkdir(exist_ok=False)
    case = read_bound_json(root / "CASE.json")
    scene = read_bound_json(root / "model/SCENE.json")
    model = load_model(case["model_path"])
    data = mujoco.MjData(model)
    ids = native._model_ids(mujoco, model)
    data.qpos[ids["qpos_ids"]] = DEFAULT_ANGLES
    data.qpos[:2] = case["start_xy_m"]
    for i in range(model.njnt):
        name = model.joint(i).name
        if "_hand_" in name:
            data.qpos[model.jnt_qposadr[i]] = (
                RIGHT_CLOSED.get(name, 0) * case["ready_fraction"]
            )
    adr = int(model.joint("payload_free").qposadr[0])
    data.qpos[adr : adr + 7] = [*case["source_object_xyz_m"], 1, 0, 0, 0]
    mujoco.mj_kinematics(model, data)
    mujoco.mj_comPos(model, data)
    mujoco.mj_flex(model, data)
    mujoco.mj_collision(model, data)
    contacts = []
    for c in data.contact:
        pair = contact_pair(model, c)
        fixed = [int(model.body_weldid[model.body(p["body"]).id]) == 0 for p in pair]
        contacts.append(
            {
                "pair": pair,
                "distance_m": float(c.dist),
                "both_participants_fixed": all(fixed),
            }
        )
    contacts.sort(key=lambda c: c["distance_m"])
    invalid = [c for c in contacts if c["both_participants_fixed"]]
    result = {
        "schema": "native-static-solver-failure-diagnostic/v1",
        "static_admission_passed": False,
        "task_passed": False,
        "physics_steps": 0,
        "contacts": contacts,
        "fixed_fixed_contact_count": len(invalid),
        "fixed_fixed_contacts": invalid,
        "observed_error": "mujoco.FatalError: findEdges: no tree found for constraint 43 in initial setup_hand -> mj_forward (no mj_step called)",
        "cause_scope": (
            "fixed rigid-flex / fixed fixture contact constraints have no dynamic kinematic tree"
            if invalid
            else "unresolved; inspect contact constraints"
        ),
        "no_collision_masks_or_solver_flags_modified": True,
        "no_task_attempt_started": True,
        "initial_qpos": data.qpos.tolist(),
        "model": _file_binding(Path(case["model_path"])),
        "scene": _file_binding(root / "model/SCENE.json"),
        "protocol": _file_binding(root / "PROTOCOL.json"),
        "implementation": _file_binding(Path(__file__)),
        "failed_build": {
            "root": str(failed_build),
            "model": _file_binding(failed_build / "model/model.xml"),
            "source": _file_binding(failed_build / "BUILD_FAILED_SOURCE.py"),
            "physics_steps": 0,
            "error": "over-strict all-body inertia comparison rejected inferred inertia changes on five fixed furniture bodies; robot and payload invariance later independently passed",
        },
        "full_official_robot_meshes": len(scene["official_robot_meshes"]),
        "native_triangles": sum(
            s["triangles"] for s in scene["native_collision_surfaces"]
        ),
        "positive_training_samples_exported": 0,
        "dataset_split": "unassigned",
        "source_role": "development_validation",
        "limitations": scene["limitations"],
    }
    save(directory / "REPORT.json", result)
    # Native visual meshes only. Hiding collider duplicates is render-only.
    for i in range(model.ngeom):
        if (model.geom(i).name or "").startswith("robot_") and (
            model.geom_contype[i] or model.geom_conaffinity[i]
        ):
            model.geom_rgba[i, 3] = 0
    model.vis.global_.offwidth = 960
    model.vis.global_.offheight = 720
    options = mujoco.MjvOption()
    options.flexgroup[:] = 0
    renderer = mujoco.Renderer(model, height=720, width=960)
    cam = mujoco.MjvCamera()
    cam.type = mujoco.mjtCamera.mjCAMERA_FREE
    cam.azimuth = 80
    cam.elevation = -17
    cam.distance = 2.45
    cam.lookat[:] = [data.qpos[0] + 0.15, data.qpos[1] - 0.06, 0.83]
    renderer.update_scene(data, camera=cam, scene_option=options)
    frame = renderer.render().copy()
    cv2.rectangle(frame, (0, 0), (960, 46), (25, 25, 25), -1)
    cv2.putText(
        frame,
        "FULL G1 + NATIVE ROOM | STATIC ONLY - ADMISSION FAILED",
        (12, 29),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.58,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    cv2.imwrite(str(directory / "preview.jpg"), cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
    cam.azimuth = 35
    cam.distance = 4.5
    cam.elevation = -24
    cam.lookat[:] = [2.25, 2, 0.75]
    renderer.update_scene(data, camera=cam, scene_option=options)
    frame = renderer.render().copy()
    cv2.putText(
        frame,
        "STATIC ONLY - FULL G1 / NATIVE SCENE",
        (12, 29),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    cv2.imwrite(str(directory / "room.jpg"), cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
    renderer.close()
    save(
        directory / "MANIFEST.json",
        {
            "report": _file_binding(directory / "REPORT.json"),
            "preview": _file_binding(directory / "preview.jpg"),
            "room": _file_binding(directory / "room.jpg"),
            "physics_steps": 0,
            "task_passed": False,
            "proxy_robot": False,
            "render_only_hide_collision_duplicates": True,
            "implementation": _file_binding(Path(__file__)),
            "elapsed_s": time.monotonic() - started,
        },
    )
    print(
        {
            "fixed_fixed_contacts": len(invalid),
            "all_contacts": len(contacts),
            "deepest": contacts[:5],
            "visualization": str(directory),
        },
        flush=True,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--failed-build", type=Path, required=True)
    a = p.parse_args()
    run(a.root, a.failed_build)
