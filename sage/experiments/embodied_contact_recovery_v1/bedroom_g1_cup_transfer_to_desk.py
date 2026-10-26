#!/usr/bin/env python3
"""Carry the friction-held bedroom mug to the adjacent writing desk.

The rollout deliberately reuses the validated v30 lift state instead of
pretending that a new grasp has been solved.  The robot base is welded only
while that state is allowed to settle; the weld is then disabled before the
turn, walk, desk approach, placement, release, and retract.  The mug remains a
free dynamic body throughout and is never attached to the hand.

The saved render trajectory prepends the already validated v30 pickup segment
to the newly simulated continuation.  A second NPZ stores only the new
physics continuation so provenance and acceptance metrics remain explicit.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import shutil

import mujoco
import numpy as np
from scipy.spatial.transform import Rotation

from .bedroom_generated_walk import (
    SOURCE,
    base_yaw,
    install_controller_adapter,
    sha256,
    visual_manifest,
    wrap_angle,
    write_json,
)
from .bedroom_g1_cup_pick_place_physics_v1 import (
    MUG_BODY,
    MUG_FREEJOINT,
    MUG_PROXY_GEOM,
    PALM_BODY,
    SOURCE_VISUAL_TRAJECTORY,
    actuator_ids,
    contact_sample,
    interpolate,
    joint_addresses,
)
from .bedroom_g1_cup_pick_place_v3 import (
    ARM_NAMES,
    FINGER_NAMES,
    contact_classification,
    smoothstep,
    solve_palm_pose,
)


ROOT = Path("/data/wsj/main")
SOURCE_RUN = (
    ROOT
    / "scene_runs/codex_trellis_v2"
    / "bedroom_g1_cup_pick_place_physics_20261013_v30"
)
SOURCE_MODEL = SOURCE_RUN / "MODEL.xml"
SOURCE_TRAJECTORY = SOURCE_RUN / "ROBOT_CUP_PHYSICS_TRAJECTORY.npz"
SOURCE_REPORT = SOURCE_RUN / "REPORT.json"
SOURCE_DYNAMIC_BINDING = SOURCE_RUN / "DYNAMIC_MUG_BINDING.json"
DEFAULT_OUTPUT = (
    ROOT
    / "scene_runs/codex_trellis_v2"
    / "bedroom_g1_cup_transfer_to_desk_physics_20261013_v1"
)

BASE_WELD = "robot_base_stabilization_weld"
DESK_GEOM = "bedroom_static_geom_explicit_desk"
START_TIME_S = 5.80
DESK_CUP_X_M = 0.75
DESK_TOP_Z_M = 0.75


def yaw_quaternion(yaw: float) -> np.ndarray:
    return np.array([math.cos(yaw / 2.0), 0.0, 0.0, math.sin(yaw / 2.0)])


def upright_component(qpos: np.ndarray) -> float:
    return float(1.0 - 2.0 * (qpos[4] ** 2 + qpos[5] ** 2))


def desk_contact(sample: dict) -> bool:
    return any(row["geom"] == DESK_GEOM for row in sample["support"])


def named_nonfloor_robot_room_contacts(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    cup_body_id: int,
) -> list[dict]:
    return contact_classification(model, data, cup_body_id)["robot_room"]


def solve_arm(
    model: mujoco.MjModel,
    ik_data: mujoco.MjData,
    qpos: np.ndarray,
    arm_addresses: np.ndarray,
    arm_lower: np.ndarray,
    arm_upper: np.ndarray,
    palm_body_id: int,
    target_position: np.ndarray,
    target_matrix: np.ndarray,
    seed: np.ndarray,
    posture_reference: np.ndarray,
) -> tuple[np.ndarray, float, float]:
    return solve_palm_pose(
        model,
        ik_data,
        qpos,
        arm_addresses,
        arm_lower,
        arm_upper,
        palm_body_id,
        target_position,
        target_matrix,
        seed,
        posture_reference,
    )


def run_preflight(
    model: mujoco.MjModel,
    source: np.lib.npyio.NpzFile,
    start_index: int,
    arm_addresses: np.ndarray,
    arm_lower: np.ndarray,
    arm_upper: np.ndarray,
    palm_body_id: int,
    cup_body_id: int,
    mug_qpos_address: int,
    route: str,
) -> dict:
    """Zero-integration endpoint and arm-edge audit for the desk placement."""

    start_qpos = source["qpos"][start_index].copy()
    start_arm = start_qpos[arm_addresses].copy()
    start_yaw = base_yaw(start_qpos)
    if route == "north":
        target_base_xy = np.array([0.98, 2.35], dtype=float)
        target_yaw = start_yaw
        target_cup = np.array([0.88, 1.85, DESK_TOP_Z_M + 0.0585])
        base_route = [
            start_qpos[:2].copy(),
            np.array([1.90, 0.78]),
            np.array([1.90, 2.35]),
            target_base_xy,
        ]
    else:
        target_base_xy = np.array([1.20, 0.82], dtype=float)
        target_yaw = -math.pi
        target_cup = np.array([DESK_CUP_X_M, 1.05, DESK_TOP_Z_M + 0.0585])
        base_route = [start_qpos[:2].copy(), target_base_xy]
    yaw_rotation = Rotation.from_euler("z", target_yaw - start_yaw).as_matrix()
    cup_from_palm = yaw_rotation @ (
        source["cup_positions"][start_index]
        - source["right_palm_positions"][start_index]
    )
    target_palm = target_cup - cup_from_palm
    target_matrix = yaw_rotation @ source["right_palm_matrices"][start_index]
    approach_height = 0.08 if route == "north" else 0.12

    qpos = start_qpos.copy()
    qpos[:3] = [target_base_xy[0], target_base_xy[1], 0.7594]
    qpos[3:7] = yaw_quaternion(target_yaw)
    qpos[mug_qpos_address : mug_qpos_address + 3] = target_cup
    qpos[mug_qpos_address + 3 : mug_qpos_address + 7] = [1.0, 0.0, 0.0, 0.0]

    ik_data = mujoco.MjData(model)
    solution, position_error, orientation_error = solve_arm(
        model,
        ik_data,
        qpos,
        arm_addresses,
        arm_lower,
        arm_upper,
        palm_body_id,
        target_palm,
        target_matrix,
        start_arm,
        start_arm,
    )
    approach_solution, approach_position_error, approach_orientation_error = solve_arm(
        model,
        ik_data,
        qpos,
        arm_addresses,
        arm_lower,
        arm_upper,
        palm_body_id,
        target_palm + np.array([0.0, 0.0, approach_height]),
        target_matrix,
        start_arm,
        start_arm,
    )

    audit_data = mujoco.MjData(model)
    collision_rows = []
    arm_edges = (
        (start_arm, approach_solution),
        (approach_solution, solution),
    )
    edge_index = 0
    for segment_index, (edge_start, edge_end) in enumerate(arm_edges):
        for alpha in np.linspace(0.0, 1.0, 61):
            work = qpos.copy()
            work[arm_addresses] = (
                (1.0 - alpha) * edge_start + alpha * edge_end
            )
            # During the edge audit the free mug follows its measured in-hand
            # offset.  This is kinematics only; no body pose is rewritten in
            # the dynamic rollout.
            audit_data.qpos[:] = work
            mujoco.mj_kinematics(model, audit_data)
            work[mug_qpos_address : mug_qpos_address + 3] = (
                audit_data.xpos[palm_body_id] + cup_from_palm
            )
            audit_data.qpos[:] = work
            mujoco.mj_forward(model, audit_data)
            mujoco.mj_collision(model, audit_data)
            contacts = contact_classification(model, audit_data, cup_body_id)
            if contacts["robot_room"] or contacts["robot_self"]:
                collision_rows.append(
                    {
                        "edge_index": edge_index,
                        "segment_index": segment_index,
                        "alpha": float(alpha),
                        "robot_room": contacts["robot_room"],
                        "robot_self": contacts["robot_self"],
                    }
                )
            edge_index += 1

    base_route_collision_rows = []
    route_sample_index = 0
    cup_from_base = (
        source["cup_positions"][start_index] - start_qpos[:3]
    )
    for segment_index, (segment_start, segment_end) in enumerate(
        zip(base_route[:-1], base_route[1:])
    ):
        sample_count = max(
            2,
            int(np.ceil(np.linalg.norm(segment_end - segment_start) / 0.025)) + 1,
        )
        for alpha in np.linspace(0.0, 1.0, sample_count):
            route_qpos = start_qpos.copy()
            route_qpos[:2] = (
                (1.0 - alpha) * segment_start + alpha * segment_end
            )
            route_qpos[mug_qpos_address : mug_qpos_address + 3] = (
                route_qpos[:3] + cup_from_base
            )
            audit_data.qpos[:] = route_qpos
            mujoco.mj_forward(model, audit_data)
            mujoco.mj_collision(model, audit_data)
            contacts = contact_classification(model, audit_data, cup_body_id)
            if contacts["robot_room"] or contacts["robot_self"]:
                base_route_collision_rows.append(
                    {
                        "sample_index": route_sample_index,
                        "segment_index": segment_index,
                        "alpha": float(alpha),
                        "base_xy_m": route_qpos[:2].tolist(),
                        "robot_room": contacts["robot_room"],
                        "robot_self": contacts["robot_self"],
                    }
                )
            route_sample_index += 1

    return {
        "schema": "bedroom_g1_cup_cross_desk_preflight_v1",
        "integration_steps": 0,
        "route": route,
        "base_route_xy_m": [point.tolist() for point in base_route],
        "target_base_xy_m": target_base_xy.tolist(),
        "target_base_yaw_deg": math.degrees(target_yaw),
        "target_cup_center_xyz_m": target_cup.tolist(),
        "target_palm_xyz_m": target_palm.tolist(),
        "ik_position_error_m": position_error,
        "ik_orientation_error_deg": math.degrees(orientation_error),
        "goal_arm_rad": solution.tolist(),
        "approach_height_m": approach_height,
        "approach_arm_rad": approach_solution.tolist(),
        "approach_ik_position_error_m": approach_position_error,
        "approach_ik_orientation_error_deg": math.degrees(
            approach_orientation_error
        ),
        "maximum_goal_joint_delta_rad": float(
            np.max(np.abs(solution - start_arm))
        ),
        "arm_edge_samples": edge_index,
        "arm_edge_collision_rows": collision_rows,
        "base_route_samples": route_sample_index,
        "base_route_collision_rows": base_route_collision_rows,
        "pass": bool(
            position_error <= 0.003
            and orientation_error <= math.radians(2.5)
            and approach_position_error <= 0.003
            and approach_orientation_error <= math.radians(2.5)
            and not collision_rows
            and not base_route_collision_rows
        ),
        "known_corridor_constraints": {
            "base_x_at_or_above_1_30_m": "desk pose failed 6D IK scan",
            "base_y_near_1_00_m": "lower-body collision with office chair",
        },
    }


def combine_with_source_pickup(
    output: Path,
    source: np.lib.npyio.NpzFile,
    start_index: int,
    continuation_path: Path,
) -> Path:
    continuation = np.load(continuation_path)
    source_slice = slice(0, start_index + 1)
    combined = {}
    array_names = (
        "qpos",
        "positions",
        "matrices",
        "cup_positions",
        "cup_matrices",
        "right_palm_positions",
        "right_palm_matrices",
    )
    for name in array_names:
        combined[name] = np.concatenate(
            [source[name][source_slice], continuation[name]], axis=0
        )
    source_times = source["times"][source_slice] - float(source["times"][0])
    continuation_times = continuation["times"] + float(source_times[-1])
    combined["times"] = np.concatenate([source_times, continuation_times])
    path = output / "ROBOT_CUP_PHYSICS_TRAJECTORY.npz"
    np.savez_compressed(path, **combined)
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", nargs="?", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--duration", type=float, default=42.0)
    parser.add_argument("--navigation-speed", type=float, default=0.28)
    parser.add_argument("--rotation-speed", type=float, default=0.35)
    parser.add_argument("--route", choices=("rotator", "north"), default="rotator")
    parser.add_argument("--target-base-x", type=float, default=1.20)
    parser.add_argument("--target-base-y", type=float, default=0.82)
    args = parser.parse_args()

    if args.output.exists():
        raise RuntimeError(f"output already exists: {args.output}")
    args.output.mkdir(parents=True)
    shutil.copy2(SOURCE_MODEL, args.output / "MODEL.xml")
    shutil.copy2(SOURCE_DYNAMIC_BINDING, args.output / "DYNAMIC_MUG_BINDING.json")
    model_xml = args.output / "MODEL.xml"

    run_module, adapter = install_controller_adapter(args.output, model_xml)
    write_json(args.output / "ADAPTER_SUMMARY.json", adapter)
    model = mujoco.MjModel.from_xml_path(str(model_xml))
    model.opt.timestep = 0.0025
    mujoco.mj_saveModel(model, str(args.output / "MODEL.mjb"))
    data = mujoco.MjData(model)
    source = np.load(SOURCE_TRAJECTORY)
    start_index = int(np.argmin(np.abs(source["times"] - START_TIME_S)))
    data.qpos[:] = source["qpos"][start_index]
    data.qvel[:] = 0.0
    data.ctrl[:] = 0.0
    mujoco.mj_forward(model, data)

    arm_addresses = joint_addresses(model, ARM_NAMES)
    arm_dof_addresses = np.asarray(
        [model.jnt_dofadr[model.joint(name).id] for name in ARM_NAMES], dtype=int
    )
    arm_joint_ids = np.asarray([model.joint(name).id for name in ARM_NAMES])
    arm_lower = model.jnt_range[arm_joint_ids, 0].copy()
    arm_upper = model.jnt_range[arm_joint_ids, 1].copy()
    arm_lower[3] = max(arm_lower[3], 0.10)
    arm_actuator_ids = actuator_ids(model, ARM_NAMES)
    finger_addresses = joint_addresses(model, FINGER_NAMES)
    finger_actuator_ids = actuator_ids(model, FINGER_NAMES)
    palm_body_id = model.body(PALM_BODY).id
    cup_body_id = model.body(MUG_BODY).id
    mug_geom_id = model.geom(MUG_PROXY_GEOM).id
    mug_joint_id = model.joint(MUG_FREEJOINT).id
    mug_qpos_address = int(model.jnt_qposadr[mug_joint_id])
    mug_dof_address = int(model.jnt_dofadr[mug_joint_id])
    weld_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_EQUALITY, BASE_WELD)
    if weld_id < 0:
        raise RuntimeError(f"required source base weld missing: {BASE_WELD}")

    preflight = run_preflight(
        model,
        source,
        start_index,
        arm_addresses,
        arm_lower,
        arm_upper,
        palm_body_id,
        cup_body_id,
        mug_qpos_address,
        args.route,
    )
    write_json(args.output / "PREFLIGHT.json", preflight)
    if not preflight["pass"]:
        raise RuntimeError("zero-integration desk placement preflight failed")

    config = json.loads((SOURCE / "model_config.json").read_text())
    policies = [
        run_module.ONNXPolicy(str(SOURCE / f"{name}.onnx"))
        for name in ("walker", "croucher", "rotator")
    ]
    controller = run_module.G1Controller(model, data, *policies, config)
    normal_walker = controller.walker_policy

    visual_ids, visual_rows = visual_manifest(model)
    visual_ids = np.asarray(visual_ids, dtype=int)
    write_json(args.output / "ROBOT_VISUALS.json", visual_rows)

    start_arm = data.qpos[arm_addresses].copy()
    start_base_yaw = base_yaw(data.qpos)
    source_visual = np.load(SOURCE_VISUAL_TRAJECTORY)
    carry_ik_data = mujoco.MjData(model)
    carry_ik_arm, _, _ = solve_arm(
        model,
        carry_ik_data,
        data.qpos.copy(),
        arm_addresses,
        arm_lower,
        arm_upper,
        palm_body_id,
        source_visual["right_palm_positions"][96],
        source_visual["right_palm_matrices"][96],
        start_arm,
        start_arm,
    )
    # Reconstruct the v30 hold controller's 0.5 outer tracking term.  Freezing
    # the measured qpos itself removes its gravity-balancing offset and lets
    # the loaded arm sag as soon as a saved frame is restarted.
    carry_arm = np.clip(
        carry_ik_arm + 0.5 * (carry_ik_arm - start_arm),
        arm_lower,
        arm_upper,
    )
    arm_command = carry_arm.copy()
    controller.frozen_arm_pos = carry_arm.astype(np.float32)
    source_open_index = int(np.argmin(np.abs(source["times"] - 1.0)))
    open_fingers = source["qpos"][source_open_index, finger_addresses].copy()
    fully_closed = np.array(
        [0.80, -0.90, -1.50, 1.40, 1.50, 1.40, 1.50], dtype=float
    )
    closure_fraction = np.array([0.55, 0.55, 0.55, 0.28, 0.28, 0.35, 0.35])
    closed_fingers = open_fingers + 1.10 * closure_fraction * (
        fully_closed - open_fingers
    )
    finger_limits = np.asarray(
        [model.jnt_range[model.joint(name).id] for name in FINGER_NAMES]
    )
    closed_fingers = np.clip(
        closed_fingers, finger_limits[:, 0], finger_limits[:, 1]
    )

    arm_pd_kp = np.array([80.0, 80.0, 60.0, 60.0, 30.0, 30.0, 20.0])
    arm_pd_kd = np.array([4.0, 4.0, 3.0, 3.0, 2.0, 2.0, 1.5])
    reach_duration = 5.0 if args.route == "north" else 3.5
    lower_duration = 3.0 if args.route == "north" else 3.5
    approach_height = 0.08 if args.route == "north" else 0.12
    phase = "fixed_settle"
    phase_start = float(data.time)
    phase_events = [{"phase": phase, "time_s": phase_start}]
    base_release_time = None
    rotation_start_yaw = None
    navigation_start_xy = None
    target_cup_position = None
    target_palm_position = None
    approach_arm = None
    place_arm = None
    retract_arm = None
    phase_arm_start = start_arm.copy()
    support_stop_arm = None
    placement_plan = None
    failure_reason = None
    support_run_steps = 0
    yaw_good_steps = 0
    navigation_good_steps = 0
    north_route = [
        ("navigate_east", np.array([1.90, 0.78]), 6.0),
        ("navigate_north", np.array([1.90, 2.35]), 12.0),
        (
            "navigate_west",
            np.array([args.target_base_x, args.target_base_y]),
            10.0,
        ),
    ]
    north_route_index = 0
    no_hand_contact_steps = 0
    post_release_hand_contact_steps = 0
    robot_room_contact_pairs: set[tuple[str, str]] = set()
    robot_room_max_penetration = 0.0

    dt = float(model.opt.timestep)
    policy_every = 8
    video_every = 20
    ik_data = mujoco.MjData(model)
    target = controller.default_joint_pos.copy()

    qpos_states = []
    visual_positions = []
    visual_matrices = []
    mug_positions = []
    mug_matrices = []
    palm_positions = []
    palm_matrices = []
    times = []
    timeline = []
    hand_contact_flags = []
    desk_contact_flags = []
    carry_relative_positions = []
    carry_times = []
    max_mug_penetration = 0.0
    max_base_tilt_deg = 0.0
    max_base_angular_speed = 0.0
    min_base_height = float(data.qpos[2])
    fell = False
    fall_steps = 0
    release_completed_time = None

    def change_phase(name: str) -> None:
        nonlocal phase, phase_start, phase_arm_start
        phase = name
        phase_start = float(data.time)
        phase_arm_start = data.qpos[arm_addresses].copy()
        phase_events.append({"phase": name, "time_s": phase_start})

    def plan_placement() -> None:
        nonlocal target_cup_position, target_palm_position
        nonlocal approach_arm, place_arm, placement_plan
        if args.route == "north":
            target_cup_position = np.array(
                [0.88, 1.85, DESK_TOP_Z_M + 0.0585], dtype=float
            )
        else:
            target_y = float(np.clip(data.qpos[1] + 0.20, 1.05, 1.25))
            target_cup_position = np.array(
                [DESK_CUP_X_M, target_y, DESK_TOP_Z_M + 0.0585], dtype=float
            )
        cup_from_palm = data.xpos[cup_body_id] - data.xpos[palm_body_id]
        target_palm_position = target_cup_position - cup_from_palm
        target_palm_matrix = data.xmat[palm_body_id].reshape(3, 3).copy()
        approach_palm_position = target_palm_position + np.array(
            [0.0, 0.0, approach_height]
        )
        seed = data.qpos[arm_addresses].copy()
        approach_arm, approach_position_error, approach_orientation_error = solve_arm(
            model,
            ik_data,
            data.qpos.copy(),
            arm_addresses,
            arm_lower,
            arm_upper,
            palm_body_id,
            approach_palm_position,
            target_palm_matrix,
            seed,
            seed,
        )
        place_arm, place_position_error, place_orientation_error = solve_arm(
            model,
            ik_data,
            data.qpos.copy(),
            arm_addresses,
            arm_lower,
            arm_upper,
            palm_body_id,
            target_palm_position,
            target_palm_matrix,
            approach_arm,
            approach_arm,
        )
        placement_plan = {
            "base_xy_m": data.qpos[:2].tolist(),
            "base_yaw_deg": math.degrees(base_yaw(data.qpos)),
            "target_cup_center_xyz_m": target_cup_position.tolist(),
            "cup_from_palm_at_plan_m": cup_from_palm.tolist(),
            "approach_palm_xyz_m": approach_palm_position.tolist(),
            "target_palm_xyz_m": target_palm_position.tolist(),
            "approach_arm_rad": approach_arm.tolist(),
            "place_arm_rad": place_arm.tolist(),
            "approach_ik_position_error_m": approach_position_error,
            "approach_ik_orientation_error_deg": math.degrees(
                approach_orientation_error
            ),
            "place_ik_position_error_m": place_position_error,
            "place_ik_orientation_error_deg": math.degrees(
                place_orientation_error
            ),
        }

    total_steps = int(round(args.duration / dt))
    for step in range(total_steps):
        now = float(data.time)
        elapsed = now - phase_start

        if phase == "fixed_settle" and elapsed >= 1.0:
            data.eq_active[weld_id] = 0
            base_release_time = now
            change_phase("free_settle")
        elif phase == "free_settle" and elapsed >= 1.5:
            if args.route == "north":
                navigation_start_xy = data.qpos[:2].copy()
                navigation_good_steps = 0
                north_route_index = 0
                change_phase(north_route[north_route_index][0])
            else:
                controller.walker_policy = controller.rotator_policy
                rotation_start_yaw = base_yaw(data.qpos)
                change_phase("rotate")
        elif phase == "rotate":
            yaw_error = wrap_angle(-math.pi - base_yaw(data.qpos))
            yaw_good_steps = yaw_good_steps + 1 if abs(yaw_error) <= math.radians(7) else 0
            if yaw_good_steps >= int(round(0.30 / dt)):
                controller.walker_policy = normal_walker
                controller.ang_vel_z = 0.0
                change_phase("post_rotate_settle")
            elif elapsed >= 7.0:
                failure_reason = "rotation_timeout"
        elif phase == "post_rotate_settle" and elapsed >= 1.5:
            navigation_start_xy = data.qpos[:2].copy()
            change_phase("navigate")
        elif phase.startswith("navigate_") and args.route == "north":
            _, waypoint, timeout = north_route[north_route_index]
            navigation_error = waypoint - data.qpos[:2]
            navigation_good_steps = (
                navigation_good_steps + 1
                if np.linalg.norm(navigation_error) <= 0.055
                else 0
            )
            if navigation_good_steps >= int(round(0.30 / dt)):
                controller.lin_vel_x = 0.0
                controller.lin_vel_y = 0.0
                controller.ang_vel_z = 0.0
                if north_route_index + 1 < len(north_route):
                    north_route_index += 1
                    navigation_good_steps = 0
                    change_phase(north_route[north_route_index][0])
                else:
                    change_phase("navigation_settle")
            elif elapsed >= timeout:
                failure_reason = f"{phase}_timeout"
        elif phase == "navigate":
            navigation_error = np.array(
                [args.target_base_x, args.target_base_y]
            ) - data.qpos[:2]
            navigation_good_steps = (
                navigation_good_steps + 1
                if np.linalg.norm(navigation_error) <= 0.045
                else 0
            )
            if navigation_good_steps >= int(round(0.35 / dt)):
                controller.lin_vel_x = 0.0
                controller.lin_vel_y = 0.0
                controller.ang_vel_z = 0.0
                change_phase("navigation_settle")
            elif elapsed >= 10.0:
                failure_reason = "navigation_timeout"
        elif phase == "navigation_settle" and elapsed >= 1.5:
            try:
                plan_placement()
            except RuntimeError as error:
                failure_reason = f"runtime_placement_ik_failed: {error}"
            if failure_reason is None:
                change_phase("reach_approach")
        elif phase == "reach_approach" and elapsed >= reach_duration:
            change_phase("approach_hold")
        elif phase == "approach_hold" and elapsed >= 0.8:
            change_phase("lower")
        elif phase == "lower":
            if support_run_steps >= int(round(0.12 / dt)):
                support_stop_arm = data.qpos[arm_addresses].copy()
                change_phase("settle_place")
            elif elapsed >= lower_duration:
                failure_reason = "desk_support_not_reached"
        elif phase == "settle_place" and elapsed >= 0.7:
            change_phase("release")
        elif phase == "release" and elapsed >= 1.2:
            release_completed_time = now
            change_phase("post_release_dwell")
        elif phase == "post_release_dwell" and elapsed >= 0.7:
            current_palm = data.xpos[palm_body_id].copy()
            current_matrix = data.xmat[palm_body_id].reshape(3, 3).copy()
            retract_target = current_palm + np.array([0.10, -0.04, 0.04])
            try:
                retract_arm, _, _ = solve_arm(
                    model,
                    ik_data,
                    data.qpos.copy(),
                    arm_addresses,
                    arm_lower,
                    arm_upper,
                    palm_body_id,
                    retract_target,
                    current_matrix,
                    data.qpos[arm_addresses].copy(),
                    data.qpos[arm_addresses].copy(),
                )
            except RuntimeError as error:
                failure_reason = f"retract_ik_failed: {error}"
            if failure_reason is None:
                change_phase("retract")
        elif phase == "retract" and elapsed >= 3.0:
            change_phase("final_hold")
        elif phase == "final_hold" and elapsed >= 1.5:
            change_phase("complete")

        if failure_reason is not None:
            break
        if phase == "complete":
            break

        if phase == "release":
            finger_target = interpolate(
                closed_fingers, open_fingers, elapsed / 1.2
            )
        elif phase in {"post_release_dwell", "retract", "final_hold"}:
            finger_target = open_fingers
        else:
            finger_target = closed_fingers

        if phase == "reach_approach":
            arm_target = interpolate(
                phase_arm_start, approach_arm, elapsed / reach_duration
            )
        elif phase == "approach_hold":
            arm_target = approach_arm
        elif phase == "lower":
            arm_target = interpolate(
                phase_arm_start, place_arm, elapsed / lower_duration
            )
        elif phase in {"settle_place", "release", "post_release_dwell"}:
            arm_target = support_stop_arm if support_stop_arm is not None else place_arm
        elif phase == "retract":
            arm_target = interpolate(phase_arm_start, retract_arm, elapsed / 3.0)
        elif phase == "final_hold":
            arm_target = retract_arm
        else:
            arm_target = carry_arm

        if step % policy_every == 0:
            if phase == "rotate":
                yaw_error = wrap_angle(-math.pi - base_yaw(data.qpos))
                controller.lin_vel_x = 0.0
                controller.lin_vel_y = 0.0
                controller.ang_vel_z = float(
                    np.clip(1.0 * yaw_error, -args.rotation_speed, args.rotation_speed)
                )
            elif phase == "navigate" or (
                args.route == "north" and phase.startswith("navigate_")
            ):
                if args.route == "north":
                    world_error = north_route[north_route_index][1] - data.qpos[:2]
                else:
                    world_error = np.array(
                        [args.target_base_x, args.target_base_y]
                    ) - data.qpos[:2]
                yaw = base_yaw(data.qpos)
                rotation = Rotation.from_euler("z", yaw).as_matrix()[:2, :2]
                body_error = rotation.T @ world_error
                command_ramp = smoothstep(elapsed / 0.8)
                controller.lin_vel_x = float(
                    command_ramp
                    * np.clip(
                        1.2 * body_error[0],
                        -args.navigation_speed,
                        args.navigation_speed,
                    )
                )
                controller.lin_vel_y = float(
                    command_ramp
                    * np.clip(
                        1.2 * body_error[1],
                        -args.navigation_speed,
                        args.navigation_speed,
                    )
                )
                controller.ang_vel_z = float(
                    np.clip(
                        0.8 * wrap_angle(start_base_yaw - yaw), -0.12, 0.12
                    )
                    if args.route == "north"
                    else np.clip(0.8 * wrap_angle(-math.pi - yaw), -0.12, 0.12)
                )
            else:
                controller.lin_vel_x = 0.0
                controller.lin_vel_y = 0.0
                controller.ang_vel_z = 0.0
            target = controller.step()
            arm_command = np.clip(arm_target, arm_lower, arm_upper)
            target[controller.right_arm_indices] = arm_command.astype(np.float32)
            controller.frozen_arm_pos = arm_command.astype(np.float32)

        controller.apply_pd_control(target)
        arm_position = data.qpos[arm_addresses]
        arm_velocity = data.qvel[arm_dof_addresses]
        arm_torque = (
            arm_pd_kp * (arm_command - arm_position)
            - arm_pd_kd * arm_velocity
            + data.qfrc_bias[arm_dof_addresses]
        )
        arm_torque = np.clip(
            arm_torque,
            model.actuator_ctrlrange[arm_actuator_ids, 0],
            model.actuator_ctrlrange[arm_actuator_ids, 1],
        )
        data.ctrl[arm_actuator_ids] = arm_torque
        data.ctrl[finger_actuator_ids] = finger_target
        mujoco.mj_step(model, data)

        sample = contact_sample(model, data, mug_geom_id)
        if phase == "lower":
            support_run_steps = support_run_steps + 1 if desk_contact(sample) else 0
        max_mug_penetration = max(
            max_mug_penetration, sample["max_mug_contact_penetration_m"]
        )
        if phase in {
            "free_settle",
            "rotate",
            "post_rotate_settle",
            "navigate",
            "navigate_east",
            "navigate_north",
            "navigate_west",
            "navigation_settle",
            "reach_approach",
            "approach_hold",
            "lower",
        }:
            carry_times.append(float(data.time))
            relative = data.xmat[palm_body_id].reshape(3, 3).T @ (
                data.xpos[cup_body_id] - data.xpos[palm_body_id]
            )
            carry_relative_positions.append(relative)
            no_hand_contact_steps = 0 if sample["hand"] else no_hand_contact_steps + 1
            if no_hand_contact_steps >= int(round(0.35 / dt)):
                failure_reason = "friction_grasp_lost_during_carry"
        if release_completed_time is not None and sample["hand"]:
            post_release_hand_contact_steps += 1

        for row in named_nonfloor_robot_room_contacts(model, data, cup_body_id):
            pair = tuple(sorted((row["geom1"], row["geom2"])))
            robot_room_contact_pairs.add(pair)
            robot_room_max_penetration = max(
                robot_room_max_penetration, float(row["penetration_m"])
            )

        upright = upright_component(data.qpos)
        tilt_deg = math.degrees(math.acos(float(np.clip(upright, -1.0, 1.0))))
        max_base_tilt_deg = max(max_base_tilt_deg, tilt_deg)
        max_base_angular_speed = max(
            max_base_angular_speed, float(np.linalg.norm(data.qvel[3:6]))
        )
        min_base_height = min(min_base_height, float(data.qpos[2]))
        fall_steps = fall_steps + 1 if data.qpos[2] < 0.50 or upright < 0.5 else 0
        if fall_steps >= 80:
            fell = True
            failure_reason = "robot_fell"

        if step % video_every == 0:
            qpos_states.append(data.qpos.copy())
            visual_positions.append(data.geom_xpos[visual_ids].copy())
            visual_matrices.append(
                data.geom_xmat[visual_ids].reshape(-1, 3, 3).copy()
            )
            mug_positions.append(data.xpos[cup_body_id].copy())
            mug_matrices.append(data.xmat[cup_body_id].reshape(3, 3).copy())
            palm_positions.append(data.xpos[palm_body_id].copy())
            palm_matrices.append(data.xmat[palm_body_id].reshape(3, 3).copy())
            times.append(float(data.time))
            hand_contact_flags.append(bool(sample["hand"]))
            desk_contact_flags.append(desk_contact(sample))
            timeline.append(
                {
                    "time_s": float(data.time),
                    "phase": phase,
                    "base_xyz_m": data.qpos[:3].tolist(),
                    "base_yaw_deg": math.degrees(base_yaw(data.qpos)),
                    "base_tilt_deg": tilt_deg,
                    "cup_xyz_m": data.xpos[cup_body_id].tolist(),
                    "cup_hand_contact": bool(sample["hand"]),
                    "cup_desk_contact": desk_contact(sample),
                    "hand_contact_bodies": sorted(
                        {row["body"] for row in sample["hand"]}
                    ),
                    "support_contact_geoms": sorted(
                        {row["geom"] for row in sample["support"]}
                    ),
                }
            )
        if failure_reason is not None:
            break

    arrays = {
        "qpos": np.asarray(qpos_states),
        "positions": np.asarray(visual_positions),
        "matrices": np.asarray(visual_matrices),
        "times": np.asarray(times),
        "cup_positions": np.asarray(mug_positions),
        "cup_matrices": np.asarray(mug_matrices),
        "right_palm_positions": np.asarray(palm_positions),
        "right_palm_matrices": np.asarray(palm_matrices),
    }
    continuation_path = args.output / "CONTINUATION_PHYSICS_TRAJECTORY.npz"
    np.savez_compressed(continuation_path, **arrays)
    trajectory_path = combine_with_source_pickup(
        args.output, source, start_index, continuation_path
    )

    times_array = arrays["times"]
    cup_positions = arrays["cup_positions"]
    cup_matrices = arrays["cup_matrices"]
    hand_flags = np.asarray(hand_contact_flags, dtype=bool)
    desk_flags = np.asarray(desk_contact_flags, dtype=bool)
    final_window = times_array >= max(0.0, float(times_array[-1]) - 1.0)
    final_hand_fraction = float(np.mean(hand_flags[final_window]))
    final_desk_fraction = float(np.mean(desk_flags[final_window]))
    final_tilt = math.degrees(
        math.acos(float(np.clip(cup_matrices[-1, 2, 2], -1.0, 1.0)))
    )
    final_linear_speed = float(
        np.linalg.norm(data.qvel[mug_dof_address : mug_dof_address + 3])
    )
    final_angular_speed = float(
        np.linalg.norm(data.qvel[mug_dof_address + 3 : mug_dof_address + 6])
    )
    final_target_error = (
        float(np.linalg.norm(cup_positions[-1] - target_cup_position))
        if target_cup_position is not None
        else math.inf
    )
    final_xy_error = (
        float(np.linalg.norm(cup_positions[-1, :2] - target_cup_position[:2]))
        if target_cup_position is not None
        else math.inf
    )
    carry_relative_positions = np.asarray(carry_relative_positions)
    if len(carry_relative_positions):
        reference_relative = carry_relative_positions[0]
        max_carry_slip = float(
            np.max(
                np.linalg.norm(
                    carry_relative_positions - reference_relative[None, :], axis=1
                )
            )
        )
    else:
        max_carry_slip = math.inf
    carry_contact_fraction = float(
        np.mean(
            [
                row["cup_hand_contact"]
                for row in timeline
                if row["phase"]
                in {
                    "free_settle",
                    "rotate",
                    "post_rotate_settle",
                    "navigate",
                    "navigate_east",
                    "navigate_north",
                    "navigate_west",
                    "navigation_settle",
                    "reach_approach",
                    "approach_hold",
                    "lower",
                }
            ]
        )
    )
    final_base_error = float(
        np.linalg.norm(
            data.qpos[:2] - np.array([args.target_base_x, args.target_base_y])
        )
    )
    rotation_achieved = (
        abs(math.degrees(wrap_angle(base_yaw(data.qpos) - rotation_start_yaw)))
        if rotation_start_yaw is not None
        else 0.0
    )
    desk_support_stop = any(
        event["phase"] == "settle_place" for event in phase_events
    )
    task_success = bool(
        phase == "complete"
        and failure_reason is None
        and not fell
        and (
            rotation_achieved >= 75.0
            if args.route == "rotator"
            else abs(math.degrees(wrap_angle(base_yaw(data.qpos) - base_yaw(arrays["qpos"][0]))))
            <= 15.0
        )
        and final_base_error <= 0.12
        and carry_contact_fraction >= 0.80
        and max_carry_slip <= 0.035
        and desk_support_stop
        and final_xy_error <= 0.05
        and abs(cup_positions[-1, 2] - (DESK_TOP_Z_M + 0.0585)) <= 0.04
        and final_tilt <= 15.0
        and final_linear_speed <= 0.05
        and final_angular_speed <= 0.50
        and final_hand_fraction <= 0.05
        and final_desk_fraction >= 0.80
        and post_release_hand_contact_steps == 0
        and not robot_room_contact_pairs
    )

    source_report = json.loads(SOURCE_REPORT.read_text())
    source_prefix_duration = float(source["times"][start_index] - source["times"][0])
    report = {
        "schema": "bedroom_g1_cup_transfer_to_adjacent_desk_v1",
        "label": "physics_cross_desk_transfer_pass" if task_success else "physics_cross_desk_transfer_failed",
        "task_success": task_success,
        "failure_reason": failure_reason,
        "scene": source_report["scene"],
        "scope": "validated_friction_pickup_prefix_plus_free_base_turn_walk_desk_place_release",
        "source_pickup_run": str(SOURCE_RUN),
        "source_pickup_report_sha256": sha256(SOURCE_REPORT),
        "model_xml": str(model_xml),
        "model_xml_sha256": sha256(model_xml),
        "trajectory": str(trajectory_path),
        "trajectory_sha256": sha256(trajectory_path),
        "continuation_trajectory": str(continuation_path),
        "continuation_trajectory_sha256": sha256(continuation_path),
        "preflight": preflight,
        "placement_plan": placement_plan,
        "phase_events": phase_events,
        "video_timeline": {
            "source_pickup_prefix_duration_s": source_prefix_duration,
            "continuation_duration_s": float(times_array[-1]),
            "combined_duration_s": float(
                source_prefix_duration + times_array[-1]
            ),
        },
        "physics": {
            "executed": True,
            "timestep_s": dt,
            "steps": step + 1,
            "duration_s": float(data.time),
            "saved_trajectory_fps": 1.0 / (dt * video_every),
            "mug_is_dynamic_free_body": True,
            "mug_pose_writes_after_initialization": 0,
            "mug_weld_or_equality_constraints": [],
            "mug_mass_kg": 0.20,
            "mug_sliding_friction": 2.0,
            "mug_collision_proxy": "vertical_cylinder_excluding_handle",
            "robot_base_weld_initially_active": True,
            "robot_base_weld_release_time_s": base_release_time,
            "robot_base_weld_active_after_release": bool(data.eq_active[weld_id]),
            "route": args.route,
            "rotator_policy_used": args.route == "rotator",
            "walker_policy_used": True,
            "direct_arm_pd_used_throughout_continuation": True,
            "carry_arm_command_rad": carry_arm.tolist(),
        },
        "motion_evidence": {
            "initial_base_xy_m": arrays["qpos"][0, :2].tolist(),
            "navigation_start_xy_m": (
                navigation_start_xy.tolist() if navigation_start_xy is not None else None
            ),
            "final_base_xyz_m": data.qpos[:3].tolist(),
            "target_base_xy_m": [args.target_base_x, args.target_base_y],
            "final_base_position_error_m": final_base_error,
            "rotation_achieved_deg": rotation_achieved,
            "max_base_tilt_deg": max_base_tilt_deg,
            "max_base_angular_speed_rad_s": max_base_angular_speed,
            "minimum_base_height_m": min_base_height,
            "max_carry_relative_position_slip_m": max_carry_slip,
            "carry_hand_contact_saved_frame_fraction": carry_contact_fraction,
            "target_cup_center_xyz_m": (
                target_cup_position.tolist() if target_cup_position is not None else None
            ),
            "final_cup_center_xyz_m": cup_positions[-1].tolist(),
            "final_cup_target_error_m": final_target_error,
            "final_cup_xy_error_m": final_xy_error,
            "final_cup_tilt_deg": final_tilt,
            "final_cup_linear_speed_mps": final_linear_speed,
            "final_cup_angular_speed_rad_s": final_angular_speed,
            "final_hand_contact_saved_frame_fraction": final_hand_fraction,
            "final_desk_contact_saved_frame_fraction": final_desk_fraction,
            "robot_fell": fell,
        },
        "contact_evidence": {
            "desk_support_stop_triggered": desk_support_stop,
            "post_release_hand_contact_steps": post_release_hand_contact_steps,
            "max_mug_contact_penetration_m": max_mug_penetration,
            "robot_room_nonfloor_contact_pairs": [
                list(pair) for pair in sorted(robot_room_contact_pairs)
            ],
            "robot_room_max_penetration_m": robot_room_max_penetration,
        },
        "acceptance": {
            "transfer_target_met": task_success,
            "target": {
                "minimum_rotation_deg": 75.0,
                "maximum_final_base_position_error_m": 0.12,
                "minimum_carry_hand_contact_fraction": 0.80,
                "maximum_carry_slip_m": 0.035,
                "desk_support_stop_required": True,
                "maximum_final_cup_xy_error_m": 0.05,
                "maximum_final_cup_height_error_m": 0.04,
                "maximum_final_cup_tilt_deg": 15.0,
                "maximum_final_cup_linear_speed_mps": 0.05,
                "maximum_final_cup_angular_speed_rad_s": 0.50,
                "maximum_final_hand_contact_fraction": 0.05,
                "minimum_final_desk_contact_fraction": 0.80,
                "maximum_post_release_hand_contact_steps": 0,
                "maximum_robot_room_nonfloor_contact_pairs": 0,
            },
            "production_accepted": False,
            "learning_validated": False,
        },
        "timeline": timeline,
    }
    write_json(args.output / "REPORT.json", report)
    print(
        json.dumps(
            {
                "task_success": task_success,
                "failure_reason": failure_reason,
                "phase": phase,
                "motion_evidence": report["motion_evidence"],
                "contact_evidence": report["contact_evidence"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
