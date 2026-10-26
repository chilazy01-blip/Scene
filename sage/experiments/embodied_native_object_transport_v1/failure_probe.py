"""Zero-step exact causal replay and a single planning-tolerance counterfactual."""

import argparse
from pathlib import Path
import numpy as np
from .task import Task as Original
from .task_v2 import Task as Proposed
from .protocol import authorize
from .report_safe_engine import safe_save
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def run(root):
    import mujoco

    p = authorize(root)
    r = read_bound_json(root / "version_01/full/REPORT.json")
    t = read_bound_json(root / "version_01/full/TRACE.json")
    m = load_model(r["model"]["path"])
    c = read_bound_json(Path(p["case"]["path"]))
    base = np.load(p["reference"]["path"], allow_pickle=False)
    outcomes = []
    for name, cls in (("original_5mm", Original), ("proposed_10mm", Proposed)):
        d = mujoco.MjData(m)
        task = cls(mujoco, m, c, base["q"], base["v"])
        previous = t["warmup_substeps"][-1]
        matched = True
        for row in t["records"]:
            s = row["substeps"][0]
            d.qpos[:] = s["full_qpos_before"]
            d.qvel[:] = s["full_qvel_before"]
            d.time = s["time_before_s"]
            mujoco.mj_kinematics(m, d)
            mujoco.mj_comPos(m, d)
            task.update(row["tick"], d, previous)
            task.synchronize(row["tick"], d)
            task.arm_target(row["tick"], d)
            matched &= (
                task.stage == row["stage"]
                and np.array_equal(task.q[row["tick"]], row["reference_qpos"])
                and np.array_equal(task.v[row["tick"]], row["reference_velocity"])
            )
            previous = row["substeps"][-1]
        d.qpos[:] = previous["full_qpos_after"]
        d.qvel[:] = previous["full_qvel_after"]
        d.time = previous["time_after_s"]
        mujoco.mj_kinematics(m, d)
        mujoco.mj_comPos(m, d)
        tick = len(t["records"])
        task.update(tick, d, previous)
        task.synchronize(tick, d)
        record = {
            "name": name,
            "all_recorded_reference_prefix_exact": bool(matched),
            "next_tick": tick,
            "failure": task.failure,
            "last_ik": task.last_ik,
            "physical_steps": 0,
        }
        if task.failure is None:
            arm = task.arm_target(tick, d)
            record["arm_servo_failure"] = task.failure
            record["next_arm_target"] = arm.tolist()
        outcomes.append(record)
        print(record, flush=True)
    assert outcomes[0]["failure"] == r["stop_reason"]
    assert all(o["all_recorded_reference_prefix_exact"] for o in outcomes)
    assert (
        outcomes[1]["failure"] is None and outcomes[1].get("arm_servo_failure") is None
    )
    safe_save(
        root / "PLANNING_TOLERANCE_CAUSAL_PROBE.json",
        {
            "schema": "native-mug-planning-tolerance-causal-probe/v1",
            "physics_steps": 0,
            "outcomes": outcomes,
            "report": _file_binding(root / "version_01/full/REPORT.json"),
            "audit": _file_binding(root / "version_01/full/AUDIT.json"),
            "original_source": _file_binding(Path(__file__).with_name("task.py")),
            "proposed_source": _file_binding(Path(__file__).with_name("task_v2.py")),
            "implementation": _file_binding(Path(__file__)),
            "not_dynamic_grasp_success": True,
            "change": "planning IK position residual gate5mm->10mm, below actual endpoint reach15mm criterion; all actual physical/model/motor and task gates unchanged",
        },
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    run(ap.parse_args().root)
