#!/usr/bin/env python3
"""Build a depth/collision-audited G1 mug pick-and-place visual trajectory.

This remains a kinematic visual demonstration.  Compared with the earlier
version it keeps a fixed six-dimensional palm pose while the mug is held,
plans collision-free approach/retreat arm paths, and audits every rendered
frame against the generated bedroom collision model.
"""

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


ARM_NAMES = (
    "right_shoulder_pitch_joint",
    "right_shoulder_roll_joint",
    "right_shoulder_yaw_joint",
    "right_elbow_joint",
    "right_wrist_roll_joint",
    "right_wrist_pitch_joint",
    "right_wrist_yaw_joint",
)
FINGER_NAMES = (
    "right_hand_thumb_0_joint",
    "right_hand_thumb_1_joint",
    "right_hand_thumb_2_joint",
    "right_hand_index_0_joint",
    "right_hand_index_1_joint",
    "right_hand_middle_0_joint",
    "right_hand_middle_1_joint",
)

# This orientation is the well-behaved side grasp from the preceding visual
# baseline, frozen as a full orientation target rather than allowing a
# position-only IK solve to rotate the wrist independently at each keyframe.
PALM_TARGET_ROTATION = np.array(
    [
        [-0.05518352, 0.95431014, 0.29367830],
        [-0.98014952, -0.10786900, 0.16634660],
        [0.19042503, -0.27866905, 0.94131922],
    ],
    dtype=float,
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def smoothstep(value: float) -> float:
    value = float(np.clip(value, 0.0, 1.0))
    return value * value * (3.0 - 2.0 * value)


def joint_addresses(model, names: tuple[str, ...]) -> tuple[np.ndarray, np.ndarray]:
    joint_ids = []
    addresses = []
    for name in names:
        joint_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, name)
        if joint_id < 0:
            raise RuntimeError(f"joint not found: {name}")
        joint_ids.append(joint_id)
        addresses.append(int(model.jnt_qposadr[joint_id]))
    return np.asarray(joint_ids, dtype=int), np.asarray(addresses, dtype=int)


def palm_pose(model, data, qpos: np.ndarray, palm_body_id: int):
    data.qpos[:] = qpos
    mujoco.mj_kinematics(model, data)
    return (
        data.xpos[palm_body_id].copy(),
        data.xmat[palm_body_id].reshape(3, 3).copy(),
    )


def solve_palm_pose(
    model,
    data,
    base_qpos: np.ndarray,
    arm_addresses: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    palm_body_id: int,
    target_position: np.ndarray,
    target_rotation: np.ndarray,
    seed: np.ndarray,
    posture_reference: np.ndarray,
) -> tuple[np.ndarray, float, float]:
    work_qpos = base_qpos.copy()

    def residual(arm_qpos: np.ndarray) -> np.ndarray:
        work_qpos[arm_addresses] = arm_qpos
        data.qpos[:] = work_qpos
        mujoco.mj_kinematics(model, data)
        position_error = (data.xpos[palm_body_id] - target_position) * 40.0
        current_rotation = data.xmat[palm_body_id].reshape(3, 3)
        orientation_error = Rotation.from_matrix(
            target_rotation.T @ current_rotation
        ).as_rotvec() * 2.0
        posture_error = (arm_qpos - posture_reference) * 0.01
        return np.concatenate([position_error, orientation_error, posture_error])

    result = least_squares(
        residual,
        np.clip(seed, lower + 1.0e-8, upper - 1.0e-8),
        bounds=(lower, upper),
        max_nfev=400,
        xtol=1.0e-11,
        ftol=1.0e-11,
        gtol=1.0e-11,
    )
    work_qpos[arm_addresses] = result.x
    position, rotation = palm_pose(model, data, work_qpos, palm_body_id)
    position_error = float(np.linalg.norm(position - target_position))
    orientation_error = float(
        np.linalg.norm(
            Rotation.from_matrix(target_rotation.T @ rotation).as_rotvec()
        )
    )
    if position_error > 0.003 or orientation_error > math.radians(2.5):
        raise RuntimeError(
            "6D palm IK did not converge: "
            f"position={position_error:.6f} m, "
            f"orientation={math.degrees(orientation_error):.6f} deg"
        )
    return result.x.copy(), position_error, orientation_error


