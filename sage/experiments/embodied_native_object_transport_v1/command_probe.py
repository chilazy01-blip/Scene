"""Zero-step reconstruction of the unexecuted command and reference ablations."""

import argparse
from pathlib import Path
import numpy as np
from .protocol_v2 import authorize
from .task_v2 import Task
from .report_safe_engine import safe_save
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_transport_hybrid_v1.control import ARM
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)
from sage.experiments.embodied_data_stability_v1 import (
    sonic_native_dynamic_shadow as native,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_full_shadow import (
    _make_session,
)
from sage.experiments.embodied_data_stability_v1.sonic_supported_shadow import (
    official_decoder_blocks,
    last_action_rows,
)
from sage.experiments.embodied_data_stability_v1.sonic_semantic_shadow import (
    DEFAULT_ANGLES,
    ACTION_SCALES,
    ENCODER_ASSEMBLER,
    DECODER_ASSEMBLER,
    body_joint_target_from_raw_action,
)
from sage.experiments.embodied_data_stability_v1.sonic_offline_observation_mapper import (
    reorder_mujoco_to_isaaclab,
)


def run(root):
    import mujoco

    p = authorize(root)
    episode = root / "version_02/full"
    r = read_bound_json(episode / "REPORT.json")
    t = read_bound_json(episode / "TRACE.json")
    assert r["stop_reason"] == "large target range excess"
    c = read_bound_json(Path(p["case"]["path"]))
    base = np.load(p["reference"]["path"], allow_pickle=False)
    m = load_model(r["model"]["path"])
    d = mujoco.MjData(m)
    ids = native._model_ids(mujoco, m)
    task = Task(mujoco, m, c, base["q"], base["v"])
    positions = []
    velocities = []
    quats = []
    gyros = []
    actions = np.zeros((len(t["records"]) + 11, 29), dtype=np.float32)
    pelvis = m.body("pelvis").id

    def setstate(q, v, time):
        d.qpos[:] = q
        d.qvel[:] = v
        d.time = time
        mujoco.mj_kinematics(m, d)
        mujoco.mj_comPos(m, d)
        mujoco.mj_comVel(m, d)

    def history():
        positions.append(d.qpos[ids["qpos_ids"]].copy())
        velocities.append(d.qvel[ids["dof_ids"]].copy())
        quats.append(d.qpos[3:7].copy())
        g = np.zeros(6)
        mujoco.mj_objectVelocity(m, d, mujoco.mjtObj.mjOBJ_BODY, pelvis, g, 1)
        gyros.append(g[:3].copy())

    for i in range(0, len(t["warmup_substeps"]), 4):
        s = t["warmup_substeps"][i]
        setstate(s["full_qpos_before"], s["full_qvel_before"], s["time_before_s"])
        history()
        actions[i // 4] = reorder_mujoco_to_isaaclab(
            (task.q[0, 7:] - np.asarray(DEFAULT_ANGLES)) / np.asarray(ACTION_SCALES)
        )
    previous = t["warmup_substeps"][-1]
    prefix = True
    for row in t["records"]:
        s = row["substeps"][0]
        setstate(s["full_qpos_before"], s["full_qvel_before"], s["time_before_s"])
        task.update(row["tick"], d, previous)
        task.synchronize(row["tick"], d)
        task.arm_target(row["tick"], d)
        prefix &= np.array_equal(
            task.q[row["tick"]], row["reference_qpos"]
        ) and np.array_equal(task.v[row["tick"]], row["reference_velocity"])
        positions.append(np.asarray(row["actual_body_qpos"]))
        velocities.append(np.asarray(row["actual_body_qvel"]))
        quats.append(np.asarray(row["actual_quaternion"]))
        gyros.append(np.asarray(row["actual_gyro"]))
        actions[row["tick"] + 10] = row["applied_action_isaaclab"]
        previous = row["substeps"][-1]
    tick = len(t["records"])
    setstate(
        previous["full_qpos_after"],
        previous["full_qvel_after"],
        previous["time_after_s"],
    )
    task.update(tick, d, previous)
    task.synchronize(tick, d)
    arm = task.arm_target(tick, d)
    history()
    assert prefix and not task.failure
    inputs = native._mapping_inputs(positions, velocities, quats, gyros)
    encoder = _make_session(Path(p["inputs"]["encoder"]["path"]))
    decoder = _make_session(Path(p["inputs"]["decoder"]["path"]))
    lo, hi = m.jnt_range[ids["joint_ids"]].T
    index = [m.joint(int(j)).name for j in ids["joint_ids"]].index(
        "right_ankle_pitch_joint"
    )
    q = task.q.copy()
    v = task.v.copy()
    held = q.copy()
    held[:, ARM + 7] = d.qpos[task.armq]
    heldv = v.copy()
    heldv[:, ARM] = 0
    neutral = np.repeat(base["q"][:1], len(q), axis=0)
    neutral[:, ARM + 7] = d.qpos[task.armq]
    zero = np.zeros_like(v)
    outcomes = []
    for name, ref, vel in (
        ("actual_frozen_reference", q, v),
        ("hold_actual_arm_forecast", held, heldv),
        ("idle_body_hold_actual_arm_forecast", neutral, zero),
    ):
        enc = np.array(
            [
                ENCODER_ASSEMBLER.assemble(
                    native.build_dynamic_g1_encoder_blocks(
                        ref,
                        vel,
                        tick,
                        initial_robot_quaternion_wxyz=t["initial_qpos"][3:7],
                        current_robot_quaternion_wxyz=quats[-1],
                    )
                )
            ],
            dtype=np.float32,
        )
        token = encoder.run(None, {encoder.get_inputs()[0].name: enc})[0]
        dec = np.array(
            [
                DECODER_ASSEMBLER.assemble(
                    official_decoder_blocks(
                        inputs,
                        tick + 10,
                        token,
                        last_action_rows(actions, tick + 10, legacy=False),
                    )
                )
            ],
            dtype=np.float32,
        )
        raw = np.asarray(
            decoder.run(None, {decoder.get_inputs()[0].name: dec})[0], dtype=np.float32
        ).reshape(29)
        target = np.asarray(
            body_joint_target_from_raw_action(
                raw, phase="native_mug_transport", sim_time_s=float(d.time)
            ).position_target_rad
        )
        target[ARM] = arm[ARM]
        if name == "actual_frozen_reference":
            assert np.array_equal(
                raw, np.asarray(t["rejected_command"]["raw"], dtype=np.float32)
            )
            assert target.tolist() == t["rejected_command"]["mixed"]
        excess = target - np.clip(target, lo, hi)
        outcome = {
            "name": name,
            "right_ankle_pitch_target_rad": float(target[index]),
            "right_ankle_excess_deg": float(
                np.degrees(max(0.0, target[index] - hi[index]))
            ),
            "maximum_target_projection_rad": float(np.max(np.abs(excess))),
            "raw_action": raw.tolist(),
            "not_executed": True,
        }
        outcomes.append(outcome)
        print({k: v for k, v in outcome.items() if k != "raw_action"}, flush=True)
    safe_save(
        root / "COMMAND_REFERENCE_CAUSAL_PROBE.json",
        {
            "schema": "native-mug-command-reference-probe/v1",
            "physics_steps": 0,
            "rejected_tick": tick,
            "time_s": float(d.time),
            "actual_rejected_command_bitwise_reproduced": True,
            "all_applied_reference_prefix_exact": bool(prefix),
            "outcomes": outcomes,
            "scope": "one unexecuted-command counterfactual, not validated dynamic repair or successful grasp",
            "all_actual_physical_steps_safe": all(
                s["safe"]
                for s in t["warmup_substeps"]
                + [s for row in t["records"] for s in row["substeps"]]
            ),
            "report": _file_binding(episode / "REPORT.json"),
            "implementation": _file_binding(Path(__file__)),
        },
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    run(ap.parse_args().root)
