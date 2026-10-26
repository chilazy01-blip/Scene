#!/usr/bin/env python3
"""Match a fixed-base G1 visual pose to the simulated book-pusher path."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import mujoco
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation

from bedroom_g1_cup_pick_place_v3 import (
    ARM_NAMES,
    FINGER_NAMES,
    PALM_TARGET_ROTATION,
    joint_addresses,
    palm_pose,
    solve_palm_pose,
)


ROBOT_BASE_XYZ = np.array([1.50, 0.86, 0.762], dtype=float)
ROBOT_BASE_YAW_DEG = -90.0
# Point the index finger through the broad front opening.  This offset places
# the center of its distal link on the simulated fingertip contact proxy.
BOOK_PUSH_PALM_ROTATION = PALM_TARGET_ROTATION.copy()
PALM_FROM_CONTACT_WORLD = np.array([-0.0325, 0.1719, -0.0511], dtype=float)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_position_seed(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    base_qpos: np.ndarray,
    addresses: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    palm_body_id: int,
    target: np.ndarray,
) -> tuple[np.ndarray, float]:
    """Find a reachable deterministic branch before freezing its orientation."""
    reference = base_qpos[addresses].copy()
    work = base_qpos.copy()

    def residual(arm_qpos: np.ndarray) -> np.ndarray:
        work[addresses] = arm_qpos
        data.qpos[:] = work
        mujoco.mj_kinematics(model, data)
        position = (data.xpos[palm_body_id] - target) * 80.0
        posture = (arm_qpos - reference) * 0.004
        return np.concatenate([position, posture])

    rng = np.random.default_rng(20261014)
    candidates: list[tuple[float, float, np.ndarray]] = []
    seeds = [reference, *[rng.uniform(lower, upper) for _ in range(64)]]
    for seed in seeds:
        result = least_squares(
            residual,
            np.clip(seed, lower + 1.0e-8, upper - 1.0e-8),
            bounds=(lower, upper),
            max_nfev=600,
            xtol=1.0e-11,
            ftol=1.0e-11,
            gtol=1.0e-11,
        )
        work[addresses] = result.x
        position, _ = palm_pose(model, data, work, palm_body_id)
        position_error = float(np.linalg.norm(position - target))
        posture_distance = float(np.linalg.norm(result.x - reference))
        candidates.append((position_error, posture_distance, result.x.copy()))
    reachable = [row for row in candidates if row[0] < 0.001]
    if not reachable:
        best = min(candidates, key=lambda row: row[0])
        raise RuntimeError(f"palm target unreachable; best error={best[0]:.6f} m")
    best = min(reachable, key=lambda row: row[1])
    return best[2], best[0]


def solve_continuous_palm_pose(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    base_qpos: np.ndarray,
    arm_addresses: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    palm_body_id: int,
    target_position: np.ndarray,
    target_rotation: np.ndarray,
    previous: np.ndarray,
) -> tuple[np.ndarray, float, float]:
    """Solve one small IK step while strongly retaining the prior branch."""
    work = base_qpos.copy()
    prior = previous.copy()
    max_joint_step = 0.12
    step_lower = np.maximum(lower, prior - max_joint_step)
    step_upper = np.minimum(upper, prior + max_joint_step)

    def residual(arm_qpos: np.ndarray) -> np.ndarray:
        work[arm_addresses] = arm_qpos
        data.qpos[:] = work
        mujoco.mj_kinematics(model, data)
        position_error = (data.xpos[palm_body_id] - target_position) * 40.0
        current_rotation = data.xmat[palm_body_id].reshape(3, 3)
        orientation_error = Rotation.from_matrix(
            target_rotation.T @ current_rotation
        ).as_rotvec() * 2.0
        continuity = (arm_qpos - prior) * 0.20
        return np.concatenate([position_error, orientation_error, continuity])

    result = least_squares(
        residual,
        np.clip(previous, step_lower + 1.0e-8, step_upper - 1.0e-8),
        bounds=(step_lower, step_upper),
        max_nfev=300,
        xtol=1.0e-11,
        ftol=1.0e-11,
        gtol=1.0e-11,
    )
    work[arm_addresses] = result.x
    position, rotation = palm_pose(model, data, work, palm_body_id)
    position_error = float(np.linalg.norm(position - target_position))
    orientation_error = float(
        np.linalg.norm(
            Rotation.from_matrix(target_rotation.T @ rotation).as_rotvec()
        )
    )
    step = float(np.max(np.abs(result.x - previous)))
    if (
        position_error > 0.004
        or orientation_error > math.radians(3.0)
        or step > max_joint_step + 1.0e-7
    ):
        raise RuntimeError(
            "continuous palm IK failed: "
            f"position={position_error:.6f} m, "
            f"orientation={math.degrees(orientation_error):.6f} deg, "
            f"step={step:.6f} rad"
        )
    return result.x.copy(), position_error, orientation_error


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-xml", type=Path, required=True)
    parser.add_argument("--source-trajectory", type=Path, required=True)
    parser.add_argument("--visuals", type=Path, required=True)
    parser.add_argument("--book-trajectory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    model = mujoco.MjModel.from_xml_path(str(args.model_xml))
    data = mujoco.MjData(model)
    source = np.load(args.source_trajectory)
    book = np.load(args.book_trajectory)
    visual_rows = json.loads(args.visuals.read_text())

    q_reference = source["qpos"][-1].copy()
    q_reference[:3] = ROBOT_BASE_XYZ
    yaw = math.radians(ROBOT_BASE_YAW_DEG)
    q_reference[3:7] = np.array(
        [math.cos(0.5 * yaw), 0.0, 0.0, math.sin(0.5 * yaw)]
    )
    arm_joint_ids, arm_addresses = joint_addresses(model, ARM_NAMES)
    _, finger_addresses = joint_addresses(model, FINGER_NAMES)
    lower = model.jnt_range[arm_joint_ids, 0].copy()
    upper = model.jnt_range[arm_joint_ids, 1].copy()
    lower[3] = max(lower[3], 0.05)
    palm_body_id = mujoco.mj_name2id(
        model, mujoco.mjtObj.mjOBJ_BODY, "right_hand_palm_link"
    )
    if palm_body_id < 0:
        raise RuntimeError("right hand palm body missing")

    pusher_positions = book["pusher_positions"]
    palm_targets = pusher_positions + PALM_FROM_CONTACT_WORLD
    times = book["times"]
    start_arm, seed_position_error, seed_orientation_error = solve_palm_pose(
        model,
        data,
        q_reference,
        arm_addresses,
        lower,
        upper,
        palm_body_id,
        palm_targets[0],
        BOOK_PUSH_PALM_ROTATION,
        q_reference[arm_addresses],
        q_reference[arm_addresses],
    )
    target_rotation = BOOK_PUSH_PALM_ROTATION.copy()

    qpos = np.repeat(q_reference[None, :], len(times), axis=0)
    open_fingers = q_reference[finger_addresses].copy()
    fully_closed = np.array([0.85, -0.878, -1.477, 1.163, 1.498, 1.393, 1.5])
    # Tuck the thumb and middle finger behind the pointing index finger so the
    # lateral sweep has one compact, unambiguous contact link.
    compact_fraction = np.array([1.0, 1.0, 1.0, 0.35, 0.35, 1.0, 1.0])
    qpos[:, finger_addresses] = open_fingers + compact_fraction * (
        fully_closed - open_fingers
    )

    seed = start_arm.copy()
    qpos[0, arm_addresses] = seed
    position_errors = [seed_position_error]
    orientation_errors = [seed_orientation_error]
    for index, target in enumerate(palm_targets[1:], 1):
        try:
            seed, position_error, orientation_error = solve_continuous_palm_pose(
                model,
                data,
                q_reference,
                arm_addresses,
                lower,
                upper,
                palm_body_id,
                target,
                target_rotation,
                seed,
            )
        except RuntimeError as exc:
            raise RuntimeError(
                f"frame {index} at t={times[index]:.3f} s: {exc}"
            ) from exc
        qpos[index, arm_addresses] = seed
        position_errors.append(position_error)
        orientation_errors.append(orientation_error)

    geom_ids = []
    for row in visual_rows:
        geom_id = mujoco.mj_name2id(
            model, mujoco.mjtObj.mjOBJ_GEOM, row["geom_name"]
        )
        if geom_id < 0:
            raise RuntimeError(f"visual geometry not found: {row['geom_name']}")
        geom_ids.append(geom_id)
    geom_ids = np.asarray(geom_ids, dtype=int)

    positions = np.empty((len(times), len(geom_ids), 3), dtype=float)
    matrices = np.empty((len(times), len(geom_ids), 3, 3), dtype=float)
    palm_positions = np.empty((len(times), 3), dtype=float)
    palm_matrices = np.empty((len(times), 3, 3), dtype=float)
    for index, row in enumerate(qpos):
        palm_position, palm_matrix = palm_pose(model, data, row, palm_body_id)
        positions[index] = data.geom_xpos[geom_ids]
        matrices[index] = data.geom_xmat[geom_ids].reshape(-1, 3, 3)
        palm_positions[index] = palm_position
        palm_matrices[index] = palm_matrix

    contact_offset_palm = target_rotation.T @ (-PALM_FROM_CONTACT_WORLD)
    hand_contact_positions = palm_positions + np.einsum(
        "nij,j->ni", palm_matrices, contact_offset_palm
    )

    trajectory_path = args.output / "ROBOT_BOOK_VISUAL_TRAJECTORY.npz"
    np.savez_compressed(
        trajectory_path,
        times=times,
        qpos=qpos,
        positions=positions,
        matrices=matrices,
        right_palm_positions=palm_positions,
        right_palm_matrices=palm_matrices,
        book_names=book["book_names"],
        book_positions=book["book_positions"],
        book_matrices=book["book_matrices"],
        pusher_positions=pusher_positions,
        hand_contact_positions=hand_contact_positions,
    )

    palm_target_tracking = np.linalg.norm(palm_positions - palm_targets, axis=1)
    contact_tracking = np.linalg.norm(hand_contact_positions - pusher_positions, axis=1)
    arm_steps = np.abs(np.diff(qpos[:, arm_addresses], axis=0))
    report = {
        "schema": "bedroom_g1_book_push_visual_v1",
        "label": "fixed_base_kinematic_robot_visual_matched_to_dynamic_book_contact_proxy",
        "physics_trajectory": str(args.book_trajectory),
        "physics_trajectory_sha256": sha256(args.book_trajectory),
        "source_robot_model": str(args.model_xml),
        "source_robot_model_sha256": sha256(args.model_xml),
        "source_robot_visuals": str(args.visuals),
        "source_stable_robot_trajectory": str(args.source_trajectory),
        "trajectory": str(trajectory_path),
        "trajectory_sha256": sha256(trajectory_path),
        "frames": len(times),
        "duration_s": float(times[-1]),
        "fps": float(1.0 / np.median(np.diff(times))),
        "robot_base_xyz_m": ROBOT_BASE_XYZ.tolist(),
        "robot_base_yaw_deg": ROBOT_BASE_YAW_DEG,
        "fixed_base": True,
        "whole_body_robot_dynamics_validated": False,
        "book_dynamics_validated_separately": True,
        "right_hand_is_kinematic_proxy_visual": True,
        "palm_from_contact_world_m": PALM_FROM_CONTACT_WORLD.tolist(),
        "contact_point_in_palm_frame_m": contact_offset_palm.tolist(),
        "seed_position_error_m": seed_position_error,
        "seed_orientation_error_deg": math.degrees(seed_orientation_error),
        "max_ik_position_error_m": max(position_errors),
        "max_ik_orientation_error_deg": math.degrees(max(orientation_errors)),
        "max_palm_target_tracking_error_m": float(np.max(palm_target_tracking)),
        "max_hand_contact_proxy_tracking_error_m": float(np.max(contact_tracking)),
        "max_per_frame_arm_joint_step_rad": float(np.max(arm_steps)),
        "target_palm_rotation_matrix": target_rotation.tolist(),
    }
    (args.output / "VISUAL_REPORT.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
