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
    result = {
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
    save(root / "REJECTED_COMMAND_REPLAY.json", result)
    print(result)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    run(p.parse_args().root)
