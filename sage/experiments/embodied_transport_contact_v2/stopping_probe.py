"""Reconstruct the discarded next policy output, without physical integration."""

import argparse
from pathlib import Path
import numpy as np
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from .control import SONIC
from sage.experiments.embodied_data_stability_v1 import (
    sonic_native_dynamic_shadow as native,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_full_shadow import (
    _make_session,
)
from sage.experiments.embodied_data_stability_v1.sonic_semantic_shadow import (
    ENCODER_ASSEMBLER,
    DECODER_ASSEMBLER,
    ACTION_SCALES,
    DEFAULT_ANGLES,
    body_joint_target_from_raw_action,
)
from sage.experiments.embodied_data_stability_v1.sonic_supported_shadow import (
    official_decoder_blocks,
    last_action_rows,
    guard_candidate,
)
from sage.experiments.embodied_data_stability_v1.sonic_offline_observation_mapper import (
    reorder_mujoco_to_isaaclab,
)
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def run(root):
    import mujoco

    path = root / "attempt_01/active_1000/REPORT.json"
    r = read_bound_json(path)
    t = read_bound_json(Path(r["trace"]["path"]))
    rows = t["records"]
    last = rows[-1]
    m = mujoco.MjModel.from_xml_path(r["model"]["path"])
    m.opt.timestep = 0.005
    d = mujoco.MjData(m)
    ids = native._model_ids(mujoco, m)
    pelvis = m.body("pelvis").id
    P = []
    V = []
    Q = []
    G = []

    def append_state(q, v):
        d.qpos[:] = q
        d.qvel[:] = v
        mujoco.mj_forward(m, d)
        P.append(d.qpos[ids["qpos_ids"]].copy())
        V.append(d.qvel[ids["dof_ids"]].copy())
        Q.append(d.qpos[3:7].copy())
        g = np.zeros(6)
        mujoco.mj_objectVelocity(m, d, mujoco.mjtObj.mjOBJ_BODY, pelvis, g, 1)
        G.append(g[:3].copy())

    for s in t["warmup_substeps"][::4]:
        append_state(s["full_qpos_before"], s["full_qvel_before"])
    for row in rows:
        P.append(np.array(row["actual_qpos"]))
        V.append(np.array(row["actual_qvel"]))
        Q.append(np.array(row["actual_quaternion"]))
        G.append(np.array(row["actual_gyro"]))
    actions = np.zeros((len(P) + 1, 29), dtype=np.float32)
    actions[:10] = reorder_mujoco_to_isaaclab(
        (
            np.array(t["warmup_substeps"][0]["position_target_rad"])
            - np.array(DEFAULT_ANGLES)
        )
        / np.array(ACTION_SCALES)
    )
    for row in rows:
        actions[row["tick"] + 10] = row["applied_raw_action_isaaclab"]
    encoder = _make_session(Path(r["inputs"]["encoder"]["path"]))
    decoder = _make_session(Path(r["inputs"]["decoder"]["path"]))

    def decode(enc, tick):
        token = encoder.run(None, {encoder.get_inputs()[0].name: enc})[0]
        dv = DECODER_ASSEMBLER.assemble(
            official_decoder_blocks(
                native._mapping_inputs(P, V, Q, G),
                tick,
                token,
                last_action_rows(actions, tick, legacy=False),
            )
        )
        return np.asarray(
            decoder.run(
                None, {decoder.get_inputs()[0].name: np.asarray([dv], dtype=np.float32)}
            )[0]
        ).reshape(29)

    baseline = decode(
        np.array([last["encoder_input_values"]], dtype=np.float32), last["tick"] + 10
    )
    if not np.array_equal(
        baseline, np.array(last["raw_action_isaaclab"], dtype=np.float32)
    ):
        raise ValueError("previous raw replay failed")
    sample = last["substeps"][-1]
    append_state(sample["full_qpos_after"], sample["full_qvel_after"])
    refs = np.load(path.parent / "reference_snapshots.npz")
    frame = last["reference_tick"] + 1
    values = ENCODER_ASSEMBLER.assemble(
        native.build_dynamic_g1_encoder_blocks(
            refs["final_qpos"],
            refs["final_velocity"],
            frame,
            initial_robot_quaternion_wxyz=np.array(
                t["warmup_substeps"][0]["full_qpos_before"][3:7]
            ),
            current_robot_quaternion_wxyz=Q[-1],
        )
    )
    raw = decode(np.asarray([values], dtype=np.float32), last["tick"] + 11)
    command = np.array(
        body_joint_target_from_raw_action(
            raw, phase="discarded_replay", sim_time_s=0
        ).position_target_rad
    )
    lower, upper = m.jnt_range[ids["joint_ids"]].T
    previous = np.array(last["candidate_rad"])
    full = guard_candidate(command, previous, lower, upper)
    consumed = {
        "finite": bool(np.isfinite(command).all()),
        "in_range": bool(
            np.all(command[SONIC] >= lower[SONIC])
            and np.all(command[SONIC] <= upper[SONIC])
        ),
        "max_step_rad": float(np.max(np.abs(command[SONIC] - previous[SONIC]))),
    }
    consumed["step_safe"] = consumed["max_step_rad"] <= native.MAX_CANDIDATE_STEP_RAD
    from .task import Task
    from sage.experiments.embodied_transport_v1.task import smooth
    case = read_bound_json(Path(r["case"]["path"]))
    start = next(e for e in t["reference_events"] if e["kind"] == "begin_carry_walk")
    brake = next(e for e in t["reference_events"] if e["kind"] == "brake" and e["frame"] > start["frame"])
    task = Task(_make_session(Path(r["inputs"]["planner"]["path"])), case, m, mujoco)
    task.q[start["frame"]] = start["start_pose"]
    carry_row = next(x for x in rows if x["sonic_candidate_consumed_by_physics"] and x["reference_tick"] == start["frame"])
    from types import SimpleNamespace
    task.begin_carry(start["frame"], SimpleNamespace(qpos=np.array(carry_row["substeps"][0]["full_qpos_before"])))
    unbraked = task.q.copy()
    profiles = []
    for duration in (55, 75, 95):
        q = unbraked.copy()
        f = brake["frame"]
        target = task.walk_start_pose.copy()
        target[:2] = q[f+duration,:2]
        target[3:7] = q[f,3:7]
        for j in range(f,len(q)):
            weight = float(smooth((j-f)/duration))
            q[j,:3] = (1-weight)*unbraked[j,:3] + weight*target[:3]
            q[j,3:7] = native._quaternion_slerp(unbraked[j,3:7],target[3:7],weight)
            q[j,7:] = (1-weight)*unbraked[j,7:] + weight*target[7:]
        v = native._reference_velocities(q)
        v[f+duration:] = 0
        values = ENCODER_ASSEMBLER.assemble(native.build_dynamic_g1_encoder_blocks(q,v,frame,
            initial_robot_quaternion_wxyz=np.array(t["warmup_substeps"][0]["full_qpos_before"][3:7]),
            current_robot_quaternion_wxyz=Q[-1]))
        newraw = decode(np.asarray([values],dtype=np.float32), last["tick"]+11)
        candidate = np.array(body_joint_target_from_raw_action(newraw,phase="counterfactual",sim_time_s=0).position_target_rad)
        margin = float(np.min(np.minimum(candidate[SONIC]-lower[SONIC],upper[SONIC]-candidate[SONIC])))
        delta = float(np.max(np.abs(candidate[SONIC]-previous[SONIC])))
        profiles.append({"duration_ticks":duration,"minimum_consumed22_margin_rad":margin,"max_step_rad":delta,
                         "guard_passed":margin >= 0 and delta <= native.MAX_CANDIDATE_STEP_RAD,
                         "right_ankle_pitch_target_rad":float(candidate[10]),
                         "baseline_exact":bool(np.array_equal(candidate,command)) if duration==55 else None})
    if not profiles[0]["baseline_exact"]:
        raise ValueError("counterfactual baseline reconstruction not exact")
    selected = next((p["duration_ticks"] for p in profiles[1:] if p["guard_passed"] and p["minimum_consumed22_margin_rad"] >= .02),None)
    result = {
        "profiles": profiles,
        "selected_carry_brake_duration_ticks": selected,
        "scope": "finite3-profile zero-physics causal stopping reference check on actual rejected state; prospective dynamics still require independent admission and full rerun",
        "new_physical_revision_budget": 2,
        "frame": frame,
        "previous_raw_replay_exact": True,
        "discarded_policy_command_rad": command.tolist(),
        "all29_guard": full,
        "consumed22_guard": consumed,
        "consumed22_violations": [{"joint": m.joint(int(ids["joint_ids"][i])).name, "target": float(command[i]), "lower": float(lower[i]), "upper": float(upper[i])} for i in SONIC if not lower[i] <= command[i] <= upper[i]],
        "physics_steps": 0,
        "report": _file_binding(path),
        "implementation": _file_binding(Path(__file__)),
    }
    save(root / "STOPPING_REFERENCE_PROBE.json", result)
    print(result)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    run(p.parse_args().root)
