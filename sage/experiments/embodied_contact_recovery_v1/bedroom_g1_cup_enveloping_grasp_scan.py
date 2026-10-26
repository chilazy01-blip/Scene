#!/usr/bin/env python3
"""Zero-integration joint search for a smaller-mug enveloping grasp.

The scan jointly varies mug radius, palm radial inset, and per-digit closure.
It requires thumb, index, and middle-finger contact with opposing contact
azimuths before a candidate can be admitted to a dynamic rollout.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

import mujoco
import numpy as np

from .bedroom_g1_cup_pick_place_physics_v1 import (
    MUG_BODY,
    MUG_FREEJOINT,
    MUG_PROXY_GEOM,
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
    sha256,
    solve_palm_pose,
)


ROOT = Path("/data/wsj/main")
DEFAULT_RUN = (
    ROOT
    / "scene_runs/codex_trellis_v2"
    / "bedroom_g1_cup_body_grasp_lift_20261013_v8_index031_lift010"
)
DEFAULT_OUTPUT = (
    ROOT
    / "scene_runs/codex_trellis_v2"
    / "bedroom_g1_cup_enveloping_grasp_scan_20261013_v1/PREFLIGHT.json"
)
FULLY_CLOSED = np.array(
    [0.80, -0.90, -1.50, 1.40, 1.50, 1.40, 1.50], dtype=float
)
MUG_POSITION = np.array([1.48, 0.31, 0.9553], dtype=float)


def circular_separation_deg(first: float, second: float) -> float:
    return abs((first - second + 180.0) % 360.0 - 180.0)


def digit_from_body(name: str) -> str | None:
    for digit in ("thumb", "index", "middle"):
        if digit in name:
            return digit
    return None


def contact_geometry(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    cup_body_id: int,
    mug_half_height: float,
) -> dict:
    angles: dict[str, list[float]] = {
        "thumb": [],
        "index": [],
        "middle": [],
    }
    heights: dict[str, list[float]] = {
        "thumb": [],
        "index": [],
        "middle": [],
    }
    cup_position = data.xpos[cup_body_id]
    cup_matrix = data.xmat[cup_body_id].reshape(3, 3)
    bodies: set[str] = set()
    max_penetration = 0.0
    palm_contact = False
    for contact in data.contact[: data.ncon]:
        geom1 = int(contact.geom1)
        geom2 = int(contact.geom2)
        body1 = int(model.geom_bodyid[geom1])
        body2 = int(model.geom_bodyid[geom2])
        if cup_body_id not in (body1, body2):
            continue
        other = body2 if body1 == cup_body_id else body1
        body_name = (
            mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, other) or ""
        )
        if not body_name.startswith("right_hand_"):
            continue
        bodies.add(body_name)
        max_penetration = max(max_penetration, max(0.0, -float(contact.dist)))
        palm_contact = palm_contact or "palm" in body_name
        digit = digit_from_body(body_name)
        if digit is not None:
            point = np.asarray(contact.pos, dtype=float)
            angles[digit].append(
                math.degrees(
                    math.atan2(
                        point[1] - MUG_POSITION[1],
                        point[0] - MUG_POSITION[0],
                    )
                )
            )
            heights[digit].append(
                float((cup_matrix.T @ (point - cup_position))[2])
            )

    all_heights = [height for rows in heights.values() for height in rows]
    minimum_axial_rim_clearance = (
        mug_half_height - max(abs(height) for height in all_heights)
        if all_heights
        else -math.inf
    )

    def opposition(first: str, second: str) -> float:
        if not angles[first] or not angles[second]:
            return 0.0
        return max(
            circular_separation_deg(a, b)
            for a in angles[first]
            for b in angles[second]
        )

    return {
        "contact_bodies": sorted(bodies),
        "contact_angles_deg": angles,
        "contact_heights_in_cup_m": heights,
        "contact_digits": sorted(digit for digit, rows in angles.items() if rows),
        "palm_contact": palm_contact,
        "max_hand_cup_penetration_m": max_penetration,
        "minimum_axial_rim_clearance_m": minimum_axial_rim_clearance,
        "thumb_index_opposition_deg": opposition("thumb", "index"),
        "thumb_middle_opposition_deg": opposition("thumb", "middle"),
    }


def model_for_radius(source_root: ET.Element, radius: float) -> mujoco.MjModel:
    root = copy.deepcopy(source_root)
    geom = root.find(f".//geom[@name='{MUG_PROXY_GEOM}']")
    if geom is None:
        raise RuntimeError("dynamic mug proxy geom is missing")
    size = [float(value) for value in geom.attrib["size"].split()]
    geom.set("size", f"{radius:.9g} {size[1]:.9g}")
    return mujoco.MjModel.from_xml_string(ET.tostring(root, encoding="unicode"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", nargs="?", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--run", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--radii", type=float, nargs="+", default=[0.0418, 0.0396])
    parser.add_argument(
        "--radial-insets-m",
        type=float,
        nargs="+",
        default=[0.0, 0.003, 0.006, 0.009, 0.012],
    )
    parser.add_argument(
        "--vertical-offset-m",
        type=float,
        default=0.0,
        help="Move the scanned palm target along world vertical.",
    )
    parser.add_argument(
        "--thumb-fractions", type=float, nargs="+", default=[0.55, 0.60, 0.65, 0.70]
    )
    parser.add_argument(
        "--index-fractions", type=float, nargs="+", default=[0.31, 0.36, 0.41, 0.46, 0.51]
    )
    parser.add_argument(
        "--middle-fractions", type=float, nargs="+", default=[0.35, 0.40, 0.45, 0.50, 0.55]
    )
    parser.add_argument("--close-scale", type=float, default=1.10)
    parser.add_argument(
        "--upright-reference-time-s",
        type=float,
        help=(
            "Use the saved hand pose relative to the mug at this time, rotate "
            "that relative pose onto an upright mug, and scan measured-to-command "
            "finger closure gains instead of absolute closure fractions."
        ),
    )
    parser.add_argument(
        "--reference-thumb-gains",
        type=float,
        nargs="+",
        default=[0.0, 0.1, 0.2, 0.3],
    )
    parser.add_argument(
        "--reference-index-gains",
        type=float,
        nargs="+",
        default=[0.0, 0.1, 0.2, 0.3, 0.4],
    )
    parser.add_argument(
        "--reference-middle-gains",
        type=float,
        nargs="+",
        default=[0.0, 0.1, 0.2, 0.3, 0.4],
    )
    parser.add_argument("--minimum-opposition-deg", type=float, default=100.0)
    parser.add_argument("--maximum-penetration-m", type=float, default=0.005)
    parser.add_argument(
        "--minimum-axial-rim-clearance-m", type=float, default=0.0
    )
    args = parser.parse_args()
    if args.output.exists():
        raise RuntimeError(f"output already exists: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)

    report_path = args.run / "REPORT.json"
    model_path = args.run / "MODEL.xml"
    report = json.loads(report_path.read_text())
    source_root = ET.parse(model_path).getroot()
    source_model = mujoco.MjModel.from_xml_path(str(SOURCE_MODEL))
    source_trajectory = np.load(SOURCE_VISUAL_TRAJECTORY)
    grasp_qpos = source_trajectory["qpos"][60]
    reference_trajectory = np.load(args.run / "ROBOT_CUP_PHYSICS_TRAJECTORY.npz")
    reference_index = None
    reference_qpos = None
    reference_relative_palm_position = None
    reference_relative_palm_matrix = None
    if args.upright_reference_time_s is not None:
        reference_index = int(
            np.argmin(
                np.abs(
                    reference_trajectory["times"]
                    - args.upright_reference_time_s
                )
            )
        )
        reference_qpos = reference_trajectory["qpos"][reference_index].copy()
        reference_cup_position = reference_trajectory["cup_positions"][
            reference_index
        ]
        reference_cup_matrix = reference_trajectory["cup_matrices"][
            reference_index
        ]
        reference_relative_palm_position = reference_cup_matrix.T @ (
            reference_trajectory["right_palm_positions"][reference_index]
            - reference_cup_position
        )
        reference_relative_palm_matrix = reference_cup_matrix.T @ (
            reference_trajectory["right_palm_matrices"][reference_index]
        )
    baseline_arm = np.asarray(
        report["physics"]["grasp_azimuth_preflight"][0]["arm_rad"], dtype=float
    )
    open_fingers = np.asarray(report["finger_targets_rad"]["open"], dtype=float)

    candidates = []
    ik_rows = []
    for radius in args.radii:
        model = model_for_radius(source_root, radius)
        data = mujoco.MjData(model)
        ik_data = mujoco.MjData(model)
        if reference_qpos is not None:
            base_qpos = reference_qpos.copy()
        else:
            base_qpos = model.qpos0.copy()
            copy_joint_state_by_name(source_model, grasp_qpos, model, base_qpos)
        mug_joint_id = model.joint(MUG_FREEJOINT).id
        mug_qpos_address = int(model.jnt_qposadr[mug_joint_id])
        base_qpos[mug_qpos_address : mug_qpos_address + 3] = MUG_POSITION
        base_qpos[mug_qpos_address + 3 : mug_qpos_address + 7] = [1.0, 0.0, 0.0, 0.0]
        arm_addresses = joint_addresses(model, ARM_NAMES)
        finger_addresses = joint_addresses(model, FINGER_NAMES)
        arm_joint_ids = np.asarray([model.joint(name).id for name in ARM_NAMES])
        arm_lower = model.jnt_range[arm_joint_ids, 0].copy()
        arm_upper = model.jnt_range[arm_joint_ids, 1].copy()
        arm_lower[3] = max(arm_lower[3], 0.10)
        finger_joint_ids = np.asarray([model.joint(name).id for name in FINGER_NAMES])
        finger_limits = model.jnt_range[finger_joint_ids]
        palm_body_id = model.body(PALM_BODY).id
        cup_body_id = model.body(MUG_BODY).id
        mug_half_height = float(model.geom(MUG_PROXY_GEOM).size[1])

        baseline_qpos = base_qpos.copy()
        baseline_qpos[arm_addresses] = (
            reference_qpos[arm_addresses]
            if reference_qpos is not None
            else baseline_arm
        )
        data.qpos[:] = baseline_qpos
        data.qvel[:] = 0.0
        mujoco.mj_forward(model, data)
        if reference_relative_palm_position is not None:
            baseline_palm_position = (
                MUG_POSITION + reference_relative_palm_position
            )
            baseline_palm_matrix = reference_relative_palm_matrix.copy()
            solve_seed = reference_qpos[arm_addresses].copy()
        else:
            baseline_palm_position = data.xpos[palm_body_id].copy()
            baseline_palm_matrix = data.xmat[palm_body_id].reshape(3, 3).copy()
            solve_seed = baseline_arm
        radial_direction = baseline_palm_position[:2] - MUG_POSITION[:2]
        radial_direction /= np.linalg.norm(radial_direction)

        for radial_inset in args.radial_insets_m:
            target_position = baseline_palm_position.copy()
            target_position[:2] -= radial_inset * radial_direction
            target_position[2] += args.vertical_offset_m
            try:
                arm, position_error, orientation_error = solve_palm_pose(
                    model,
                    ik_data,
                    baseline_qpos,
                    arm_addresses,
                    arm_lower,
                    arm_upper,
                    palm_body_id,
                    target_position,
                    baseline_palm_matrix,
                    solve_seed,
                    solve_seed,
                )
            except RuntimeError as exc:
                ik_rows.append(
                    {
                        "radius_m": radius,
                        "radial_inset_m": radial_inset,
                        "vertical_offset_m": args.vertical_offset_m,
                        "ik_pass": False,
                        "failure": str(exc),
                    }
                )
                continue
            ik_rows.append(
                {
                    "radius_m": radius,
                    "radial_inset_m": radial_inset,
                    "ik_pass": True,
                    "position_error_m": position_error,
                    "orientation_error_deg": math.degrees(orientation_error),
                    "arm_rad": arm.tolist(),
                }
            )

            thumb_values = (
                args.reference_thumb_gains
                if reference_qpos is not None
                else args.thumb_fractions
            )
            index_values = (
                args.reference_index_gains
                if reference_qpos is not None
                else args.index_fractions
            )
            middle_values = (
                args.reference_middle_gains
                if reference_qpos is not None
                else args.middle_fractions
            )
            reference_fingers = (
                reference_qpos[finger_addresses]
                if reference_qpos is not None
                else None
            )
            closed_command = np.asarray(
                report["finger_targets_rad"]["closed"], dtype=float
            )
            for thumb_fraction in thumb_values:
                for index_fraction in index_values:
                    for middle_fraction in middle_values:
                        if reference_fingers is not None:
                            gains = np.asarray(
                                [
                                    thumb_fraction,
                                    thumb_fraction,
                                    thumb_fraction,
                                    index_fraction,
                                    index_fraction,
                                    middle_fraction,
                                    middle_fraction,
                                ],
                                dtype=float,
                            )
                            finger_target = reference_fingers + gains * (
                                closed_command - reference_fingers
                            )
                        else:
                            fractions = np.asarray(
                                [
                                    thumb_fraction,
                                    thumb_fraction,
                                    thumb_fraction,
                                    index_fraction,
                                    index_fraction,
                                    middle_fraction,
                                    middle_fraction,
                                ],
                                dtype=float,
                            )
                            finger_target = open_fingers + args.close_scale * fractions * (
                                FULLY_CLOSED - open_fingers
                            )
                        finger_target = np.clip(
                            finger_target,
                            finger_limits[:, 0],
                            finger_limits[:, 1],
                        )
                        work = baseline_qpos.copy()
                        work[arm_addresses] = arm
                        work[finger_addresses] = finger_target
                        data.qpos[:] = work
                        data.qvel[:] = 0.0
                        mujoco.mj_forward(model, data)
                        mujoco.mj_collision(model, data)
                        contacts = contact_classification(model, data, cup_body_id)
                        geometry = contact_geometry(
                            model, data, cup_body_id, mug_half_height
                        )
                        three_digit = geometry["contact_digits"] == [
                            "index",
                            "middle",
                            "thumb",
                        ]
                        minimum_opposition = min(
                            geometry["thumb_index_opposition_deg"],
                            geometry["thumb_middle_opposition_deg"],
                        )
                        enveloping_pass = bool(
                            three_digit
                            and minimum_opposition >= args.minimum_opposition_deg
                            and geometry["max_hand_cup_penetration_m"]
                            <= args.maximum_penetration_m
                            and geometry["minimum_axial_rim_clearance_m"]
                            >= args.minimum_axial_rim_clearance_m
                            and not contacts["robot_room"]
                            and not contacts["robot_self"]
                        )
                        candidates.append(
                            {
                                "radius_m": radius,
                                "radius_scale": radius / 0.044,
                                "radial_inset_m": radial_inset,
                                "vertical_offset_m": args.vertical_offset_m,
                                "thumb_close_fraction": thumb_fraction,
                                "index_close_fraction": index_fraction,
                                "middle_close_fraction": middle_fraction,
                                "finger_parameterization": (
                                    "reference_actual_to_command_gain"
                                    if reference_fingers is not None
                                    else "closure_fraction_before_scale"
                                ),
                                "finger_target_rad": finger_target.tolist(),
                                "ik_position_error_m": position_error,
                                "ik_orientation_error_deg": math.degrees(
                                    orientation_error
                                ),
                                **geometry,
                                "minimum_thumb_finger_opposition_deg": minimum_opposition,
                                "robot_room_collision_count": len(contacts["robot_room"]),
                                "robot_self_collision_count": len(contacts["robot_self"]),
                                "enveloping_preflight_pass": enveloping_pass,
                            }
                        )

    passing = [row for row in candidates if row["enveloping_preflight_pass"]]
    passing.sort(
        key=lambda row: (
            -row["minimum_thumb_finger_opposition_deg"],
            -row["minimum_axial_rim_clearance_m"],
            row["max_hand_cup_penetration_m"],
            row["radial_inset_m"],
        )
    )
    payload = {
        "schema": "scene.bedroom_g1_cup_enveloping_grasp_preflight.v1",
        "scope": "zero-integration smaller-mug palm-position and finger-closure search",
        "physics_rollout_executed": False,
        "mj_step_calls": 0,
        "source_run": str(args.run),
        "source_report_sha256": sha256(report_path),
        "source_model_sha256": sha256(model_path),
        "search": {
            "radii_m": args.radii,
            "radial_insets_m": args.radial_insets_m,
            "vertical_offset_m": args.vertical_offset_m,
            "thumb_fractions": args.thumb_fractions,
            "index_fractions": args.index_fractions,
            "middle_fractions": args.middle_fractions,
            "upright_reference_time_s": args.upright_reference_time_s,
            "upright_reference_frame_index": reference_index,
            "reference_thumb_gains": args.reference_thumb_gains,
            "reference_index_gains": args.reference_index_gains,
            "reference_middle_gains": args.reference_middle_gains,
            "close_scale": args.close_scale,
            "candidate_count": len(candidates),
        },
        "gates": {
            "required_contact_digits": ["thumb", "index", "middle"],
            "minimum_thumb_to_each_finger_opposition_deg": args.minimum_opposition_deg,
            "maximum_hand_cup_penetration_m": args.maximum_penetration_m,
            "minimum_axial_rim_clearance_m": (
                args.minimum_axial_rim_clearance_m
            ),
            "robot_room_collision_count": 0,
            "robot_self_collision_count": 0,
        },
        "passing_count": len(passing),
        "selected_candidate": passing[0] if passing else None,
        "top_passing_candidates": passing[:20],
        "ik_rows": ik_rows,
        "candidates": candidates,
        "claim_boundary": (
            "This is a collision/contact geometry screen with no integration, "
            "grip force, friction retention, or disturbance evidence."
        ),
    }
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "candidate_count": len(candidates),
                "passing_count": len(passing),
                "selected_candidate": passing[0] if passing else None,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
