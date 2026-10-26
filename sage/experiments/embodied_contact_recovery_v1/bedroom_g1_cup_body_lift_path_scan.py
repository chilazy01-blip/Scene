#!/usr/bin/env python3
"""Zero-integration lift-path scan from a measured dynamic grasp state.

The scan holds the measured palm orientation fixed, solves a sequence of 6D
IK targets, moves the mug collision proxy rigidly with the palm only for
collision auditing, and records joint-limit, Jacobian, gravity-torque, and
collision margins.  It never calls ``mj_step`` and therefore does not claim
that a dynamically held mug will follow the selected path.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
from pathlib import Path

import mujoco
import numpy as np

from .bedroom_g1_cup_pick_place_physics_v1 import (
    MUG_BODY,
    MUG_FREEJOINT,
    PALM_BODY,
    actuator_ids,
    joint_addresses,
)
from .bedroom_g1_cup_pick_place_v3 import (
    ARM_NAMES,
    contact_classification,
    sha256,
    solve_palm_pose,
)


ROOT = Path("/data/wsj/main")
DEFAULT_RUN = (
    ROOT
    / "scene_runs/codex_trellis_v2"
    / "bedroom_g1_cup_body_grasp_lift_20261013_v2_reanchor"
)
DEFAULT_OUTPUT = (
    ROOT
    / "scene_runs/codex_trellis_v2"
    / "bedroom_g1_cup_body_lift_path_scan_20261013_v1/PREFLIGHT.json"
)


def json_dump(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", nargs="?", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--run", type=Path, default=DEFAULT_RUN)
    parser.add_argument(
        "--x-offsets-m",
        type=float,
        nargs="+",
        default=[0.0, 0.04, 0.06, 0.08, 0.10, 0.12],
    )
    parser.add_argument(
        "--y-offsets-m",
        type=float,
        nargs="+",
        default=[-0.04, -0.02, 0.0, 0.02, 0.04],
    )
    parser.add_argument(
        "--z-offsets-m", type=float, nargs="+", default=[0.08, 0.10]
    )
    parser.add_argument("--samples", type=int, default=41)
    parser.add_argument(
        "--anchor-saved-index",
        type=int,
        help=(
            "Override the trajectory sample used for the non-task posture; "
            "useful when evaluating a directly held pre-grasp posture."
        ),
    )
    parser.add_argument(
        "--anchor-arm-source",
        choices=("measured", "planned_grasp", "resolved_enveloping_grasp"),
        default="measured",
        help=(
            "Use the measured lift-anchor arm state, or replace only the "
            "task-arm joints with the collision-audited grasp IK solution "
            "recorded in the source report."
        ),
    )
    parser.add_argument("--anchor-radial-inset-m", type=float, default=0.0)
    parser.add_argument("--anchor-vertical-offset-m", type=float, default=0.0)
    args = parser.parse_args()
    if args.samples < 2:
        parser.error("--samples must be at least 2")
    if args.output.exists():
        raise RuntimeError(f"output already exists: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)

    report_path = args.run / "REPORT.json"
    trajectory_path = args.run / "ROBOT_CUP_PHYSICS_TRAJECTORY.npz"
    report = json.loads(report_path.read_text())
    model_path = Path(report["model_xml"])
    model = mujoco.MjModel.from_xml_path(str(model_path))
    trajectory = np.load(trajectory_path)

    anchor_time = float(report["physics"]["lift_anchor_time_s"])
    anchor_index = (
        args.anchor_saved_index
        if args.anchor_saved_index is not None
        else int(np.argmin(np.abs(trajectory["times"] - anchor_time)))
    )
    if anchor_index < 0 or anchor_index >= len(trajectory["times"]):
        parser.error("--anchor-saved-index is outside the saved trajectory")
    anchor_qpos = trajectory["qpos"][anchor_index].copy()
    anchor_saved_time = float(trajectory["times"][anchor_index])

    arm_addresses = joint_addresses(model, ARM_NAMES)
    arm_joint_ids = np.asarray([model.joint(name).id for name in ARM_NAMES])
    arm_dof_addresses = np.asarray(
        [model.jnt_dofadr[joint_id] for joint_id in arm_joint_ids], dtype=int
    )
    arm_actuator_ids = actuator_ids(model, ARM_NAMES)
    lower = model.jnt_range[arm_joint_ids, 0].copy()
    upper = model.jnt_range[arm_joint_ids, 1].copy()
    elbow_index = ARM_NAMES.index("right_elbow_joint")
    # Match the execution script's extra guard against the elbow singularity.
    lower[elbow_index] = max(lower[elbow_index], 0.10)

    planned_grasp_arm = None
    if args.anchor_arm_source in ("planned_grasp", "resolved_enveloping_grasp"):
        grasp_rows = report["physics"]["grasp_azimuth_preflight"]
        grasp_row = next(
            row for row in grasp_rows if row["keyframe"] == "grasp"
        )
        planned_grasp_arm = np.asarray(grasp_row["arm_rad"], dtype=float)
        if args.anchor_arm_source == "planned_grasp":
            anchor_qpos[arm_addresses] = planned_grasp_arm

    mug_joint_id = mujoco.mj_name2id(
        model, mujoco.mjtObj.mjOBJ_JOINT, MUG_FREEJOINT
    )
    mug_qpos_address = int(model.jnt_qposadr[mug_joint_id])
    cup_body_id = model.body(MUG_BODY).id
    palm_body_id = model.body(PALM_BODY).id

    if args.anchor_arm_source == "resolved_enveloping_grasp":
        resolve_data = mujoco.MjData(model)
        resolve_data.qpos[:] = anchor_qpos
        resolve_data.qvel[:] = 0.0
        mujoco.mj_forward(model, resolve_data)
        cup_position = resolve_data.xpos[cup_body_id].copy()
        cup_matrix = resolve_data.xmat[cup_body_id].reshape(3, 3).copy()
        reference = report["physics"]["enveloping_reference"]
        relative_position = np.asarray(
            reference["relative_palm_position_in_cup_m"], dtype=float
        )
        relative_matrix = np.asarray(
            reference["relative_palm_matrix_in_cup"], dtype=float
        )
        resolved_arm, _, _ = solve_palm_pose(
            model,
            resolve_data,
            anchor_qpos,
            arm_addresses,
            lower,
            upper,
            palm_body_id,
            cup_position + cup_matrix @ relative_position,
            cup_matrix @ relative_matrix,
            planned_grasp_arm,
            planned_grasp_arm,
        )
        anchor_qpos[arm_addresses] = resolved_arm

    if (
        args.anchor_radial_inset_m != 0.0
        or args.anchor_vertical_offset_m != 0.0
    ):
        adjust_data = mujoco.MjData(model)
        adjust_data.qpos[:] = anchor_qpos
        adjust_data.qvel[:] = 0.0
        mujoco.mj_forward(model, adjust_data)
        current_palm_position = adjust_data.xpos[palm_body_id].copy()
        current_palm_matrix = adjust_data.xmat[palm_body_id].reshape(3, 3).copy()
        cup_position = adjust_data.xpos[cup_body_id].copy()
        radial = current_palm_position[:2] - cup_position[:2]
        radial /= np.linalg.norm(radial)
        target_position = current_palm_position.copy()
        target_position[:2] -= args.anchor_radial_inset_m * radial
        target_position[2] += args.anchor_vertical_offset_m
        adjusted_arm, _, _ = solve_palm_pose(
            model,
            adjust_data,
            anchor_qpos,
            arm_addresses,
            lower,
            upper,
            palm_body_id,
            target_position,
            current_palm_matrix,
            anchor_qpos[arm_addresses].copy(),
            anchor_qpos[arm_addresses].copy(),
        )
        anchor_qpos[arm_addresses] = adjusted_arm

    data = mujoco.MjData(model)
    ik_data = mujoco.MjData(model)
    data.qpos[:] = anchor_qpos
    data.qvel[:] = 0.0
    mujoco.mj_forward(model, data)
    anchor_palm_position = data.xpos[palm_body_id].copy()
    anchor_palm_matrix = data.xmat[palm_body_id].reshape(3, 3).copy()
    anchor_cup_position = data.xpos[cup_body_id].copy()
    anchor_arm = anchor_qpos[arm_addresses].copy()

    jacobian_position = np.zeros((3, model.nv), dtype=float)
    jacobian_rotation = np.zeros((3, model.nv), dtype=float)
    candidates = []
    alphas = np.linspace(0.0, 1.0, args.samples)

    for dx, dy, dz in itertools.product(
        args.x_offsets_m, args.y_offsets_m, args.z_offsets_m
    ):
        offset = np.asarray([dx, dy, dz], dtype=float)
        seed = anchor_arm.copy()
        joint_minima = np.full(len(ARM_NAMES), np.inf, dtype=float)
        max_position_error = 0.0
        max_orientation_error = 0.0
        max_condition = 0.0
        min_singular_value = math.inf
        max_gravity_ratio = 0.0
        robot_room_rows = []
        robot_self_rows = []
        failed = None

        for sample_index, alpha in enumerate(alphas):
            target_position = anchor_palm_position + alpha * offset
            try:
                solved, position_error, orientation_error = solve_palm_pose(
                    model,
                    ik_data,
                    anchor_qpos,
                    arm_addresses,
                    lower,
                    upper,
                    palm_body_id,
                    target_position,
                    anchor_palm_matrix,
                    seed,
                    anchor_arm,
                )
            except RuntimeError as exc:
                failed = {
                    "sample_index": sample_index,
                    "alpha": float(alpha),
                    "reason": str(exc),
                }
                break
            seed = solved
            margin = np.minimum(solved - lower, upper - solved)
            joint_minima = np.minimum(joint_minima, margin)
            max_position_error = max(max_position_error, position_error)
            max_orientation_error = max(max_orientation_error, orientation_error)

            work_qpos = anchor_qpos.copy()
            work_qpos[arm_addresses] = solved
            work_qpos[mug_qpos_address : mug_qpos_address + 3] = (
                anchor_cup_position + alpha * offset
            )
            data.qpos[:] = work_qpos
            data.qvel[:] = 0.0
            mujoco.mj_forward(model, data)
            mujoco.mj_collision(model, data)

            mujoco.mj_jacBody(
                model,
                data,
                jacobian_position,
                jacobian_rotation,
                palm_body_id,
            )
            jacobian = np.vstack(
                [
                    jacobian_position[:, arm_dof_addresses],
                    jacobian_rotation[:, arm_dof_addresses],
                ]
            )
            singular_values = np.linalg.svd(jacobian, compute_uv=False)
            smallest = float(singular_values[-1])
            condition = float(singular_values[0] / max(smallest, 1.0e-12))
            min_singular_value = min(min_singular_value, smallest)
            max_condition = max(max_condition, condition)

            torque_limits = np.max(
                np.abs(model.actuator_ctrlrange[arm_actuator_ids]), axis=1
            )
            gravity_ratio = float(
                np.max(
                    np.abs(data.qfrc_bias[arm_dof_addresses])
                    / np.maximum(torque_limits, 1.0e-9)
                )
            )
            max_gravity_ratio = max(max_gravity_ratio, gravity_ratio)

            contacts = contact_classification(model, data, cup_body_id)
            for category, destination in (
                ("robot_room", robot_room_rows),
                ("robot_self", robot_self_rows),
            ):
                for contact in contacts[category]:
                    destination.append(
                        {
                            "sample_index": sample_index,
                            "alpha": float(alpha),
                            **contact,
                        }
                    )

        min_joint_margin = (
            float(np.min(joint_minima)) if failed is None else None
        )
        min_elbow_margin = (
            float(joint_minima[elbow_index]) if failed is None else None
        )
        passed = bool(
            failed is None
            and dz >= 0.08
            and min_joint_margin is not None
            and min_joint_margin >= 0.05
            and max_condition <= 50.0
            and max_gravity_ratio <= 0.80
            and not robot_room_rows
            and not robot_self_rows
        )
        candidates.append(
            {
                "offset_xyz_m": offset.tolist(),
                "horizontal_distance_m": float(np.linalg.norm(offset[:2])),
                "ik_pass": failed is None,
                "failure": failed,
                "max_ik_position_error_m": max_position_error,
                "max_ik_orientation_error_deg": math.degrees(
                    max_orientation_error
                ),
                "minimum_joint_limit_margin_rad": min_joint_margin,
                "minimum_per_joint_margin_rad": (
                    dict(zip(ARM_NAMES, joint_minima.tolist()))
                    if failed is None
                    else None
                ),
                "minimum_elbow_limit_margin_rad": min_elbow_margin,
                "minimum_jacobian_singular_value": (
                    min_singular_value if failed is None else None
                ),
                "maximum_jacobian_condition_number": (
                    max_condition if failed is None else None
                ),
                "maximum_gravity_torque_to_actuator_limit_ratio": (
                    max_gravity_ratio if failed is None else None
                ),
                "robot_room_collision_samples": len(robot_room_rows),
                "robot_self_collision_samples": len(robot_self_rows),
                "first_robot_room_collision": (
                    robot_room_rows[0] if robot_room_rows else None
                ),
                "first_robot_self_collision": (
                    robot_self_rows[0] if robot_self_rows else None
                ),
                "preflight_pass": passed,
            }
        )

    passing = [row for row in candidates if row["preflight_pass"]]
    passing.sort(
        key=lambda row: (
            row["maximum_jacobian_condition_number"],
            row["horizontal_distance_m"],
        )
    )
    selected = passing[0] if passing else None
    pure_vertical = [
        row
        for row in candidates
        if row["offset_xyz_m"][0] == 0.0
        and row["offset_xyz_m"][1] == 0.0
        and row["offset_xyz_m"][2] == 0.08
    ][0]

    payload = {
        "schema": "scene.body_lift_path_preflight.v1",
        "scope": (
            "zero-integration fixed-wrist IK, collision, joint-margin, "
            "Jacobian, and gravity-torque scan"
        ),
        "physics_rollout_executed": False,
        "mj_step_calls": 0,
        "source_run": str(args.run),
        "source_report": str(report_path),
        "source_report_sha256": sha256(report_path),
        "source_trajectory": str(trajectory_path),
        "source_trajectory_sha256": sha256(trajectory_path),
        "model_xml": str(model_path),
        "model_xml_sha256": sha256(model_path),
        "anchor": {
            "arm_source": args.anchor_arm_source,
            "additional_radial_inset_m": args.anchor_radial_inset_m,
            "vertical_offset_m": args.anchor_vertical_offset_m,
            "reported_time_s": anchor_time,
            "saved_index_override": args.anchor_saved_index,
            "saved_sample_time_s": anchor_saved_time,
            "saved_sample_index": anchor_index,
            "palm_position_xyz_m": anchor_palm_position.tolist(),
            "cup_position_xyz_m": anchor_cup_position.tolist(),
            "arm_joint_positions_rad": dict(zip(ARM_NAMES, anchor_arm.tolist())),
            "measured_arm_joint_positions_rad": dict(
                zip(
                    ARM_NAMES,
                    trajectory["qpos"][anchor_index][arm_addresses].tolist(),
                )
            ),
            "planned_grasp_arm_rad": (
                planned_grasp_arm.tolist()
                if planned_grasp_arm is not None
                else None
            ),
        },
        "enforced_joint_limits_rad": {
            name: [float(lo), float(hi)]
            for name, lo, hi in zip(ARM_NAMES, lower, upper)
        },
        "gates": {
            "minimum_vertical_lift_m": 0.08,
            "minimum_joint_limit_margin_rad": 0.05,
            "maximum_jacobian_condition_number": 50.0,
            "maximum_gravity_torque_to_actuator_limit_ratio": 0.80,
            "maximum_robot_room_collision_samples": 0,
            "maximum_robot_self_collision_samples": 0,
        },
        "samples_per_candidate": args.samples,
        "candidate_count": len(candidates),
        "passing_candidate_count": len(passing),
        "pure_vertical_reference": pure_vertical,
        "selected_candidate": selected,
        "selection_rule": (
            "pass every gate, then minimize maximum Jacobian condition "
            "number, then horizontal path length"
        ),
        "candidates": candidates,
        "claim_boundary": (
            "The mug is moved kinematically with the palm for collision "
            "auditing only. Dynamic grasp retention remains untested."
        ),
    }
    json_dump(args.output, payload)
    print(json.dumps({
        "output": str(args.output),
        "candidate_count": len(candidates),
        "passing_candidate_count": len(passing),
        "pure_vertical_pass": pure_vertical["preflight_pass"],
        "selected_candidate": selected,
    }, indent=2))


if __name__ == "__main__":
    main()