def contact_classification(model, data, cup_body_id: int) -> dict[str, list[dict]]:
    rows: dict[str, list[dict]] = {
        "robot_room": [],
        "robot_self": [],
        "robot_cup": [],
    }

    def body_name(body_id: int) -> str:
        return mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, body_id) or "world"

    def is_robot(body_id: int) -> bool:
        return body_id > 0 and not body_name(body_id).startswith("bedroom_")

    for contact in data.contact[: data.ncon]:
        geom1 = int(contact.geom1)
        geom2 = int(contact.geom2)
        body1 = int(model.geom_bodyid[geom1])
        body2 = int(model.geom_bodyid[geom2])
        name1 = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, geom1) or str(geom1)
        name2 = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, geom2) or str(geom2)
        lower_names = (name1 + " " + name2).lower()
        row = {
            "distance_m": float(contact.dist),
            "penetration_m": max(0.0, -float(contact.dist)),
            "geom1": name1,
            "geom2": name2,
        }
        robot1 = is_robot(body1)
        robot2 = is_robot(body2)
        if cup_body_id in (body1, body2) and (robot1 or robot2):
            rows["robot_cup"].append(row)
        elif robot1 and robot2:
            rows["robot_self"].append(row)
        elif robot1 != robot2:
            if "floor" in lower_names or "rug" in lower_names:
                continue
            rows["robot_room"].append(row)
    return rows


def plan_arm_path(
    model,
    data,
    base_qpos: np.ndarray,
    arm_addresses: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    cup_body_id: int,
    cup_position: np.ndarray,
    start: np.ndarray,
    goal: np.ndarray,
    seed: int,
) -> tuple[list[np.ndarray], dict]:
    model.body_pos[cup_body_id] = cup_position
    work_qpos = base_qpos.copy()

    def valid(arm_qpos: np.ndarray) -> bool:
        work_qpos[arm_addresses] = arm_qpos
        data.qpos[:] = work_qpos
        mujoco.mj_kinematics(model, data)
        mujoco.mj_collision(model, data)
        contacts = contact_classification(model, data, cup_body_id)
        return not any(contacts.values())

    def edge_valid(a: np.ndarray, b: np.ndarray, step: float = 0.05) -> bool:
        count = max(2, int(np.ceil(np.max(np.abs(b - a)) / step)) + 1)
        return all(valid((1.0 - u) * a + u * b) for u in np.linspace(0.0, 1.0, count))

    if not valid(start) or not valid(goal):
        raise RuntimeError("arm path endpoint is in collision")
    if edge_valid(start, goal):
        return [start.copy(), goal.copy()], {
            "random_seed": seed,
            "iterations": 0,
            "raw_nodes": 2,
            "shortcut_nodes": 2,
        }

    rng = np.random.default_rng(seed)
    nodes = [start.copy()]
    parents = [-1]
    found = None
    iterations = 0
    scale = np.maximum(upper - lower, 1.0e-6)
    noise = np.array([0.55, 0.55, 0.65, 0.45, 0.65, 0.65, 0.65])
    for iterations in range(1, 7001):
        if rng.random() < 0.22:
            sample = goal
        else:
            alpha = rng.random()
            center = (1.0 - alpha) * start + alpha * goal
            sample = np.clip(center + rng.normal(0.0, noise), lower, upper)
        node_array = np.asarray(nodes)
        distances = np.linalg.norm((node_array - sample) / scale, axis=1)
        nearest = int(np.argmin(distances))
        delta = sample - nodes[nearest]
        divisor = max(1.0, float(np.max(np.abs(delta) / 0.16)))
        candidate = nodes[nearest] + delta / divisor
        if not edge_valid(nodes[nearest], candidate):
            continue
        nodes.append(candidate)
        parents.append(nearest)
        if edge_valid(candidate, goal):
            found = len(nodes) - 1
            break
    if found is None:
        raise RuntimeError("collision-free arm path was not found within the RRT budget")

    path = [goal.copy()]
    index = found
    while index >= 0:
        path.append(nodes[index].copy())
        index = parents[index]
    path.reverse()

    shortcut = [path[0]]
    index = 0
    while index < len(path) - 1:
        candidate = len(path) - 1
        while candidate > index + 1 and not edge_valid(
            path[index], path[candidate], step=0.035
        ):
            candidate -= 1
        shortcut.append(path[candidate])
        index = candidate

    for a, b in zip(shortcut, shortcut[1:]):
        if not edge_valid(a, b, step=0.02):
            raise RuntimeError("shortcut arm path failed dense collision validation")
    return shortcut, {
        "random_seed": seed,
        "iterations": iterations,
        "raw_nodes": len(path),
        "shortcut_nodes": len(shortcut),
    }


