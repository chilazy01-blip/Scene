#!/usr/bin/env python3
"""Zero-integration azimuth scan for grasping the cylindrical mug body.

The visible mug handle is absent from the documented dynamics proxy.  This
scan therefore combines execution-model IK/contact checks with an explicit
angular clearance gate against the measured visible-handle direction.  It
does not claim dynamic grasp success and consumes no physics rollout budget.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import mujoco
import numpy as np
from scipy.spatial.transform import Rotation

from .bedroom_g1_cup_pick_place_physics_v1 import (
    MUG_BODY,
    MUG_FREEJOINT,
    PALM_BODY,
    SOURCE_MODEL,
    SOURCE_VISUAL_TRAJECTORY,
    copy_joint_state_by_name,
    joint_addresses,
)
from .bedroom_g1_cup_pick_place_v3 import (
    ARM_NAMES,
    FINGER_NAMES,
    contact_classification,
    solve_palm_pose,
)


ROOT = Path("/data/wsj/main")
DEFAULT_MODEL = (
    ROOT
    / "scene_runs/codex_trellis_v2"
    / "bedroom_g1_cup_grip_load_20261013_v1_baseline/MODEL.xml"
)
DEFAULT_BASELINE_REPORT = (
    ROOT
    / "scene_runs/codex_trellis_v2"
    / "bedroom_g1_cup_grip_load_20261013_v1_baseline/REPORT.json"
)
DEFAULT_BASELINE_TRAJECTORY = (
    ROOT
    / "scene_runs/codex_trellis_v2"
    / "bedroom_g1_cup_grip_load_20261013_v1_baseline"
    / "ROBOT_CUP_PHYSICS_TRAJECTORY.npz"
)
DEFAULT_OUTPUT = (
    ROOT
    / "scene_runs/codex_trellis_v2"
    / "bedroom_g1_cup_body_grasp_scan_20261013_v1/PREFLIGHT.json"
)

# Derived from the outer-vertex centroid of bedside_mug_geometry_0 after the
# renderer's root transform is replaced by the simulated mug pose.
VISIBLE_HANDLE_AZIMUTH_DEG = 115.0
MINIMUM_HANDLE_SEPARATION_DEG = 45.0


def wrap_degrees(value: float) -> float:
    return (value + 180.0) % 360.0 - 180.0


def hand_cup_contacts(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    cup_body_id: int,
) -> tuple[list[str], float]:
    bodies = set()
    max_penetration = 0.0
    for contact in data.contact[: data.ncon]:
        geom1 = int(contact.geom1)
        geom2 = int(contact.geom2)
        body1 = int(model.geom_bodyid[geom1])
        body2 = int(model.geom_bodyid[geom2])
        if cup_body_id not in (body1, body2):
            continue
        other = body2 if body1 == cup_body_id else body1
        name = (
            mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, other)
            or f"body_{other}"
        )
        if name.startswith("right_hand_"):
            bodies.add(name)
            max_penetration = max(max_penetration, max(0.0, -float(contact.dist)))
    return sorted(bodies), max_penetration


def digit_set(body_names: list[str]) -> set[str]:
    result = set()
    for name in body_names:
        for digit in ("thumb", "index", "middle"):
            if digit in name:
                result.add(digit)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", nargs="?", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument(
        "--baseline-report", type=Path, default=DEFAULT_BASELINE_REPORT
    )
    parser.add_argument(
        "--baseline-trajectory", type=Path, default=DEFAULT_BASELINE_TRAJECTORY
    )
    parser.add_argument(
        "--angles-deg",
        type=float,
        nargs="+",
        default=[-90.0, -60.0, -30.0, 0.0, 30.0, 60.0, 90.0],
    )
    args = parser.parse_args()
    if args.output.exists():
        raise RuntimeError(f"output already exists: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)

    model = mujoco.MjModel.from_xml_path(str(args.model))
    source_model = mujoco.MjModel.from_xml_path(str(SOURCE_MODEL))
    source = np.load(SOURCE_VISUAL_TRAJECTORY)
    baseline = json.loads(args.baseline_report.read_text())
    baseline_trajectory = np.load(args.baseline_trajectory)
    data = mujoco.MjData(model)
    ik_data = mujoco.MjData(model)

    grasp_qpos = source["qpos"][60]
    data.qpos[:] = model.qpos0
    copy_joint_state_by_name(source_model, grasp_qpos, model, data.qpos)
    mug_joint_id = mujoco.mj_name2id(
        model, mujoco.mjtObj.mjOBJ_JOINT, MUG_FREEJOINT
    )
    mug_qpos_address = int(model.jnt_qposadr[mug_joint_id])
    mug_position = np.array([1.48, 0.31, 0.9553], dtype=float)
    data.qpos[mug_qpos_address : mug_qpos_address + 3] = mug_position
    data.qpos[mug_qpos_address + 3 : mug_qpos_address + 7] = [1.0, 0.0, 0.0, 0.0]
    data.qvel[:] = 0.0
    mujoco.mj_forward(model, data)

    arm_addresses = joint_addresses(model, ARM_NAMES)
    arm_joint_ids = np.asarray([model.joint(name).id for name in ARM_NAMES])
    lower = model.jnt_range[arm_joint_ids, 0].copy()
    upper = model.jnt_range[arm_joint_ids, 1].copy()
    lower[3] = max(lower[3], 0.10)
    finger_addresses = joint_addresses(model, FINGER_NAMES)
    pre_disturbance_index = int(
        np.flatnonzero(baseline_trajectory["times"] <= 5.25)[-1]
    )
    held_qpos = baseline_trajectory["qpos"][pre_disturbance_index].copy()
    closed_fingers = held_qpos[finger_addresses].copy()
    palm_body_id = model.body(PALM_BODY).id
    cup_body_id = model.body(MUG_BODY).id

    original_grasp_arm = data.qpos[arm_addresses].copy()
    original_lift_arm = held_qpos[arm_addresses].copy()
    held_cup_position = baseline_trajectory["cup_positions"][
        pre_disturbance_index
    ].copy()
    held_palm_position = baseline_trajectory["right_palm_positions"][
        pre_disturbance_index
    ].copy()
    held_palm_matrix = baseline_trajectory["right_palm_matrices"][
        pre_disturbance_index
    ].copy()
    held_palm_from_cup = held_palm_position - held_cup_position
    measured_lift = float(held_cup_position[2] - mug_position[2])
    lift_mug_position = mug_position + np.array([0.0, 0.0, measured_lift])

    candidates = []
    base_qpos = data.qpos.copy()
    for angle_deg in args.angles_deg:
        rotation = Rotation.from_euler("z", angle_deg, degrees=True).as_matrix()
        grasp_position = mug_position + rotation @ held_palm_from_cup
        lift_position = lift_mug_position + rotation @ held_palm_from_cup
        grasp_matrix = rotation @ held_palm_matrix
        lift_matrix = rotation @ held_palm_matrix
        palm_azimuth_deg = math.degrees(
            math.atan2(
                grasp_position[1] - mug_position[1],
                grasp_position[0] - mug_position[0],
            )
        )
        handle_separation_deg = abs(
            wrap_degrees(palm_azimuth_deg - VISIBLE_HANDLE_AZIMUTH_DEG)
        )
        row = {
            "angle_offset_deg": angle_deg,
            "palm_azimuth_deg": palm_azimuth_deg,
            "visible_handle_azimuth_deg": VISIBLE_HANDLE_AZIMUTH_DEG,
            "visible_handle_angular_separation_deg": handle_separation_deg,
            "visible_handle_clearance_pass": (
                handle_separation_deg >= MINIMUM_HANDLE_SEPARATION_DEG
            ),
            "target_grasp_palm_xyz_m": grasp_position.tolist(),
        }
        try:
            grasp_arm, grasp_position_error, grasp_orientation_error = (
                solve_palm_pose(
                    model,
                    ik_data,
                    base_qpos,
                    arm_addresses,
                    lower,
                    upper,
                    palm_body_id,
                    grasp_position,
                    grasp_matrix,
                    original_grasp_arm,
                    original_grasp_arm,
                )
            )
            lift_arm, lift_position_error, lift_orientation_error = solve_palm_pose(
                model,
                ik_data,
                base_qpos,
                arm_addresses,
                lower,
                upper,
                palm_body_id,
                lift_position,
                lift_matrix,
                grasp_arm,
                original_lift_arm,
            )
        except RuntimeError as exc:
            row.update({"ik_pass": False, "failure": str(exc), "pass": False})
            candidates.append(row)
            continue

        endpoint_qpos = base_qpos.copy()
        endpoint_qpos[arm_addresses] = grasp_arm
        endpoint_qpos[finger_addresses] = closed_fingers
        data.qpos[:] = endpoint_qpos
        mujoco.mj_forward(model, data)
        mujoco.mj_collision(model, data)
        endpoint_contacts = contact_classification(model, data, cup_body_id)
        hand_bodies, max_hand_penetration = hand_cup_contacts(
            model, data, cup_body_id
        )
        digits = digit_set(hand_bodies)

        path_collision_rows = []
        max_path_hand_penetration = 0.0
        path_contact_digits = set()
        for sample_index, alpha in enumerate(np.linspace(0.0, 1.0, 61)):
            work = base_qpos.copy()
            work[arm_addresses] = (1.0 - alpha) * grasp_arm + alpha * lift_arm
            work[finger_addresses] = closed_fingers
            work[mug_qpos_address : mug_qpos_address + 3] = (
                (1.0 - alpha) * mug_position + alpha * lift_mug_position
            )
            work[mug_qpos_address + 3 : mug_qpos_address + 7] = [1.0, 0.0, 0.0, 0.0]
            data.qpos[:] = work
            mujoco.mj_forward(model, data)
            mujoco.mj_collision(model, data)
            contacts = contact_classification(model, data, cup_body_id)
            path_bodies, penetration = hand_cup_contacts(model, data, cup_body_id)
            path_contact_digits.update(digit_set(path_bodies))
            max_path_hand_penetration = max(max_path_hand_penetration, penetration)
            if contacts["robot_room"] or contacts["robot_self"]:
                path_collision_rows.append(
                    {
                        "sample_index": sample_index,
                        "alpha": float(alpha),
                        "robot_room": contacts["robot_room"],
                        "robot_self": contacts["robot_self"],
                    }
                )

        joint_margin = float(
            min(
                np.min(grasp_arm - lower),
                np.min(upper - grasp_arm),
                np.min(lift_arm - lower),
                np.min(upper - lift_arm),
            )
        )
        passes = bool(
            row["visible_handle_clearance_pass"]
            and not endpoint_contacts["robot_room"]
            and not endpoint_contacts["robot_self"]
            and not path_collision_rows
            and max(max_hand_penetration, max_path_hand_penetration) <= 0.005
            and joint_margin >= 0.01
        )
        row.update(
            {
                "ik_pass": True,
                "grasp_ik_position_error_m": grasp_position_error,
                "grasp_ik_orientation_error_deg": math.degrees(
                    grasp_orientation_error
                ),
                "lift_ik_position_error_m": lift_position_error,
                "lift_ik_orientation_error_deg": math.degrees(
                    lift_orientation_error
                ),
                "minimum_arm_joint_limit_margin_rad": joint_margin,
                "closed_grasp_contact_bodies": hand_bodies,
                "closed_grasp_contact_digits": sorted(digits),
                "lift_path_contact_digits": sorted(path_contact_digits),
                "max_static_hand_cup_penetration_m": max(
                    max_hand_penetration, max_path_hand_penetration
                ),
                "endpoint_robot_room_contacts": endpoint_contacts["robot_room"],
                "endpoint_robot_self_contacts": endpoint_contacts["robot_self"],
                "lift_path_collision_rows": path_collision_rows,
                "grasp_arm_rad": grasp_arm.tolist(),
                "lift_arm_rad": lift_arm.tolist(),
                "pass": passes,
            }
        )
        candidates.append(row)

    passing = [row for row in candidates if row["pass"] and row["angle_offset_deg"]]
    passing.sort(
        key=lambda row: (
            -row["minimum_arm_joint_limit_margin_rad"],
            -row["visible_handle_angular_separation_deg"],
        )
    )
    report = {
        "schema": "bedroom_g1_cup_body_grasp_azimuth_preflight_v1",
        "integration_steps": 0,
        "model": str(args.model),
        "source_trajectory": str(SOURCE_VISUAL_TRAJECTORY),
        "baseline_dynamic_trajectory": str(args.baseline_trajectory),
        "baseline_actual_state_time_s": float(
            baseline_trajectory["times"][pre_disturbance_index]
        ),
        "baseline_actual_finger_qpos_rad": closed_fingers.tolist(),
        "baseline_measured_lift_m": measured_lift,
        "mug_collision_proxy": "vertical_cylinder_excluding_handle",
        "visible_handle_measurement": {
            "method": "outer-vertex centroid of bedside_mug_geometry_0 in the renderer-local mug frame",
            "azimuth_deg": VISIBLE_HANDLE_AZIMUTH_DEG,
            "minimum_accepted_palm_separation_deg": MINIMUM_HANDLE_SEPARATION_DEG,
            "limitation": "Angular clearance is a conservative screen, not a full visual-mesh collision computation.",
        },
        "acceptance": {
            "grasp_and_lift_6d_ik": True,
            "robot_room_contacts": 0,
            "robot_self_contacts": 0,
            "static_contact_digits": (
                "diagnostic_only because actuator settling is required to "
                "establish the force-bearing three-digit grasp"
            ),
            "dynamic_contact_requirement": ["thumb", "index", "middle"],
            "maximum_static_hand_cup_penetration_m": 0.005,
            "minimum_arm_joint_limit_margin_rad": 0.01,
        },
        "candidates": candidates,
        "passing_offsets_deg": [row["angle_offset_deg"] for row in passing],
        "recommended_dynamic_offsets_deg": [
            row["angle_offset_deg"] for row in passing[:2]
        ],
        "pass": bool(passing),
        "production_accepted": False,
        "learning_validated": False,
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
