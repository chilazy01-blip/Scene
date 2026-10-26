#!/usr/bin/env python3
"""Build a bounded kinematic G1 mug pick-and-place visual trajectory.

The leg and torso posture comes from a recorded stable physics rollout.  The
right arm is solved with bounded MuJoCo forward-kinematics IK, while the mug is
kept upright and follows the measured palm path between close and release.
This is a task-level visual demonstration, not a new physics rollout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import mujoco
import numpy as np
from scipy.optimize import least_squares


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def smoothstep(value: float) -> float:
    value = float(np.clip(value, 0.0, 1.0))
    return value * value * (3.0 - 2.0 * value)


def interpolate_keyframes(times: np.ndarray, keyframes: list[tuple[float, np.ndarray]]):
    output = []
    for time_s in times:
        if time_s <= keyframes[0][0]:
            output.append(keyframes[0][1].copy())
            continue
        if time_s >= keyframes[-1][0]:
            output.append(keyframes[-1][1].copy())
            continue
        for (time_a, value_a), (time_b, value_b) in zip(keyframes, keyframes[1:]):
            if time_a <= time_s <= time_b:
                alpha = smoothstep((time_s - time_a) / (time_b - time_a))
                output.append((1.0 - alpha) * value_a + alpha * value_b)
                break
    return np.asarray(output)


def joint_qpos_address(model, name: str) -> int:
    joint_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, name)
    if joint_id < 0:
        raise RuntimeError(f"joint not found: {name}")
    return int(model.jnt_qposadr[joint_id])


def solve_palm_position(
    model,
    data,
    base_qpos: np.ndarray,
    arm_addresses: np.ndarray,
    palm_body_id: int,
    target: np.ndarray,
    seed: np.ndarray,
    posture_reference: np.ndarray,
) -> tuple[np.ndarray, float]:
    joint_ids = [
        mujoco.mj_name2id(
            model,
            mujoco.mjtObj.mjOBJ_JOINT,
            name,
        )
        for name in (
            "right_shoulder_pitch_joint",
            "right_shoulder_roll_joint",
            "right_shoulder_yaw_joint",
            "right_elbow_joint",
            "right_wrist_roll_joint",
            "right_wrist_pitch_joint",
            "right_wrist_yaw_joint",
        )
    ]
    lower = model.jnt_range[joint_ids, 0]
    upper = model.jnt_range[joint_ids, 1]
    # The raw model permits the elbow to fold backwards.  That is useful for
    # optimization but reads as a broken/overhead arm in this tabletop task.
    lower[3] = max(lower[3], 0.10)
    work_qpos = base_qpos.copy()

    def residual(arm_qpos: np.ndarray) -> np.ndarray:
        work_qpos[arm_addresses] = arm_qpos
        data.qpos[:] = work_qpos
        mujoco.mj_forward(model, data)
        position_error = (data.xpos[palm_body_id] - target) * 30.0
        # Keep the redundant arm near its relaxed branch.  A near-zero weight
        # lets a position-only solve choose visually valid but contorted
        # shoulder and wrist configurations.
        posture_error = (arm_qpos - posture_reference) * 0.03
        return np.concatenate([position_error, posture_error])

    result = least_squares(
        residual,
        seed,
        bounds=(lower, upper),
        max_nfev=240,
        xtol=1.0e-10,
        ftol=1.0e-10,
        gtol=1.0e-10,
    )
    work_qpos[arm_addresses] = result.x
    data.qpos[:] = work_qpos
    mujoco.mj_forward(model, data)
    error = float(np.linalg.norm(data.xpos[palm_body_id] - target))
    if error > 0.005:
        raise RuntimeError(f"right-palm IK residual too large: {error:.6f} m")
    return result.x.copy(), error


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--source-trajectory", type=Path, required=True)
    parser.add_argument("--visuals", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fps", type=int, default=15)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    model = mujoco.MjModel.from_binary_path(str(args.model))
    data = mujoco.MjData(model)
    source = np.load(args.source_trajectory)
    visual_rows = json.loads(args.visuals.read_text())

    q_reference = source["qpos"][-1].copy()
    q_reference[:3] = np.array([1.62, 0.78, 0.762])
    # Face south toward the dresser and its existing bedside mug.
    q_reference[3:7] = np.array([np.sqrt(0.5), 0.0, 0.0, -np.sqrt(0.5)])

    arm_names = (
        "right_shoulder_pitch_joint",
        "right_shoulder_roll_joint",
        "right_shoulder_yaw_joint",
        "right_elbow_joint",
        "right_wrist_roll_joint",
        "right_wrist_pitch_joint",
        "right_wrist_yaw_joint",
    )
    finger_names = (
        "right_hand_thumb_0_joint",
        "right_hand_thumb_1_joint",
        "right_hand_thumb_2_joint",
        "right_hand_index_0_joint",
        "right_hand_index_1_joint",
        "right_hand_middle_0_joint",
        "right_hand_middle_1_joint",
    )
    arm_addresses = np.asarray(
        [joint_qpos_address(model, name) for name in arm_names], dtype=int
    )
    finger_addresses = np.asarray(
        [joint_qpos_address(model, name) for name in finger_names], dtype=int
    )
    palm_body_id = mujoco.mj_name2id(
        model,
        mujoco.mjtObj.mjOBJ_BODY,
        "right_hand_palm_link",
    )
    if palm_body_id < 0:
        raise RuntimeError("right palm body not found")

    arm_rest = q_reference[arm_addresses].copy()
    targets = {
        "pregrasp": np.array([1.41, 0.52, 0.98]),
        "grasp": np.array([1.41, 0.42, 0.98]),
        "lift": np.array([1.41, 0.42, 1.10]),
        "carry": np.array([1.32, 0.42, 1.10]),
        "place": np.array([1.32, 0.42, 0.98]),
        "retract": np.array([1.32, 0.52, 1.02]),
    }
    solved = {}
    residuals = {}
    seed = arm_rest.copy()
    # Solve only contact/carry poses.  Approach and retract are joint-space
    # blends on the same branch; solving them independently makes the
    # redundant arm flip its wrist even when the palm target is nearby.
    for name in ("grasp", "lift", "carry", "place"):
        target = targets[name]
        try:
            seed, residual = solve_palm_position(
                model,
                data,
                q_reference,
                arm_addresses,
                palm_body_id,
                target,
                seed,
                arm_rest,
            )
        except RuntimeError as exc:
            raise RuntimeError(f"{name}: {exc}") from exc
        solved[name] = seed.copy()
        residuals[name] = residual
    solved["pregrasp"] = 0.72 * solved["grasp"] + 0.28 * arm_rest
    solved["retract"] = 0.62 * solved["place"] + 0.38 * arm_rest

    open_fingers = q_reference[finger_addresses].copy()
    closed_fingers = np.array([0.85, -0.878, -1.477, 1.163, 1.498, 1.393, 1.5])
    phase_times = {
        "rest_start": 0.0,
        "pregrasp": 1.5,
        "grasp_open": 2.5,
        "grasp_closed": 3.2,
        "lift": 4.2,
        "carry": 5.5,
        "place": 6.7,
        "release": 7.4,
        "retract": 8.4,
        "rest_end": 9.8,
    }
    frame_count = int(round(phase_times["rest_end"] * args.fps)) + 1
    times = np.arange(frame_count, dtype=float) / args.fps

    arm_keyframes = [
        (phase_times["rest_start"], arm_rest),
        (phase_times["pregrasp"], solved["pregrasp"]),
        (phase_times["grasp_open"], solved["grasp"]),
        (phase_times["grasp_closed"], solved["grasp"]),
        (phase_times["lift"], solved["lift"]),
        (phase_times["carry"], solved["carry"]),
        (phase_times["place"], solved["place"]),
        (phase_times["release"], solved["place"]),
        (phase_times["retract"], solved["retract"]),
        (phase_times["rest_end"], arm_rest),
    ]
    finger_keyframes = [
        (phase_times["rest_start"], open_fingers),
        (phase_times["grasp_open"], open_fingers),
        (phase_times["grasp_closed"], closed_fingers),
        (phase_times["place"], closed_fingers),
        (phase_times["release"], open_fingers),
        (phase_times["rest_end"], open_fingers),
    ]
    arm_trajectory = interpolate_keyframes(times, arm_keyframes)
    finger_trajectory = interpolate_keyframes(times, finger_keyframes)

    qpos = np.repeat(q_reference[None, :], frame_count, axis=0)
    qpos[:, arm_addresses] = arm_trajectory
    qpos[:, finger_addresses] = finger_trajectory

    geom_ids = []
    for row in visual_rows:
        geom_id = mujoco.mj_name2id(
            model,
            mujoco.mjtObj.mjOBJ_GEOM,
            row["geom_name"],
        )
        if geom_id < 0:
            raise RuntimeError(f"visual geometry not found: {row['geom_name']}")
        geom_ids.append(geom_id)
    geom_ids = np.asarray(geom_ids, dtype=int)

    positions = np.empty((frame_count, len(geom_ids), 3), dtype=float)
    matrices = np.empty((frame_count, len(geom_ids), 3, 3), dtype=float)
    palm_positions = np.empty((frame_count, 3), dtype=float)
    for index, row in enumerate(qpos):
        data.qpos[:] = row
        mujoco.mj_forward(model, data)
        positions[index] = data.geom_xpos[geom_ids]
        matrices[index] = data.geom_xmat[geom_ids].reshape(-1, 3, 3)
        palm_positions[index] = data.xpos[palm_body_id]

    mug_start = np.array([1.4104, 0.3097, 0.9553])
    mug_offset = mug_start - targets["grasp"]
    mug_place = targets["place"] + mug_offset
    cup_positions = np.repeat(mug_start[None, :], frame_count, axis=0)
    for index, time_s in enumerate(times):
        if phase_times["grasp_closed"] <= time_s <= phase_times["place"]:
            cup_positions[index] = palm_positions[index] + mug_offset
        elif time_s > phase_times["place"]:
            cup_positions[index] = mug_place
    cup_matrices = np.repeat(np.eye(3)[None, :, :], frame_count, axis=0)

    trajectory_path = args.output / "ROBOT_CUP_VISUAL_TRAJECTORY.npz"
    np.savez_compressed(
        trajectory_path,
        qpos=qpos,
        positions=positions,
        matrices=matrices,
        times=times,
        cup_positions=cup_positions,
        cup_matrices=cup_matrices,
        right_palm_positions=palm_positions,
    )
    report = {
        "schema": "bedroom_g1_cup_pick_place_visual_v1",
        "label": "task_level_kinematic_visual_demo_not_physics_validated",
        "model": str(args.model),
        "model_sha256": sha256(args.model),
        "source_stable_trajectory": str(args.source_trajectory),
        "source_stable_trajectory_sha256": sha256(args.source_trajectory),
        "visuals": str(args.visuals),
        "trajectory": str(trajectory_path),
        "fps": args.fps,
        "frames": frame_count,
        "duration_s": frame_count / args.fps,
        "robot_base_xyz_m": q_reference[:3].tolist(),
        "robot_base_yaw_deg": -90.0,
        "cup_source_object": "bedside_mug_root",
        "cup_geometry_reused_from_scene": True,
        "cup_start_xyz_m": mug_start.tolist(),
        "cup_place_xyz_m": mug_place.tolist(),
        "cup_displacement_m": float(np.linalg.norm(mug_place - mug_start)),
        "right_palm_ik_residual_m": residuals,
        "approach_retract_generation": "joint_space_blends_on_contact_ik_branch",
        "arm_motion_design": {
            "same_side_work_envelope": True,
            "elbow_minimum_rad": 0.10,
            "redundant_ik_posture_weight": 0.03,
            "independently_solved_keyframes": ["grasp", "lift", "carry", "place"],
        },
        "cup_attachment": {
            "attach_at_phase": "grasp_closed",
            "detach_at_phase": "place",
            "kept_upright": True,
        },
        "phase_times_s": phase_times,
        "physical_simulation_executed": False,
        "collision_validation_executed": False,
        "production_accepted": False,
    }
    (args.output / "REPORT.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
