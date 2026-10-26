"""Separate native-range finger PD and measured free-payload accounting."""

import numpy as np
from .grasp import payload_metrics
from sage.experiments.embodied_data_stability_v1.sonic_playback_shadow import (
    build_reference as idle_reference,
)
from sage.experiments.embodied_locomotion_v1.reference import walking


def reference(planner, case):
    if case["carry_mode"] == "walking":
        return walking(planner)
    q, metadata, v = idle_reference(planner, 0)
    n = max(0, 600 - len(q))
    q = np.concatenate([q, np.repeat(q[-1:], n, axis=0)])
    v = np.concatenate([v, np.zeros((n, 29))])
    metadata.update(
        mode=0,
        target_speed_m_s=-1.0,
        stop_preview_protocol="measured_goal_triggered_quintic",
        motion_kind="standing hold, no goal-triggered motion",
    )
    return q, v, metadata


def setup(mujoco, model, data, case):
    names = [
        model.joint(i).name
        for i in range(model.njnt)
        if "_hand_" in model.joint(i).name
    ]
    qids = np.array([int(model.joint(n).qposadr[0]) for n in names])
    dofs = np.array([int(model.joint(n).dofadr[0]) for n in names])
    act = np.array([model.actuator(n).id for n in names])
    initial = np.array([case["initial_right_hand_targets"].get(n, 0.0) for n in names])
    target = np.array([case["right_hand_targets"].get(n, 0.0) for n in names])
    lower = np.array([model.joint(n).range[0] for n in names])
    upper = np.array([model.joint(n).range[1] for n in names])
    if (
        np.any(target < lower)
        or np.any(target > upper)
        or np.any(initial < lower)
        or np.any(initial > upper)
    ):
        raise ValueError("hand target range")
    data.qpos[qids] = initial
    mujoco.mj_forward(model, data)
    wrist = model.body("right_wrist_yaw_link").id
    adr = int(model.joint("payload_free").qposadr[0])
    local = np.array(case["payload_local_xyz_m"])
    data.qpos[adr : adr + 3] = data.xpos[wrist] + data.xmat[wrist].reshape(3, 3) @ local
    data.qpos[adr + 3 : adr + 7] = data.xquat[wrist]
    mujoco.mj_forward(model, data)
    return {
        "names": names,
        "qpos": qids,
        "dofs": dofs,
        "actuators": act,
        "target": target,
        "kp": np.array([2.0 if "thumb_0" in n else 1.5 for n in names]),
        "kd": 0.1,
        "effort": model.actuator_ctrlrange[act, 1].copy(),
        "initial_local": local,
    }


def apply(model, data, hand):
    q = data.qpos[hand["qpos"]].copy()
    v = data.qvel[hand["dofs"]].copy()
    torque = np.clip(
        hand["kp"] * (hand["target"] - q) - hand["kd"] * v,
        -hand["effort"],
        hand["effort"],
    )
    data.ctrl[hand["actuators"]] = torque
    return {
        "positions_before_rad": q.tolist(),
        "velocities_before_rad_s": v.tolist(),
        "target_rad": hand["target"].tolist(),
        "torque_nm": torque.tolist(),
        "joint_names": hand["names"],
        "kp": hand["kp"].tolist(),
        "kd": hand["kd"],
        "effort_limit_nm": hand["effort"].tolist(),
    }


def acceptance(records, budget, case):
    rows = [r for r in records if r["sonic_candidate_consumed_by_physics"]]
    samples = [s for r in rows for s in r["substeps"]]
    if not samples:
        return {"passed": False, "gates": {}, "metrics": {}}
    held = sum(s["payload"]["held"] for s in samples) / len(samples)
    slip = max(s["payload"]["relative_position_error_m"] for s in samples)
    bad = any(s["payload"]["non_hand_contact"] for s in samples)
    gates = {
        "complete_protocol": len(rows) == budget and len(samples) == budget * 4,
        "contact_supported_retention": held >= 0.9,
        "relative_slip": slip <= 0.03,
        "no_non_hand_support": not bad,
        "object_above_floor": min(s["payload"]["height_m"] for s in samples) >= 0.25,
        "no_pelvis_support": all(
            not s["support_enabled"] and not any(s["support_wrench"]) for s in samples
        ),
    }
    if case["carry_mode"] == "walking":
        from sage.experiments.embodied_locomotion_v1.metrics import accept

        task = accept(records, budget, case)
        gates["locomotion_and_stop"] = task["passed"]
    return {
        "passed": all(gates.values()),
        "gates": gates,
        "metrics": {
            "held_contact_fraction": held,
            "max_relative_slip_m": slip,
            "active_steps": len(samples),
        },
        "thresholds": {
            "min_held_contact_fraction": 0.9,
            "max_slip_m": 0.03,
            "minimum_object_height_m": 0.25,
        },
        "preloaded_grasp_not_pickup": True,
    }
