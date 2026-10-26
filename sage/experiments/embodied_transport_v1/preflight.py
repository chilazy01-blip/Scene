"""Finite zero-step task placement/arm reference preflight using prior evidence."""

import argparse
from pathlib import Path
import numpy as np
from .kinematics import solve
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


def run(prior, output):
    import mujoco

    if output.exists():
        raise FileExistsError(output)
    report = read_bound_json(prior / "continuation_01/walking_full/REPORT.json")
    trace = read_bound_json(Path(report["trace"]["path"]))
    model = mujoco.MjModel.from_xml_path(report["case_config"]["model_path"])
    data = mujoco.MjData(model)
    sample = trace["records"][49]["substeps"][-1]
    data.qpos[:] = sample["full_qpos_after"]
    mujoco.mj_forward(model, data)
    w = model.body("right_wrist_yaw_link").id
    obj = model.body("payload").id
    grip_local = data.xmat[w].reshape(3, 3).T @ (data.xpos[obj] - data.xpos[w])
    grip_rotation = data.xmat[w].reshape(3, 3).T @ data.xmat[obj].reshape(3, 3)
    target_rotation = grip_rotation.T
    pose = np.array(trace["records"][-1]["substeps"][-1]["full_qpos_after"])
    pose[:2] = [1.30, 2.72]
    outcomes = []
    for y in (2.40, 2.45, 2.50):
        center = np.array([1.45, y, 0.69])
        wrist = center - target_rotation @ grip_local
        result = solve(mujoco, model, pose, wrist, target_rotation)
        outcomes.append(
            {
                "object_center_m": center.tolist(),
                "desired_wrist_m": wrist.tolist(),
                **result,
            }
        )
    result = {
        "schema": "transport-geometric-preflight/v1",
        "prior_report": _file_binding(
            prior / "continuation_01/walking_full/REPORT.json"
        ),
        "grasp_local_xyz_m": grip_local.tolist(),
        "grasp_local_rotation": grip_rotation.tolist(),
        "desired_upright_wrist_rotation": target_rotation.tolist(),
        "nominal_pick_root_xy_m": [1.30, 2.72],
        "candidates": outcomes,
        "physics_steps": 0,
        "note": "three bounded placements for development workspace checks; no physical pickup success",
        "implementation": _file_binding(Path(__file__)),
        "ik": _file_binding(Path(__file__).with_name("kinematics.py")),
    }
    result["content_sha256_excluding_this_field"] = canonical_sha256(result)
    write_json_atomic(output, result)
    print(result)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--prior", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    run(a.prior, a.output)