def sample_joint_path(path: list[np.ndarray], alpha: float) -> np.ndarray:
    if len(path) == 1:
        return path[0].copy()
    lengths = np.asarray(
        [max(1.0e-8, float(np.max(np.abs(b - a)))) for a, b in zip(path, path[1:])]
    )
    cumulative = np.concatenate([[0.0], np.cumsum(lengths)])
    target = float(np.clip(alpha, 0.0, 1.0)) * cumulative[-1]
    segment = min(int(np.searchsorted(cumulative, target, side="right") - 1), len(path) - 2)
    local = (target - cumulative[segment]) / lengths[segment]
    local = smoothstep(local)
    return (1.0 - local) * path[segment] + local * path[segment + 1]


def task_palm_target(time_s: float, phases: dict[str, float], points: dict[str, np.ndarray]):
    sequence = (
        ("grasp_closed", "lift"),
        ("lift", "carry"),
        ("carry", "place"),
    )
    for start_name, end_name in sequence:
        start = phases[start_name]
        end = phases[end_name]
        if start <= time_s <= end:
            alpha = smoothstep((time_s - start) / (end - start))
            return (1.0 - alpha) * points[start_name] + alpha * points[end_name]
    if time_s < phases["grasp_closed"]:
        return points["grasp_closed"].copy()
    return points["place"].copy()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-xml", type=Path, required=True)
    parser.add_argument("--source-trajectory", type=Path, required=True)
    parser.add_argument("--visuals", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fps", type=int, default=20)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    model = mujoco.MjModel.from_xml_path(str(args.model_xml))
    data = mujoco.MjData(model)
    source = np.load(args.source_trajectory)
    visual_rows = json.loads(args.visuals.read_text())

    q_reference = source["qpos"][-1].copy()
    q_reference[:3] = np.array([1.68, 0.85, 0.762])
    q_reference[3:7] = np.array([math.sqrt(0.5), 0.0, 0.0, -math.sqrt(0.5)])

    arm_joint_ids, arm_addresses = joint_addresses(model, ARM_NAMES)
    _, finger_addresses = joint_addresses(model, FINGER_NAMES)
    palm_body_id = mujoco.mj_name2id(
        model, mujoco.mjtObj.mjOBJ_BODY, "right_hand_palm_link"
    )
    cup_body_id = mujoco.mj_name2id(
        model, mujoco.mjtObj.mjOBJ_BODY, "bedroom_bedside_mug"
    )
    if palm_body_id < 0 or cup_body_id < 0:
        raise RuntimeError("required palm or bedroom mug body is missing")

    lower = model.jnt_range[arm_joint_ids, 0].copy()
    upper = model.jnt_range[arm_joint_ids, 1].copy()
    lower[3] = max(lower[3], 0.10)
    arm_rest = q_reference[arm_addresses].copy()

    cup_start = np.array([1.48, 0.31, 0.9553])
    cup_place = np.array([1.63, 0.31, 0.9553])
    palm_from_cup = np.array([-0.06, 0.18, 0.015])
    grasp_palm = cup_start + palm_from_cup
    place_palm = cup_place + palm_from_cup
    palm_points = {
        "grasp_closed": grasp_palm,
        "lift": grasp_palm + np.array([0.0, 0.0, 0.14]),
        "carry": place_palm + np.array([0.0, 0.0, 0.14]),
        "place": place_palm,
    }

    grasp_arm, grasp_position_error, grasp_orientation_error = solve_palm_pose(
        model,
        data,
        q_reference,
        arm_addresses,
        lower,
        upper,
        palm_body_id,
        grasp_palm,
        PALM_TARGET_ROTATION,
        arm_rest,
        arm_rest,
    )

    open_fingers = q_reference[finger_addresses].copy()
    fully_closed = np.array([0.85, -0.878, -1.477, 1.163, 1.498, 1.393, 1.5])
    # Use a thumb/index pinch around the mug body.  Driving the middle finger
    # toward the mug swept its mesh through the ceramic before reaching the
    # final pose, so it stays open while thumb and index make the visible grip.
    # A shallow opposing pinch is enough for the visual attachment.  These
    # fractions keep both thumb and index in contact while holding collision
    # penetration below one millimetre in the rendered poses.
    closure_fraction = np.array([0.55, 0.55, 0.55, 0.28, 0.28, 0.00, 0.00])
    closed_fingers = open_fingers + closure_fraction * (fully_closed - open_fingers)

    planning_qpos = q_reference.copy()
    planning_qpos[finger_addresses] = open_fingers
    approach_path, approach_plan = plan_arm_path(
        model,
        data,
        planning_qpos,
        arm_addresses,
        lower,
        upper,
        cup_body_id,
        cup_start,
        arm_rest,
        grasp_arm,
        seed=12,
    )

    phases = {
        "rest_start": 0.0,
        "approach_start": 0.6,
        "grasp_open": 3.0,
        "grasp_closed": 3.7,
        "lift": 4.8,
        "carry": 6.0,
        "place": 7.1,
        "release": 7.8,
        # Give the multi-waypoint collision-free retreat enough time to avoid
        # the abrupt wrist snap visible with the earlier 2.2 second retreat.
        "retract_end": 11.0,
        "rest_end": 11.4,
    }
    frame_count = int(round(phases["rest_end"] * args.fps)) + 1
    times = np.arange(frame_count, dtype=float) / args.fps
    qpos = np.repeat(q_reference[None, :], frame_count, axis=0)

    for index, time_s in enumerate(times):
        if time_s <= phases["approach_start"]:
            arm = arm_rest
        elif time_s <= phases["grasp_open"]:
            alpha = (time_s - phases["approach_start"]) / (
                phases["grasp_open"] - phases["approach_start"]
            )
            arm = sample_joint_path(approach_path, alpha)
        else:
            arm = grasp_arm
        qpos[index, arm_addresses] = arm

    dense_ik_errors = []
    seed = grasp_arm.copy()
    for index, time_s in enumerate(times):
        if not phases["grasp_closed"] <= time_s <= phases["place"]:
            continue
        target = task_palm_target(time_s, phases, palm_points)
        try:
            seed, position_error, orientation_error = solve_palm_pose(
                model,
                data,
                q_reference,
                arm_addresses,
                lower,
                upper,
                palm_body_id,
                target,
                PALM_TARGET_ROTATION,
                seed,
                arm_rest,
            )
        except RuntimeError as exc:
            raise RuntimeError(f"dense 6D IK failed at t={time_s:.3f}s: {exc}") from exc
        qpos[index, arm_addresses] = seed
        dense_ik_errors.append((position_error, orientation_error))
    place_arm = qpos[int(round(phases["place"] * args.fps)), arm_addresses].copy()

    retreat_qpos = q_reference.copy()
    retreat_qpos[finger_addresses] = open_fingers
    retreat_path, retreat_plan = plan_arm_path(
        model,
        data,
        retreat_qpos,
        arm_addresses,
        lower,
        upper,
        cup_body_id,
        cup_place,
        place_arm,
        arm_rest,
        seed=23,
    )
    for index, time_s in enumerate(times):
        if phases["place"] < time_s <= phases["release"]:
            qpos[index, arm_addresses] = place_arm
        elif phases["release"] < time_s <= phases["retract_end"]:
            alpha = (time_s - phases["release"]) / (
                phases["retract_end"] - phases["release"]
            )
            qpos[index, arm_addresses] = sample_joint_path(retreat_path, alpha)
        elif time_s > phases["retract_end"]:
            qpos[index, arm_addresses] = arm_rest

    for index, time_s in enumerate(times):
        if time_s <= phases["grasp_open"]:
            fingers = open_fingers
        elif time_s <= phases["grasp_closed"]:
            alpha = smoothstep(
                (time_s - phases["grasp_open"])
                / (phases["grasp_closed"] - phases["grasp_open"])
            )
            fingers = (1.0 - alpha) * open_fingers + alpha * closed_fingers
        elif time_s <= phases["place"]:
            fingers = closed_fingers
        elif time_s <= phases["release"]:
            alpha = smoothstep(
                (time_s - phases["place"])
                / (phases["release"] - phases["place"])
            )
            fingers = (1.0 - alpha) * closed_fingers + alpha * open_fingers
        else:
            fingers = open_fingers
        qpos[index, finger_addresses] = fingers

    geom_ids = []
    for row in visual_rows:
        geom_id = mujoco.mj_name2id(
            model, mujoco.mjtObj.mjOBJ_GEOM, row["geom_name"]
        )
        if geom_id < 0:
            raise RuntimeError(f"visual geometry not found: {row['geom_name']}")
        geom_ids.append(geom_id)
    geom_ids = np.asarray(geom_ids, dtype=int)

    positions = np.empty((frame_count, len(geom_ids), 3), dtype=float)
    matrices = np.empty((frame_count, len(geom_ids), 3, 3), dtype=float)
    palm_positions = np.empty((frame_count, 3), dtype=float)
    palm_matrices = np.empty((frame_count, 3, 3), dtype=float)
    for index, row in enumerate(qpos):
        position, rotation = palm_pose(model, data, row, palm_body_id)
        positions[index] = data.geom_xpos[geom_ids]
        matrices[index] = data.geom_xmat[geom_ids].reshape(-1, 3, 3)
        palm_positions[index] = position
        palm_matrices[index] = rotation

    grasp_index = int(round(phases["grasp_closed"] * args.fps))
    place_index = int(round(phases["place"] * args.fps))
    relative_cup_position = palm_matrices[grasp_index].T @ (
        cup_start - palm_positions[grasp_index]
    )
    relative_cup_rotation = palm_matrices[grasp_index].T
    cup_positions = np.repeat(cup_start[None, :], frame_count, axis=0)
    cup_matrices = np.repeat(np.eye(3)[None, :, :], frame_count, axis=0)
    for index in range(grasp_index, place_index + 1):
        cup_positions[index] = (
            palm_positions[index] + palm_matrices[index] @ relative_cup_position
        )
        cup_matrices[index] = palm_matrices[index] @ relative_cup_rotation
    cup_positions[place_index + 1 :] = cup_place

    collision_frames = {
        "robot_room": [],
        "robot_self_over_tolerance": [],
        "robot_cup_outside_interaction": [],
    }
    max_self_penetration = 0.0
    max_intended_cup_penetration = 0.0
    intended_cup_contact_frames = 0
    self_tolerance = 0.0002
    interaction_start = int(round(phases["grasp_open"] * args.fps))
    interaction_end = int(round(phases["release"] * args.fps))
    for index, row in enumerate(qpos):
        model.body_pos[cup_body_id] = cup_positions[index]
        data.qpos[:] = row
        mujoco.mj_kinematics(model, data)
        mujoco.mj_collision(model, data)
        contacts = contact_classification(model, data, cup_body_id)
        if contacts["robot_room"]:
            collision_frames["robot_room"].append(index)
        if contacts["robot_self"]:
            penetration = max(item["penetration_m"] for item in contacts["robot_self"])
            max_self_penetration = max(max_self_penetration, penetration)
            if penetration > self_tolerance:
                collision_frames["robot_self_over_tolerance"].append(index)
        if contacts["robot_cup"]:
            penetration = max(item["penetration_m"] for item in contacts["robot_cup"])
            if interaction_start <= index <= interaction_end:
                intended_cup_contact_frames += 1
                max_intended_cup_penetration = max(
                    max_intended_cup_penetration, penetration
                )
            else:
                collision_frames["robot_cup_outside_interaction"].append(index)
    collision_passed = not any(collision_frames.values())
    if not collision_passed:
        raise RuntimeError(f"render trajectory collision audit failed: {collision_frames}")

    attachment_position_drift = 0.0
    attachment_rotation_drift = 0.0
    for index in range(grasp_index, place_index + 1):
        local_position = palm_matrices[index].T @ (
            cup_positions[index] - palm_positions[index]
        )
        local_rotation = palm_matrices[index].T @ cup_matrices[index]
        attachment_position_drift = max(
            attachment_position_drift,
            float(np.linalg.norm(local_position - relative_cup_position)),
        )
        attachment_rotation_drift = max(
            attachment_rotation_drift,
            float(
                np.linalg.norm(
                    Rotation.from_matrix(
                        relative_cup_rotation.T @ local_rotation
                    ).as_rotvec()
                )
            ),
        )

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
        right_palm_matrices=palm_matrices,
    )
    collision_report = {
        "schema": "bedroom_g1_cup_pick_place_collision_audit_v1",
        "scope": "kinematic_geometry_per_rendered_frame",
        "frames_checked": frame_count,
        "passed": collision_passed,
        "disallowed_contact_frames": collision_frames,
        "self_collision_tolerance_m": self_tolerance,
        "max_robot_self_penetration_m": max_self_penetration,
        "intended_robot_cup_contact_frames": intended_cup_contact_frames,
        "max_intended_robot_cup_penetration_m": max_intended_cup_penetration,
        "floor_and_rug_contacts_ignored_as_support": True,
        "intended_grasp_contact_is_not_a_physics_success_claim": True,
    }
    collision_path = args.output / "COLLISION_VALIDATION.json"
    collision_path.write_text(json.dumps(collision_report, indent=2) + "\n")

    position_errors = [grasp_position_error, *[row[0] for row in dense_ik_errors]]
    orientation_errors = [
        grasp_orientation_error,
        *[row[1] for row in dense_ik_errors],
    ]
    arm_steps = np.abs(np.diff(qpos[:, arm_addresses], axis=0))
    frame_durations = np.diff(times)
    arm_speeds = arm_steps / frame_durations[:, None]
    report = {
        "schema": "bedroom_g1_cup_pick_place_visual_v3",
        "label": "task_level_kinematic_visual_demo_not_physics_validated",
        "model_xml": str(args.model_xml),
        "model_xml_sha256": sha256(args.model_xml),
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
        "cup_start_xyz_m": cup_start.tolist(),
        "cup_place_xyz_m": cup_place.tolist(),
        "cup_displacement_m": float(np.linalg.norm(cup_place - cup_start)),
        "phase_times_s": phases,
        "palm_pose_control": {
            "type": "dense_6d_position_and_orientation_ik",
            "target_rotation_matrix": PALM_TARGET_ROTATION.tolist(),
            "max_position_error_m": max(position_errors),
            "max_orientation_error_deg": math.degrees(max(orientation_errors)),
        },
        "arm_path_planning": {
            "type": "deterministic_joint_space_rrt_with_dense_edge_checks",
            "approach": approach_plan,
            "retreat": retreat_plan,
            "approach_waypoints": [row.tolist() for row in approach_path],
            "retreat_waypoints": [row.tolist() for row in retreat_path],
        },
        "arm_motion": {
            "max_per_frame_joint_step_rad": float(np.max(arm_steps)),
            "max_joint_speed_rad_s": float(np.max(arm_speeds)),
        },
        "finger_closure_fraction": closure_fraction.tolist(),
        "cup_attachment": {
            "attach_at_phase": "grasp_closed",
            "detach_at_phase": "place",
            "rigid_palm_relative_transform": True,
            "max_position_drift_m": attachment_position_drift,
            "max_rotation_drift_deg": math.degrees(attachment_rotation_drift),
        },
        "collision_validation": collision_report,
        "collision_validation_path": str(collision_path),
        "physical_simulation_executed": False,
        "collision_validation_executed": True,
        "collision_validation_kind": "kinematic_geometry_only",
        "production_accepted": False,
    }
    (args.output / "REPORT.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
