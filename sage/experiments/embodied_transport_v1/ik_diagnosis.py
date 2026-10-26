"""Three bounded saved-state IK probes; no integration or actual-state writes."""

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


def run(root):
    import mujoco

    report_path = root / "continuation_01/active_0300/REPORT.json"
    report = read_bound_json(report_path)
    trace = read_bound_json(Path(report["trace"]["path"]))
    case = read_bound_json(root / "CASE.json")
    sample = trace["records"][-1]["substeps"][-1]
    model = mujoco.MjModel.from_xml_path(case["model_path"])
    q = np.array(sample["full_qpos_after"])
    R = np.array(case["desired_wrist_rotation"])
    local = np.array(case["grasp_local_xyz_m"])
    outcomes = []
    for y in (2.40, 2.45, 2.50):
        center = np.array([1.45, y, sample["payload"]["world_position_m"][2]])
        result = solve(mujoco, model, q, center - R @ local, R, max_evaluations=400)
        outcomes.append({"source_y_m": y, **result})
    data = mujoco.MjData(model)
    data.qpos[:] = q
    mujoco.mj_forward(model, data)
    positions = {
        name: data.xpos[model.body(name).id].tolist()
        for name in (
            "right_shoulder_pitch_link",
            "right_elbow_link",
            "right_wrist_yaw_link",
        )
    }
    result = {
        "schema": "transport-saved-state-IK-diagnosis/v1",
        "rejected_report": _file_binding(report_path),
        "original_root_qpos": q[:7].tolist(),
        "body_positions": positions,
        "probes": outcomes,
        "physics_steps": 0,
        "implementation": _file_binding(Path(__file__)),
    }
    result["content_sha256_excluding_this_field"] = canonical_sha256(result)
    write_json_atomic(root / "IK_DIAGNOSIS.json", result)
    print(result)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    run(p.parse_args().root)
