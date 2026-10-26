"""Zero-step reconstruction of the first rejected B command, no limit changes."""

import argparse
from pathlib import Path
import math
import numpy as np
from .protocol import require_motion_protocol
from .reference import Clock
from .dynamics_replay import rows
from .delivery import binding_ok
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
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
from sage.experiments.embodied_data_stability_v1.sonic_semantic_shadow import (
    DEFAULT_ANGLES,
    ACTION_SCALES,
    ENCODER_ASSEMBLER,
    DECODER_ASSEMBLER,
    body_joint_target_from_raw_action,
)
from sage.experiments.embodied_data_stability_v1.sonic_supported_shadow import (
    guard_candidate,
    official_decoder_blocks,
    last_action_rows,
)
from sage.experiments.embodied_data_stability_v1.sonic_offline_observation_mapper import (
    reorder_mujoco_to_isaaclab,
)


def run(root):
    import mujoco

    protocol = require_motion_protocol(root)
    output = root / "B_REJECTION_REVIEW.json"
    assert not output.exists()
    episode = root / "motion_v2/B/active_0750"
    report = read_bound_json(episode / "REPORT.json")
    audit = read_bound_json(episode / "AUDIT.json")
    binding_ok(audit["report"])
    binding_ok(report["trace"])
    assert [k for k, v in audit["gates"].items() if not v] == [
        "bounded_complete_prefix"
    ]
    trace = read_bound_json(Path(report["trace"]["path"]))
    rejected = trace["rejected_command"]
    assert rejected["tick"] == len(trace["records"]) == 711
    model = load_model(report["model"]["path"])
    model.opt.timestep = 0.005
    data = mujoco.MjData(model)
    ids = native._model_ids(mujoco, model)
    case = read_bound_json(Path(report["case"]["path"]))
    base = np.load(protocol["reference_base"]["path"], allow_pickle=False)
    clock = Clock(base["q"], base["v"], case, protocol["brake_ticks"])
    positions, velocities, quats, gyros = [], [], [], []
    actions = np.zeros((len(trace["records"]) + 11, 29), dtype=np.float32)
    pelvis = model.body("pelvis").id

    def reconstruct_state(q, v, t):
        data.qpos[:] = q
        data.qvel[:] = v
        data.time = t
        mujoco.mj_forward(model, data)

    def history():
        positions.append(data.qpos[ids["qpos_ids"]].copy())
        velocities.append(data.qvel[ids["dof_ids"]].copy())
        quats.append(data.qpos[3:7].copy())
        velocity = np.zeros(6)
        mujoco.mj_objectVelocity(
            model, data, mujoco.mjtObj.mjOBJ_BODY, pelvis, velocity, 1
        )
        gyros.append(velocity[:3].copy())

    for i in range(0, len(trace["warmup_substeps"]), 4):
        s = trace["warmup_substeps"][i]
        reconstruct_state(
            s["full_qpos_before"], s["full_qvel_before"], s["time_before_s"]
        )
        history()
        actions[i // 4] = reorder_mujoco_to_isaaclab(
            (clock.q[0, 7:] - np.asarray(DEFAULT_ANGLES)) / np.asarray(ACTION_SCALES)
        )
    active_samples = []
    for row in trace["records"]:
        s = row["substeps"][0]
        # Clock needs only recorded physical root/velocity/time. All such rows
        # have already passed independent state/NN/contact reconstruction.
        data.qpos[:] = s["full_qpos_before"]
        data.qvel[:] = s["full_qvel_before"]
        data.time = s["time_before_s"]
        frame = clock.update(row["tick"], data, active_samples)
        assert clock.snapshot(frame) == row["clock"]
        positions.append(np.asarray(row["actual_qpos"]))
        velocities.append(np.asarray(row["actual_qvel"]))
        quats.append(np.asarray(row["actual_quaternion"]))
        gyros.append(np.asarray(row["actual_gyro"]))
        actions[row["tick"] + 10] = row["raw_action_isaaclab"]
        active_samples.extend(row["substeps"])
    last = active_samples[-1]
    reconstruct_state(
        last["full_qpos_after"], last["full_qvel_after"], last["time_after_s"]
    )
    frame = clock.update(rejected["tick"], data, active_samples)
    assert clock.snapshot(frame) == rejected["clock"]
    history()
    inputs = native._mapping_inputs(positions, velocities, quats, gyros)
    encoder_input = np.array(
        [
            ENCODER_ASSEMBLER.assemble(
                native.build_dynamic_g1_encoder_blocks(
                    clock.q,
                    clock.v,
                    frame,
                    initial_robot_quaternion_wxyz=trace["initial_qpos"][3:7],
                    current_robot_quaternion_wxyz=quats[-1],
                )
            )
        ],
        dtype=np.float32,
    )
    encoder = _make_session(Path(protocol["inputs"]["encoder"]["path"]))
    token = encoder.run(None, {encoder.get_inputs()[0].name: encoder_input})[0]
    decoder_input = np.array(
        [
            DECODER_ASSEMBLER.assemble(
                official_decoder_blocks(
                    inputs,
                    rejected["tick"] + 10,
                    token,
                    last_action_rows(actions, rejected["tick"] + 10, legacy=False),
                )
            )
        ],
        dtype=np.float32,
    )
    decoder = _make_session(Path(protocol["inputs"]["decoder"]["path"]))
    raw = np.asarray(
        decoder.run(None, {decoder.get_inputs()[0].name: decoder_input})[0],
        dtype=np.float32,
    ).reshape(29)
    candidate = np.asarray(
        body_joint_target_from_raw_action(
            raw, phase="native_walk", sim_time_s=float(data.time)
        ).position_target_rad
    )
    checks = {
        "encoder_input_from_actual_state_and_causal_reference": np.array_equal(
            encoder_input[0],
            np.asarray(rejected["encoder_input_values"], dtype=np.float32),
        ),
        "decoder_input_from_actual_history": np.array_equal(
            decoder_input[0],
            np.asarray(rejected["decoder_input_values"], dtype=np.float32),
        ),
        "raw_decoder_bitwise": np.array_equal(
            raw, np.asarray(rejected["raw_action_isaaclab"], dtype=np.float32)
        ),
        "target_transform_exact": candidate.tolist() == rejected["candidate_rad"],
    }
    assert all(checks.values()), checks
    lo, hi = model.jnt_range[ids["joint_ids"]].T
    guard = guard_candidate(
        candidate, np.asarray(trace["records"][-1]["candidate_rad"]), lo, hi
    )
    assert guard == rejected["candidate_guard"] == rejected["executed_guard"]
    assert guard["finite"] and guard["step_safe"] and not guard["in_range"]
    assert len(guard["out_of_range_joints"]) == 1
    breach = guard["out_of_range_joints"][0]
    excess = breach["target_rad"] - breach["upper_rad"]
    samples = list(rows(trace))
    result = {
        "schema": "native-walk-command-rejection-review/v1",
        "physics_steps": 0,
        "checks": {k: bool(v) for k, v in checks.items()},
        "rejected_tick": rejected["tick"],
        "time_s": float(data.time),
        "joint": breach["joint"],
        "requested_rad": breach["target_rad"],
        "native_upper_rad": breach["upper_rad"],
        "excess_rad": excess,
        "excess_deg": math.degrees(excess),
        "actual_joint_rad_at_rejection": float(
            data.qpos[model.joint(breach["joint"]).qposadr[0]]
        ),
        "command_never_applied": not any(
            row["tick"] == rejected["tick"] for row in trace["records"]
        ),
        "recorded_physical_steps_all_safe": all(s["safe"] for s in samples),
        "forbidden_contacts": sum(s["forbidden_contacts"] for s in samples),
        "maximum_penetration_m": max(s["penetration_m"] for s in samples),
        "maximum_contact_force_n": max(s["contact_force_n"] for s in samples),
        "cause": "the frozen SONIC policy requested right ankle pitch slightly above original native target-angle range. Prewrite guard correctly refused it; not a scene solver failure, scene contact, or executed unsafe command",
        "not_proven": "the deeper reason why this condition's policy target crosses the limit; no proposed repair has been validated",
        "control_versions_used": 2,
        "control_version_cap": protocol["max_causal_versions"],
        "next_step_requires_new_bounded_controller_revision_authority": True,
        "do_not_change": "native environment/layout/collision, original joint/effort/physical limits, or three-condition acceptance",
        "report": _file_binding(episode / "REPORT.json"),
        "audit": _file_binding(episode / "AUDIT.json"),
        "implementation": _file_binding(Path(__file__)),
    }
    save(output, result)
    print(
        {
            k: result[k]
            for k in (
                "checks",
                "joint",
                "excess_deg",
                "actual_joint_rad_at_rejection",
                "physics_steps",
            )
        },
        flush=True,
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    run(ap.parse_args().root)
