#!/usr/bin/env python3
"""Validate a friction-held G1 mug lift in the generated bedroom.

This is deliberately a bounded contact-feasibility experiment before a full
pick-and-place rollout.  The robot starts at the collision-audited side-grasp
pose from the visual v3 trajectory, closes its actuated fingers around a free
dynamic mug, lifts, and holds.  The mug is never welded to the hand and its
pose is never written after initialization.

The original bedroom mug remains the render asset.  Physics uses a documented
cylindrical proxy for the ceramic body because MuJoCo treats a dynamic mesh as
a convex hull, which would make the handle part of an oversized collision
hull.  This proxy is intentionally conservative and excludes the handle.
"""

from __future__ import annotations

import argparse
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path

import mujoco
import numpy as np
from scipy.spatial.transform import Rotation

from .bedroom_generated_walk import (
    BEDROOM_VISUAL_GLB,
    SOURCE,
    base_yaw,
    install_controller_adapter,
    sha256,
    visual_manifest,
    write_json,
)
from .bedroom_g1_cup_pick_place_v3 import (
    ARM_NAMES,
    FINGER_NAMES,
    smoothstep,
    solve_palm_pose,
)


ROOT = Path("/data/wsj/main")
SOURCE_MODEL = (
    ROOT
    / "scene_runs/codex_trellis_v2/full_bedroom_g1_walk_stable_20261012_v10"
    / "MODEL.xml"
)
SOURCE_VISUAL_TRAJECTORY = (
    ROOT
    / "scene_runs/codex_trellis_v2/bedroom_g1_cup_pick_place_visual_20261012_v3"
    / "ROBOT_CUP_VISUAL_TRAJECTORY.npz"
)
DEFAULT_OUTPUT = (
    ROOT
    / "scene_runs/codex_trellis_v2"
    / "bedroom_g1_cup_pick_place_physics_20261013_v1"
)

MUG_BODY = "bedroom_bedside_mug"
MUG_FREEJOINT = "bedroom_bedside_mug_freejoint"
MUG_PROXY_GEOM = "bedroom_dynamic_geom_bedside_mug_body_proxy"
PALM_BODY = "right_hand_palm_link"
TORSO_BODY = "torso_link"
BASE_WELD = "robot_base_stabilization_weld"


def qpos_width(joint_type: int) -> int:
    if joint_type == mujoco.mjtJoint.mjJNT_FREE:
        return 7
    if joint_type == mujoco.mjtJoint.mjJNT_BALL:
        return 4
    return 1


def copy_joint_state_by_name(
    source_model: mujoco.MjModel,
    source_qpos: np.ndarray,
    target_model: mujoco.MjModel,
    target_qpos: np.ndarray,
) -> None:
    """Copy all named source joints without assuming an unchanged qpos order."""
    for source_joint_id in range(source_model.njnt):
        name = mujoco.mj_id2name(
            source_model, mujoco.mjtObj.mjOBJ_JOINT, source_joint_id
        )
        if not name:
            continue
        target_joint_id = mujoco.mj_name2id(
            target_model, mujoco.mjtObj.mjOBJ_JOINT, name
        )
        if target_joint_id < 0:
            continue
        source_type = int(source_model.jnt_type[source_joint_id])
        target_type = int(target_model.jnt_type[target_joint_id])
        if source_type != target_type:
            raise RuntimeError(f"joint type changed for {name}")
        width = qpos_width(source_type)
        source_address = int(source_model.jnt_qposadr[source_joint_id])
        target_address = int(target_model.jnt_qposadr[target_joint_id])
        target_qpos[target_address : target_address + width] = source_qpos[
            source_address : source_address + width
        ]


def build_dynamic_model(
    output: Path,
    *,
    mug_position: np.ndarray,
    mug_mass: float,
    mug_radius: float,
    mug_half_height: float,
    mug_friction: float,
    stabilize_robot_base: bool,
    stabilized_base_position: np.ndarray | None = None,
    stabilized_base_quaternion: np.ndarray | None = None,
) -> Path:
    root = ET.parse(SOURCE_MODEL).getroot()
    mug = root.find(f".//body[@name='{MUG_BODY}']")
    if mug is None:
        raise RuntimeError(f"missing source mug body: {MUG_BODY}")

    for child in list(mug):
        mug.remove(child)
    mug.set("pos", " ".join(f"{value:.9g}" for value in mug_position))
    mug.set("quat", "1 0 0 0")

    freejoint = ET.Element("freejoint", name=MUG_FREEJOINT)
    mug.append(freejoint)
    full_height = 2.0 * mug_half_height
    inertia_xy = mug_mass * (3.0 * mug_radius**2 + full_height**2) / 12.0
    inertia_z = 0.5 * mug_mass * mug_radius**2
    ET.SubElement(
        mug,
        "inertial",
        pos="0 0 0",
        mass=f"{mug_mass:.9g}",
        diaginertia=f"{inertia_xy:.9g} {inertia_xy:.9g} {inertia_z:.9g}",
    )
    ET.SubElement(
        mug,
        "geom",
        name=MUG_PROXY_GEOM,
        type="cylinder",
        size=f"{mug_radius:.9g} {mug_half_height:.9g}",
        mass="0",
        contype="1",
        conaffinity="3",
        friction=f"{mug_friction:.9g} 0.01 0.001",
        margin="0",
        gap="0",
        solref=".004 1",
        solimp=".95 .99 .001 .5 2",
        condim="6",
        group="3",
        rgba="0 0 0 0",
    )

    if stabilize_robot_base:
        base = root.find(".//body[@name='base']")
        if base is None:
            raise RuntimeError("missing G1 base body")
        # A weld to world uses the model reference pose as its equilibrium.
        # Move that reference to the documented bedside task pose before the
        # weld is compiled; otherwise it would pull the initialized robot back
        # to the source model's origin.
        base_position = (
            stabilized_base_position
            if stabilized_base_position is not None
            else np.array([1.68, 0.85, 0.762])
        )
        base_quaternion = (
            stabilized_base_quaternion
            if stabilized_base_quaternion is not None
            else np.array(
                [0.7071067811865476, 0.0, 0.0, -0.7071067811865475]
            )
        )
        base.set("pos", " ".join(f"{value:.12g}" for value in base_position))
        base.set(
            "quat", " ".join(f"{value:.12g}" for value in base_quaternion)
        )
        equality = root.find("equality")
        if equality is None:
            equality = ET.SubElement(root, "equality")
        ET.SubElement(
            equality,
            "weld",
            name="robot_base_stabilization_weld",
            body1="base",
            solref=".004 1",
            solimp=".95 .99 .001 .5 2",
        )

    ET.indent(root)
    path = output / "MODEL.xml"
    ET.ElementTree(root).write(path, encoding="unicode")
    write_json(
        output / "DYNAMIC_MUG_BINDING.json",
        {
            "schema": "bedroom_dynamic_mug_binding_v1",
            "source_execution_model": str(SOURCE_MODEL),
            "source_execution_model_sha256": sha256(SOURCE_MODEL),
            "mug_body": MUG_BODY,
            "freejoint": MUG_FREEJOINT,
            "collision_proxy_geom": MUG_PROXY_GEOM,
            "collision_proxy": "vertical_cylinder_excluding_handle",
            "position_xyz_m": mug_position.tolist(),
            "initial_quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
            "mass_kg": mug_mass,
            "radius_m": mug_radius,
            "half_height_m": mug_half_height,
            "sliding_friction": mug_friction,
            "torsional_friction": 0.01,
            "rolling_friction": 0.001,
            "render_asset": str(BEDROOM_VISUAL_GLB),
            "render_object": "bedside_mug_root",
            "render_geometry_reused_from_scene": True,
            "weld_or_equality_constraint_added": False,
            "robot_base_stabilization_weld_added": stabilize_robot_base,
            "robot_base_stabilization_reference_position_m": (
                base_position.tolist() if stabilize_robot_base else None
            ),
            "robot_base_stabilization_reference_quaternion_wxyz": (
                base_quaternion.tolist() if stabilize_robot_base else None
            ),
        },
    )
    return path


def joint_addresses(model: mujoco.MjModel, names: tuple[str, ...]) -> np.ndarray:
    result = []
    for name in names:
        joint_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, name)
        if joint_id < 0:
            raise RuntimeError(f"joint not found: {name}")
        result.append(int(model.jnt_qposadr[joint_id]))
    return np.asarray(result, dtype=int)


def actuator_ids(model: mujoco.MjModel, names: tuple[str, ...]) -> np.ndarray:
    result = []
    for name in names:
        actuator_id = mujoco.mj_name2id(
            model, mujoco.mjtObj.mjOBJ_ACTUATOR, name
        )
        if actuator_id < 0:
            raise RuntimeError(f"actuator not found: {name}")
        result.append(actuator_id)
    return np.asarray(result, dtype=int)


def interpolate(a: np.ndarray, b: np.ndarray, value: float) -> np.ndarray:
    value = smoothstep(value)
    return (1.0 - value) * a + value * b


def interpolate_rotation(a: np.ndarray, b: np.ndarray, value: float) -> np.ndarray:
    """Interpolate two rotation matrices without a phase-boundary jump."""
    value = smoothstep(value)
    delta = Rotation.from_matrix(b @ a.T).as_rotvec()
    return Rotation.from_rotvec(value * delta).as_matrix() @ a


def scale_delta_preserving_direction(
    delta: np.ndarray, max_abs_component: float
) -> np.ndarray:
    """Limit a joint-space update without changing its coordinated direction."""
    largest = float(np.max(np.abs(delta)))
    if largest <= max_abs_component:
        return delta
    return delta * (max_abs_component / largest)


def other_contact_geom(contact, mug_geom_id: int) -> int | None:
    if int(contact.geom1) == mug_geom_id:
        return int(contact.geom2)
    if int(contact.geom2) == mug_geom_id:
        return int(contact.geom1)
    return None


def contact_sample(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    mug_geom_id: int,
) -> dict:
    hand_rows = []
    support_rows = []
    max_penetration = 0.0
    force = np.zeros(6, dtype=float)
    for contact_id in range(data.ncon):
        contact = data.contact[contact_id]
        other_geom_id = other_contact_geom(contact, mug_geom_id)
        if other_geom_id is None:
            continue
        other_geom_name = (
            mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, other_geom_id)
            or f"geom_{other_geom_id}"
        )
        other_body_id = int(model.geom_bodyid[other_geom_id])
        other_body_name = (
            mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, other_body_id)
            or "world"
        )
        mujoco.mj_contactForce(model, data, contact_id, force)
        normal_force = abs(float(force[0]))
        tangential_force = float(np.linalg.norm(force[1:3]))
        row = {
            "geom": other_geom_name,
            "body": other_body_name,
            "distance_m": float(contact.dist),
            "penetration_m": max(0.0, -float(contact.dist)),
            "normal_force_N": normal_force,
            "tangential_force_N": tangential_force,
            "friction_ratio": tangential_force / max(normal_force, 1.0e-9),
        }
        max_penetration = max(max_penetration, row["penetration_m"])
        if other_body_name.startswith("right_hand_"):
            hand_rows.append(row)
        elif other_body_name.startswith("bedroom_") or other_body_id == 0:
            support_rows.append(row)
    return {
        "hand": hand_rows,
        "support": support_rows,
        "max_mug_contact_penetration_m": max_penetration,
    }


def phase_at(time_s: float, phases: dict[str, float]) -> str:
    if time_s < phases["close_start"]:
        return "settle_open"
    if time_s < phases["close_end"]:
        return "close"
    if time_s < phases["lift_start"]:
        return "squeeze"
    if time_s < phases["lift_end"]:
        return "lift"
    if "carry_start" in phases:
        if time_s < phases["carry_start"]:
            return "hold_lift"
        if time_s < phases["carry_end"]:
            return "carry"
        if time_s < phases["lower_start"]:
            return "hold_carry"
        if time_s < phases["lower_end"]:
            return "lower"
        if time_s < phases["release_start"]:
            return "settle_place"
        if time_s < phases["release_end"]:
            return "release"
        if "retract_start" in phases and time_s < phases["retract_start"]:
            return "post_release_dwell"
        if "clearance_end" in phases and time_s < phases["clearance_end"]:
            return "clearance_retract"
        return "retract"
    return "hold"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", nargs="?", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--mug-mass", type=float, default=0.20)
    parser.add_argument("--mug-friction", type=float, default=1.20)
    parser.add_argument("--mug-radius", type=float, default=0.044)
    parser.add_argument("--mug-half-height", type=float, default=0.0585)
    parser.add_argument(
        "--grasp-azimuth-offset-deg",
        type=float,
        default=0.0,
        help=(
            "Orbit the palm target around the mug's world vertical axis and "
            "rotate the wrist by the same angle. Positive angles are "
            "counter-clockwise in world x-y."
        ),
    )
    parser.add_argument(
        "--grasp-radial-inset-m",
        type=float,
        default=0.0,
        help=(
            "Move the palm target this far toward the mug axis after the "
            "azimuth transform. Positive values create a deeper enveloping "
            "grasp; zero preserves prior runs."
        ),
    )
    parser.add_argument(
        "--grasp-vertical-offset-m",
        type=float,
        default=0.0,
        help=(
            "Translate the palm grasp frame along world vertical. Negative "
            "values move a near-rim finger contact down the mug body."
        ),
    )
    parser.add_argument(
        "--enveloping-reference-run",
        type=Path,
        help=(
            "Saved run whose measured palm pose relative to the mug is rotated "
            "onto an upright mug before applying the radial inset."
        ),
    )
    parser.add_argument("--enveloping-reference-time-s", type=float, default=3.0)
    parser.add_argument("--close-scale", type=float, default=1.0)
    parser.add_argument(
        "--closed-finger-targets-rad",
        type=float,
        nargs=7,
        help=(
            "Explicit seven-joint closed-hand target selected by an enveloping "
            "grasp preflight. Omit to use the per-digit closure fractions."
        ),
    )
    parser.add_argument(
        "--thumb-close-fraction",
        type=float,
        default=0.55,
        help=(
            "Closure fraction for all three thumb joints before close-scale. "
            "The 0.55 default preserves the established grasp baseline."
        ),
    )
    parser.add_argument(
        "--index-close-fraction",
        type=float,
        default=0.28,
        help=(
            "Closure fraction for both index-finger joints before close-scale. "
            "The 0.28 default preserves the established grasp baseline."
        ),
    )
    parser.add_argument(
        "--index-close-delay",
        type=float,
        default=0.0,
        help=(
            "Delay index-finger closure relative to the other digits while "
            "still reaching its full target at close_end."
        ),
    )
    parser.add_argument(
        "--thumb-close-completion-advance",
        type=float,
        default=0.0,
        help=(
            "Reach the thumb closure target this many seconds before close_end "
            "without starting before close_start."
        ),
    )
    parser.add_argument(
        "--middle-close-completion-advance",
        type=float,
        default=0.0,
        help=(
            "Reach the middle-finger target this many seconds before close_end "
            "without starting before close_start."
        ),
    )
    parser.add_argument(
        "--middle-close-fraction",
        type=float,
        default=0.0,
        help=(
            "Closure fraction for both middle-finger joints before close-scale. "
            "The zero default preserves the original two-digit v15 baseline."
        ),
    )
    parser.add_argument("--arm-tracking-gain", type=float, default=1.0)
    parser.add_argument("--cartesian-gain", type=float, default=1.0)
    parser.add_argument("--cartesian-max-joint-correction", type=float, default=0.18)
    parser.add_argument("--online-ik", action="store_true")
    parser.add_argument("--ik-max-joint-step", type=float, default=0.04)
    parser.add_argument(
        "--retract-max-joint-command-step",
        type=float,
        default=0.02,
        help=(
            "Per-control-update joint-command slew cap used only by the "
            "contact-aware post-release retract."
        ),
    )
    parser.add_argument("--stabilize-robot-base", action="store_true")
    parser.add_argument("--direct-fixed-base-arm-pd", action="store_true")
    parser.add_argument(
        "--direct-fixed-posture-pd",
        action="store_true",
        help=(
            "Directly hold every non-task body joint at the initialized "
            "grasp posture. Intended for the welded-base manipulation "
            "baseline, where balance-policy sag can otherwise move the "
            "shoulder frame during finger closure."
        ),
    )
    parser.add_argument(
        "--direct-lift-arm-pd",
        action="store_true",
        help=(
            "Enable the gravity-compensated direct arm PD only from lift "
            "start onward, preserving the pre-lift grasp closure."
        ),
    )
    parser.add_argument(
        "--direct-retract-arm-pd",
        action="store_true",
        help=(
            "Apply the direct fixed-base arm PD only after retract starts, "
            "preserving the validated grasp/carry/place dynamics."
        ),
    )
    parser.add_argument("--keep-walker-with-stabilized-base", action="store_true")
    parser.add_argument(
        "--base-release-time-s",
        type=float,
        help=(
            "Disable the temporary base weld at this time and hand the legs "
            "back to the standing/walking policy without restarting physics."
        ),
    )
    parser.add_argument(
        "--free-base-static-hold-s",
        type=float,
        default=3.0,
        help="Zero-command free-base hold before an optional walk command.",
    )
    parser.add_argument(
        "--base-release-posture-blend-s",
        type=float,
        default=0.0,
        help=(
            "Smoothly blend non-task-joint torque ownership from the fixed "
            "manipulation posture to the walker after releasing the base."
        ),
    )
    parser.add_argument(
        "--pre-release-posture-blend-s",
        type=float,
        default=0.0,
        help=(
            "While the base is still welded, transfer non-task-joint torque "
            "ownership from the fixed manipulation posture to the warmed "
            "walker so constraint preload can settle before release."
        ),
    )
    parser.add_argument(
        "--warm-walker-before-base-release",
        action="store_true",
        help=(
            "Advance walker action history while the base is welded. Leave "
            "off when releasing from a verified free-base standing state."
        ),
    )
    parser.add_argument("--walk-distance-m", type=float, default=0.0)
    parser.add_argument("--walk-speed-mps", type=float, default=0.08)
    parser.add_argument(
        "--walk-body-axis",
        choices=("forward", "backward", "left", "right"),
        default="left",
    )
    parser.add_argument(
        "--free-base-carry-frame",
        choices=("torso", "torso-height", "world-upright"),
        default="torso",
        help=(
            "Reference frame used by the task arm after base release. Torso "
            "keeps the grasp kinematically quiet; torso-height additionally "
            "holds release height; world-upright compensates full base "
            "height and attitude."
        ),
    )
    parser.add_argument(
        "--stable-stance-reference-run",
        type=Path,
        help=(
            "Run containing a verified free-base standing trajectory. Its "
            "non-task joints and base roll/pitch/height seed the bedside "
            "grasp before the temporary weld is released."
        ),
    )
    parser.add_argument("--stable-stance-reference-time-s", type=float, default=2.0)
    parser.add_argument("--walk-command-ramp-s", type=float, default=0.8)
    parser.add_argument(
        "--walk-stop-ramp-distance-m",
        type=float,
        default=0.0,
        help=(
            "Smoothly reduce the walk command over this remaining distance. "
            "Zero preserves the original threshold-triggered stop."
        ),
    )
    parser.add_argument("--post-release-index-tighten-rad", type=float, default=0.0)
    parser.add_argument("--post-release-finger-ramp-s", type=float, default=0.5)
    parser.add_argument(
        "--index-tighten-lead-s",
        type=float,
        default=0.0,
        help=(
            "Start the otherwise post-release index tightening this many "
            "seconds before base release."
        ),
    )
    parser.add_argument("--pre-release-carry-offset-x", type=float, default=0.0)
    parser.add_argument("--pre-release-carry-offset-y", type=float, default=0.0)
    parser.add_argument(
        "--pre-release-carry-duration-s",
        type=float,
        default=3.0,
        help=(
            "Duration of a fixed-base horizontal carry ending at base "
            "release, used to move the held cup beyond its source support."
        ),
    )
    parser.add_argument("--lift-height", type=float, default=0.14)
    parser.add_argument("--lift-duration", type=float, default=2.0)
    parser.add_argument(
        "--actual-lift-offset-x",
        type=float,
        default=0.0,
        help="World-x component of an actual-state-anchored lift path.",
    )
    parser.add_argument(
        "--actual-lift-offset-y",
        type=float,
        default=0.0,
        help="World-y component of an actual-state-anchored lift path.",
    )
    parser.add_argument(
        "--actual-state-lift-anchor",
        action="store_true",
        help=(
            "At lift start, re-anchor a fixed-wrist lift to the measured "
            "palm pose and arm state after dynamic grasp settling."
        ),
    )
    parser.add_argument("--duration", type=float)
    parser.add_argument("--full-pick-place", action="store_true")
    parser.add_argument(
        "--contact-aware-placement",
        action="store_true",
        help=(
            "Stop lowering after stable table support, wait for open-hand "
            "clearance, then use a slow fixed-wrist-reachable diagonal retract."
        ),
    )
    parser.add_argument("--transport-distance", type=float, default=0.10)
    parser.add_argument(
        "--cup-lateral-force-newtons",
        type=float,
        default=0.0,
        help=(
            "Peak world -x force applied to the free mug during the hold "
            "window. This is an isolated grip-load test, not locomotion."
        ),
    )
    parser.add_argument("--cup-force-start", type=float, default=5.30)
    parser.add_argument("--cup-force-end", type=float, default=6.30)
    parser.add_argument("--cup-force-ramp", type=float, default=0.25)
    args = parser.parse_args()
    if args.contact_aware_placement and not args.full_pick_place:
        parser.error("--contact-aware-placement requires --full-pick-place")
    if args.lift_duration <= 0.0:
        parser.error("--lift-duration must be positive")
    if not 0.0 <= args.index_close_fraction <= 1.0:
        parser.error("--index-close-fraction must be within [0, 1]")
    if not 0.0 <= args.index_close_delay < 1.2:
        parser.error("--index-close-delay must be within [0, 1.2)")
    if not 0.0 <= args.thumb_close_completion_advance < 1.2:
        parser.error(
            "--thumb-close-completion-advance must be within [0, 1.2)"
        )
    if not 0.0 <= args.middle_close_completion_advance < 1.2:
        parser.error(
            "--middle-close-completion-advance must be within [0, 1.2)"
        )
    if (
        abs(args.actual_lift_offset_x) > 0.0
        or abs(args.actual_lift_offset_y) > 0.0
    ) and not args.actual_state_lift_anchor:
        parser.error(
            "--actual-lift-offset-x/y require --actual-state-lift-anchor"
        )
    if args.full_pick_place and args.lift_duration != 2.0:
        parser.error("non-default --lift-duration is currently lift-hold only")
    if args.full_pick_place and args.actual_state_lift_anchor:
        parser.error("--actual-state-lift-anchor is currently lift-hold only")
    if args.base_release_time_s is not None:
        if not args.stabilize_robot_base:
            parser.error("--base-release-time-s requires --stabilize-robot-base")
        if args.full_pick_place:
            parser.error("free-base continuation is currently lift-hold only")
        if args.base_release_time_s < 3.0 + args.lift_duration:
            parser.error("base release must occur after the lift phase")
        if args.free_base_static_hold_s < 1.0:
            parser.error("--free-base-static-hold-s must be at least 1 second")
        if args.walk_distance_m < 0.0:
            parser.error("--walk-distance-m must be nonnegative")
        if args.walk_speed_mps <= 0.0:
            parser.error("--walk-speed-mps must be positive")
        if args.walk_command_ramp_s <= 0.0:
            parser.error("--walk-command-ramp-s must be positive")
        if args.walk_stop_ramp_distance_m < 0.0:
            parser.error("--walk-stop-ramp-distance-m must be nonnegative")
        if args.post_release_index_tighten_rad < 0.0:
            parser.error("--post-release-index-tighten-rad must be nonnegative")
        if args.post_release_finger_ramp_s <= 0.0:
            parser.error("--post-release-finger-ramp-s must be positive")
        if args.index_tighten_lead_s < 0.0:
            parser.error("--index-tighten-lead-s must be nonnegative")
        if args.index_tighten_lead_s > args.base_release_time_s:
            parser.error("--index-tighten-lead-s exceeds base release time")
        if args.pre_release_carry_duration_s <= 0.0:
            parser.error("--pre-release-carry-duration-s must be positive")
        if (
            (
                abs(args.pre_release_carry_offset_x) > 0.0
                or abs(args.pre_release_carry_offset_y) > 0.0
            )
            and args.base_release_time_s - args.pre_release_carry_duration_s
            < 3.0 + args.lift_duration
        ):
            parser.error("pre-release carry must start after lift end")
        if args.base_release_posture_blend_s < 0.0:
            parser.error("--base-release-posture-blend-s must be nonnegative")
        if args.pre_release_posture_blend_s < 0.0:
            parser.error("--pre-release-posture-blend-s must be nonnegative")
        if (
            (
                args.base_release_posture_blend_s > 0.0
                or args.pre_release_posture_blend_s > 0.0
            )
            and not args.direct_fixed_posture_pd
        ):
            parser.error(
                "posture blending requires "
                "--direct-fixed-posture-pd"
            )
        if (
            args.base_release_time_s - args.pre_release_posture_blend_s
            < 3.0 + args.lift_duration
        ):
            parser.error("pre-release posture blend must start after lift end")
    elif args.walk_distance_m > 0.0:
        parser.error("--walk-distance-m requires --base-release-time-s")
    if (
        args.stable_stance_reference_run is not None
        and args.base_release_time_s is None
    ):
        parser.error(
            "--stable-stance-reference-run requires --base-release-time-s"
        )
    if args.duration is None:
        args.duration = (
            18.0
            if args.contact_aware_placement
            else 14.0
            if args.full_pick_place
            else 7.0
        )
    if args.output.exists():
        raise RuntimeError(f"output already exists: {args.output}")
    args.output.mkdir(parents=True)

    stable_stance_reference = None
    stable_stance_model = None
    stable_stance_qpos = None
    stabilized_base_position = None
    stabilized_base_quaternion = None
    if args.stable_stance_reference_run is not None:
        stable_stance_model_path = args.stable_stance_reference_run / "MODEL.xml"
        stable_stance_trajectory_path = (
            args.stable_stance_reference_run / "ROBOT_VISUAL_TRAJECTORY.npz"
        )
        stable_stance_model = mujoco.MjModel.from_xml_path(
            str(stable_stance_model_path)
        )
        stable_stance_trajectory = np.load(stable_stance_trajectory_path)
        stable_stance_index = int(
            np.argmin(
                np.abs(
                    stable_stance_trajectory["times"]
                    - args.stable_stance_reference_time_s
                )
            )
        )
        stable_stance_qpos = stable_stance_trajectory["qpos"][
            stable_stance_index
        ].copy()
        target_base_yaw = -0.5 * math.pi
        yaw_delta = target_base_yaw - base_yaw(stable_stance_qpos)
        stable_quaternion_wxyz = stable_stance_qpos[3:7]
        stable_rotation = Rotation.from_quat(
            [
                stable_quaternion_wxyz[1],
                stable_quaternion_wxyz[2],
                stable_quaternion_wxyz[3],
                stable_quaternion_wxyz[0],
            ]
        ).as_matrix()
        transformed_rotation = (
            Rotation.from_euler("z", yaw_delta).as_matrix() @ stable_rotation
        )
        transformed_quaternion_xyzw = Rotation.from_matrix(
            transformed_rotation
        ).as_quat()
        stabilized_base_position = np.array(
            [1.68, 0.85, stable_stance_qpos[2]], dtype=float
        )
        stabilized_base_quaternion = transformed_quaternion_xyzw[
            [3, 0, 1, 2]
        ]
        stable_stance_reference = {
            "run": str(args.stable_stance_reference_run),
            "model": str(stable_stance_model_path),
            "model_sha256": sha256(stable_stance_model_path),
            "trajectory": str(stable_stance_trajectory_path),
            "trajectory_sha256": sha256(stable_stance_trajectory_path),
            "requested_time_s": args.stable_stance_reference_time_s,
            "source_frame_index": stable_stance_index,
            "source_time_s": float(
                stable_stance_trajectory["times"][stable_stance_index]
            ),
            "transformed_base_position_m": stabilized_base_position.tolist(),
            "transformed_base_quaternion_wxyz": (
                stabilized_base_quaternion.tolist()
            ),
        }

    mug_initial_position = np.array([1.48, 0.31, 0.9553], dtype=float)
    model_xml = build_dynamic_model(
        args.output,
        mug_position=mug_initial_position,
        mug_mass=args.mug_mass,
        mug_radius=args.mug_radius,
        mug_half_height=args.mug_half_height,
        mug_friction=args.mug_friction,
        stabilize_robot_base=args.stabilize_robot_base,
        stabilized_base_position=stabilized_base_position,
        stabilized_base_quaternion=stabilized_base_quaternion,
    )
    run_module, adapter = install_controller_adapter(args.output, model_xml)
    write_json(args.output / "ADAPTER_SUMMARY.json", adapter)

    model = mujoco.MjModel.from_xml_path(str(model_xml))
    model.opt.timestep = 0.0025
    mujoco.mj_saveModel(model, str(args.output / "MODEL.mjb"))
    data = mujoco.MjData(model)
    source_model = mujoco.MjModel.from_xml_path(str(SOURCE_MODEL))
    source_trajectory = np.load(SOURCE_VISUAL_TRAJECTORY)
    source_qpos = source_trajectory["qpos"]

    # The v3 frame indices are fixed by its documented 20 Hz phase schedule.
    # Frame 60 is the open-hand grasp pose.  Frame 74 has the same arm pose
    # but already contains the visual demo's partly closed fingers and would
    # inject an impulse into the free mug at t=0.
    grasp_qpos = source_qpos[60].copy()
    lift_qpos = source_qpos[96]
    carry_qpos = source_qpos[120]
    place_qpos = source_qpos[142]
    if stable_stance_qpos is not None:
        task_joint_fragments = (
            "right_shoulder_",
            "right_elbow_",
            "right_wrist_",
            "hand_",
        )
        for stable_joint_id in range(stable_stance_model.njnt):
            name = mujoco.mj_id2name(
                stable_stance_model,
                mujoco.mjtObj.mjOBJ_JOINT,
                stable_joint_id,
            )
            if not name or any(fragment in name for fragment in task_joint_fragments):
                continue
            joint_type = int(stable_stance_model.jnt_type[stable_joint_id])
            if joint_type == mujoco.mjtJoint.mjJNT_FREE:
                continue
            target_joint_id = mujoco.mj_name2id(
                source_model, mujoco.mjtObj.mjOBJ_JOINT, name
            )
            if target_joint_id < 0:
                continue
            width = qpos_width(joint_type)
            stable_address = int(
                stable_stance_model.jnt_qposadr[stable_joint_id]
            )
            target_address = int(source_model.jnt_qposadr[target_joint_id])
            grasp_qpos[target_address : target_address + width] = (
                stable_stance_qpos[stable_address : stable_address + width]
            )
        grasp_qpos[:3] = stabilized_base_position
        grasp_qpos[3:7] = stabilized_base_quaternion
    data.qpos[:] = model.qpos0
    copy_joint_state_by_name(source_model, grasp_qpos, model, data.qpos)
    mug_joint_id = mujoco.mj_name2id(
        model, mujoco.mjtObj.mjOBJ_JOINT, MUG_FREEJOINT
    )
    mug_qpos_address = int(model.jnt_qposadr[mug_joint_id])
    data.qpos[mug_qpos_address : mug_qpos_address + 3] = mug_initial_position
    data.qpos[mug_qpos_address + 3 : mug_qpos_address + 7] = [1.0, 0.0, 0.0, 0.0]
    data.qvel[:] = 0.0
    data.ctrl[:] = 0.0
    mujoco.mj_forward(model, data)

    config = json.loads((SOURCE / "model_config.json").read_text())
    policies = [
        run_module.ONNXPolicy(str(SOURCE / f"{name}.onnx"))
        for name in ("walker", "croucher", "rotator")
    ]
    controller = run_module.G1Controller(model, data, *policies, config)
    controller.lin_vel_x = 0.0
    controller.lin_vel_y = 0.0
    controller.ang_vel_z = 0.0

    fixed_body_target = controller.default_joint_pos.copy()
    for target_index, name in enumerate(controller.joint_names):
        model_joint_id = mujoco.mj_name2id(
            model, mujoco.mjtObj.mjOBJ_JOINT, name
        )
        if model_joint_id >= 0:
            model_address = int(model.jnt_qposadr[model_joint_id])
            fixed_body_target[target_index] = data.qpos[model_address]

    arm_addresses = joint_addresses(model, ARM_NAMES)
    arm_joint_ids = np.asarray([model.joint(name).id for name in ARM_NAMES])
    arm_lower = model.jnt_range[arm_joint_ids, 0].copy()
    arm_upper = model.jnt_range[arm_joint_ids, 1].copy()
    arm_lower[3] = max(arm_lower[3], 0.10)
    finger_addresses = joint_addresses(model, FINGER_NAMES)
    finger_actuators = actuator_ids(model, FINGER_NAMES)
    grasp_arm = grasp_qpos[
        joint_addresses(source_model, ARM_NAMES)
    ].astype(float)
    lift_arm = lift_qpos[joint_addresses(source_model, ARM_NAMES)].astype(float)
    carry_arm = carry_qpos[joint_addresses(source_model, ARM_NAMES)].astype(float)
    place_arm = place_qpos[joint_addresses(source_model, ARM_NAMES)].astype(float)
    if args.lift_height != 0.14:
        fraction = args.lift_height / 0.14
        lift_arm = grasp_arm + fraction * (lift_arm - grasp_arm)
    open_fingers = grasp_qpos[
        joint_addresses(source_model, FINGER_NAMES)
    ].astype(float)
    fully_closed = np.array(
        [0.80, -0.90, -1.50, 1.40, 1.50, 1.40, 1.50], dtype=float
    )
    # The v3 geometry audit found a shallow opposing thumb/index pinch at
    # these per-joint fractions.  A uniform full-hand closure first contacts
    # the index/middle finger, pushes the unrestrained mug away, and only then
    # brings in the thumb.  Preserve simultaneous opposition and let the
    # position actuator's tracking error generate grasp force.
    closure_fraction = np.array(
        [
            args.thumb_close_fraction,
            args.thumb_close_fraction,
            args.thumb_close_fraction,
            args.index_close_fraction,
            args.index_close_fraction,
            args.middle_close_fraction,
            args.middle_close_fraction,
        ]
    )
    limits = np.asarray(
        [model.jnt_range[model.joint(name).id] for name in FINGER_NAMES]
    )
    closed_fingers = (
        np.asarray(args.closed_finger_targets_rad, dtype=float)
        if args.closed_finger_targets_rad is not None
        else open_fingers
        + args.close_scale * closure_fraction * (fully_closed - open_fingers)
    )
    closed_fingers = np.clip(closed_fingers, limits[:, 0], limits[:, 1])
    controller.frozen_arm_pos = grasp_arm.astype(np.float32)

    source_grasp_palm_position = source_trajectory["right_palm_positions"][60]
    source_grasp_palm_matrix = source_trajectory["right_palm_matrices"][60]
    source_lift_palm_position = source_trajectory["right_palm_positions"][96]
    source_lift_palm_matrix = source_trajectory["right_palm_matrices"][96]
    source_carry_palm_position = source_trajectory["right_palm_positions"][120]
    source_carry_palm_matrix = source_trajectory["right_palm_matrices"][120]
    source_place_palm_position = source_trajectory["right_palm_positions"][142]
    source_place_palm_matrix = source_trajectory["right_palm_matrices"][142]
    if args.full_pick_place:
        # The visual baseline used 15 cm, but the translated dynamic arm
        # enters a poorly tracked near-singular posture in the last few
        # centimetres.  Keep this relaxed physics demo inside the empirically
        # stable workspace while retaining a clearly measurable transport.
        transport_fraction = args.transport_distance / 0.15
        source_carry_palm_position = source_lift_palm_position + np.array(
            [args.transport_distance, 0.0, 0.0]
        )
        source_place_palm_position = source_grasp_palm_position + np.array(
            [args.transport_distance, 0.0, 0.0]
        )
        carry_arm = lift_arm + transport_fraction * (carry_arm - lift_arm)
        place_arm = grasp_arm + transport_fraction * (place_arm - grasp_arm)
    if args.lift_height != 0.14:
        source_lift_palm_position = source_grasp_palm_position + (
            args.lift_height / 0.14
        ) * (source_lift_palm_position - source_grasp_palm_position)

    enveloping_reference = None
    if args.enveloping_reference_run is not None:
        if args.full_pick_place:
            parser.error("--enveloping-reference-run is currently lift-hold only")
        reference_trajectory_path = (
            args.enveloping_reference_run / "ROBOT_CUP_PHYSICS_TRAJECTORY.npz"
        )
        reference_trajectory = np.load(reference_trajectory_path)
        reference_index = int(
            np.argmin(
                np.abs(
                    reference_trajectory["times"]
                    - args.enveloping_reference_time_s
                )
            )
        )
        reference_cup_position = reference_trajectory["cup_positions"][
            reference_index
        ]
        reference_cup_matrix = reference_trajectory["cup_matrices"][
            reference_index
        ]
        relative_palm_position = reference_cup_matrix.T @ (
            reference_trajectory["right_palm_positions"][reference_index]
            - reference_cup_position
        )
        relative_palm_matrix = reference_cup_matrix.T @ (
            reference_trajectory["right_palm_matrices"][reference_index]
        )
        source_grasp_palm_position = mug_initial_position + relative_palm_position
        source_grasp_palm_matrix = relative_palm_matrix
        source_lift_palm_position = source_grasp_palm_position + np.array(
            [args.actual_lift_offset_x, args.actual_lift_offset_y, args.lift_height]
        )
        source_lift_palm_matrix = relative_palm_matrix
        enveloping_reference = {
            "run": str(args.enveloping_reference_run),
            "trajectory": str(reference_trajectory_path),
            "trajectory_sha256": sha256(reference_trajectory_path),
            "requested_time_s": args.enveloping_reference_time_s,
            "source_frame_index": reference_index,
            "source_time_s": float(reference_trajectory["times"][reference_index]),
            "relative_palm_position_in_cup_m": relative_palm_position.tolist(),
            "relative_palm_matrix_in_cup": relative_palm_matrix.tolist(),
        }

    grasp_azimuth_rotation = Rotation.from_euler(
        "z", args.grasp_azimuth_offset_deg, degrees=True
    ).as_matrix()
    grasp_cup_center = mug_initial_position.copy()
    lift_cup_center = mug_initial_position + np.array(
        [0.0, 0.0, args.lift_height]
    )
    carry_cup_center = lift_cup_center + np.array(
        [args.transport_distance if args.full_pick_place else 0.0, 0.0, 0.0]
    )
    place_cup_center = mug_initial_position + np.array(
        [args.transport_distance if args.full_pick_place else 0.0, 0.0, 0.0]
    )
    if args.grasp_azimuth_offset_deg != 0.0:
        def orbit_palm(position: np.ndarray, center: np.ndarray) -> np.ndarray:
            return center + grasp_azimuth_rotation @ (position - center)

        source_grasp_palm_position = orbit_palm(
            source_grasp_palm_position, grasp_cup_center
        )
        source_lift_palm_position = orbit_palm(
            source_lift_palm_position, lift_cup_center
        )
        source_carry_palm_position = orbit_palm(
            source_carry_palm_position, carry_cup_center
        )
        source_place_palm_position = orbit_palm(
            source_place_palm_position, place_cup_center
        )
        source_grasp_palm_matrix = (
            grasp_azimuth_rotation @ source_grasp_palm_matrix
        )
        source_lift_palm_matrix = grasp_azimuth_rotation @ source_lift_palm_matrix
        source_carry_palm_matrix = (
            grasp_azimuth_rotation @ source_carry_palm_matrix
        )
        source_place_palm_matrix = (
            grasp_azimuth_rotation @ source_place_palm_matrix
        )

    if args.grasp_radial_inset_m != 0.0:
        def inset_palm(position: np.ndarray, center: np.ndarray) -> np.ndarray:
            result = position.copy()
            radial = result[:2] - center[:2]
            radial_norm = float(np.linalg.norm(radial))
            if radial_norm <= 1.0e-9:
                raise RuntimeError("cannot radially inset a palm on the mug axis")
            result[:2] -= args.grasp_radial_inset_m * radial / radial_norm
            return result

        source_grasp_palm_position = inset_palm(
            source_grasp_palm_position, grasp_cup_center
        )
        source_lift_palm_position = inset_palm(
            source_lift_palm_position, lift_cup_center
        )
        source_carry_palm_position = inset_palm(
            source_carry_palm_position, carry_cup_center
        )
        source_place_palm_position = inset_palm(
            source_place_palm_position, place_cup_center
        )

    if args.grasp_vertical_offset_m != 0.0:
        for position in (
            source_grasp_palm_position,
            source_lift_palm_position,
            source_carry_palm_position,
            source_place_palm_position,
        ):
            position[2] += args.grasp_vertical_offset_m

    visual_ids, visual_rows = visual_manifest(model)
    visual_ids = np.asarray(visual_ids, dtype=int)
    write_json(args.output / "ROBOT_VISUALS.json", visual_rows)
    mug_body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, MUG_BODY)
    mug_geom_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, MUG_PROXY_GEOM)
    palm_body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, PALM_BODY)
    torso_body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, TORSO_BODY)
    if torso_body_id < 0:
        raise RuntimeError(f"missing robot torso body: {TORSO_BODY}")
    base_weld_id = (
        mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_EQUALITY, BASE_WELD)
        if args.base_release_time_s is not None
        else -1
    )
    if args.base_release_time_s is not None and base_weld_id < 0:
        raise RuntimeError(f"missing base stabilization equality: {BASE_WELD}")
    arm_dof_addresses = np.asarray(
        [model.jnt_dofadr[model.joint(name).id] for name in ARM_NAMES], dtype=int
    )
    arm_actuator_ids = actuator_ids(model, ARM_NAMES)
    arm_pd_kp = np.array([80.0, 80.0, 60.0, 60.0, 30.0, 30.0, 20.0])
    arm_pd_kd = np.array([4.0, 4.0, 3.0, 3.0, 2.0, 2.0, 1.5])
    fixed_posture_names = tuple(
        name for name in controller.joint_names if name not in ARM_NAMES
    )
    fixed_posture_indices = np.asarray(
        [
            index
            for index, name in enumerate(controller.joint_names)
            if name not in ARM_NAMES
        ],
        dtype=int,
    )
    fixed_posture_addresses = joint_addresses(model, fixed_posture_names)
    fixed_posture_dof_addresses = np.asarray(
        [model.jnt_dofadr[model.joint(name).id] for name in fixed_posture_names],
        dtype=int,
    )
    fixed_posture_actuator_ids = actuator_ids(model, fixed_posture_names)
    fixed_posture_targets = fixed_body_target[fixed_posture_indices].astype(float)
    fixed_posture_kp = np.asarray(
        [80.0 if name.startswith("waist_") else 60.0 for name in fixed_posture_names]
    )
    fixed_posture_kd = np.asarray(
        [4.0 if name.startswith("waist_") else 3.0 for name in fixed_posture_names]
    )
    jacobian_position = np.zeros((3, model.nv), dtype=float)
    jacobian_rotation = np.zeros((3, model.nv), dtype=float)
    ik_data = mujoco.MjData(model)
    grasp_azimuth_preflight = []
    if (
        args.grasp_azimuth_offset_deg != 0.0
        or args.grasp_radial_inset_m != 0.0
        or args.enveloping_reference_run is not None
    ):
        preflight_qpos = data.qpos.copy()
        rotated_targets = [
            (
                "grasp",
                source_grasp_palm_position,
                source_grasp_palm_matrix,
                grasp_arm,
            ),
            (
                "lift",
                source_lift_palm_position,
                source_lift_palm_matrix,
                lift_arm,
            ),
        ]
        if args.full_pick_place:
            rotated_targets.extend(
                [
                    (
                        "carry",
                        source_carry_palm_position,
                        source_carry_palm_matrix,
                        carry_arm,
                    ),
                    (
                        "place",
                        source_place_palm_position,
                        source_place_palm_matrix,
                        place_arm,
                    ),
                ]
            )
        solved_keyframes = []
        solve_seed = grasp_arm.copy()
        for name, position, matrix, posture_reference in rotated_targets:
            solution, position_error, orientation_error = solve_palm_pose(
                model,
                ik_data,
                preflight_qpos,
                arm_addresses,
                arm_lower,
                arm_upper,
                palm_body_id,
                position,
                matrix,
                solve_seed,
                posture_reference,
            )
            solved_keyframes.append(solution)
            solve_seed = solution
            grasp_azimuth_preflight.append(
                {
                    "keyframe": name,
                    "position_error_m": position_error,
                    "orientation_error_deg": math.degrees(orientation_error),
                    "arm_rad": solution.tolist(),
                }
            )
        grasp_arm, lift_arm = solved_keyframes[:2]
        if args.full_pick_place:
            carry_arm, place_arm = solved_keyframes[2:]
        data.qpos[arm_addresses] = grasp_arm
        data.qvel[:] = 0.0
        mujoco.mj_forward(model, data)
        fixed_body_target[controller.right_arm_indices] = grasp_arm.astype(np.float32)
        controller.frozen_arm_pos = grasp_arm.astype(np.float32)
    ik_seed = grasp_arm.copy()
    ik_position_errors = []
    ik_orientation_errors = []

    if args.full_pick_place:
        phases = {
            "settle_start": 0.0,
            "close_start": 1.0,
            "close_end": 2.2,
            "lift_start": 3.0,
            "lift_end": 5.0,
            "carry_start": 5.8,
            "carry_end": 7.8,
            "lower_start": 8.2,
            "lower_end": 10.2,
            "release_start": 10.8,
            "release_end": 11.8,
            "retract_start": 12.5 if args.contact_aware_placement else 11.8,
            "clearance_end": 14.5 if args.contact_aware_placement else 11.8,
            "retract_end": 16.5 if args.contact_aware_placement else 13.5,
            "task_end": args.duration,
        }
    else:
        phases = {
            "settle_start": 0.0,
            "close_start": 1.0,
            "close_end": 2.2,
            "lift_start": 3.0,
            "lift_end": 3.0 + args.lift_duration,
            "hold_end": args.duration,
        }
    dt = float(model.opt.timestep)
    policy_every = 8
    video_every = 20
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
    mug_pose_writes_after_initialization = 0
    fell = False
    fall_hits = 0
    max_mug_penetration = 0.0
    max_hand_normal_force = 0.0
    max_hand_tangential_force = 0.0
    hand_contact_steps = 0
    support_contact_steps = 0
    lifted_hand_contact_steps = 0
    lifted_support_contact_steps = 0
    hand_contact_bodies: set[str] = set()
    support_contact_geoms: set[str] = set()
    max_palm_position_error = 0.0
    max_palm_orientation_error = 0.0
    arm_command = grasp_arm.copy()
    support_contact_run_steps = 0
    support_stop_triggered = False
    support_stop_time = None
    support_stop_palm_position = None
    support_stop_palm_matrix = None
    support_stop_arm = None
    no_hand_contact_run_steps = 0
    max_pre_retract_no_hand_contact_run_steps = 0
    post_retract_hand_contact_steps = 0
    post_retract_first_hand_contact_time = None
    post_retract_max_hand_normal_force = 0.0
    disturbance_force_impulse = 0.0
    max_disturbance_force = 0.0
    disturbance_steps = 0
    disturbance_hand_contact_steps = 0
    disturbance_support_contact_steps = 0
    disturbance_max_hand_normal_force = 0.0
    lift_anchor_time = None
    lift_anchor_palm_position = None
    lift_anchor_palm_matrix = None
    lift_anchor_arm = None
    actual_lift_offset = np.array(
        [args.actual_lift_offset_x, args.actual_lift_offset_y, args.lift_height],
        dtype=float,
    )
    pre_release_carry_offset = np.array(
        [
            args.pre_release_carry_offset_x,
            args.pre_release_carry_offset_y,
            0.0,
        ],
        dtype=float,
    )
    base_released = False
    base_release_actual_time = None
    base_release_base_position = None
    base_release_palm_position = None
    base_release_palm_matrix = None
    base_release_torso_palm_position = None
    base_release_torso_palm_matrix = None
    base_release_arm = None
    walk_start_scheduled_time = None
    walk_start_actual_time = None
    walk_origin_base_xy = None
    walk_world_direction = None
    walk_completed = False
    walk_complete_time = None
    max_walk_progress = 0.0
    walk_completion_tolerance_m = (
        min(0.005, 0.25 * args.walk_stop_ramp_distance_m)
        if args.walk_stop_ramp_distance_m > 0.0
        else 0.0
    )
    body_axis_vectors = {
        "forward": np.array([1.0, 0.0]),
        "backward": np.array([-1.0, 0.0]),
        "left": np.array([0.0, 1.0]),
        "right": np.array([0.0, -1.0]),
    }

    total_steps = int(round(args.duration / dt))
    for step in range(total_steps):
        now = float(data.time)
        phase = phase_at(now, phases)
        if (
            args.base_release_time_s is not None
            and not base_released
            and now >= args.base_release_time_s
        ):
            # Release the temporary manipulation fixture without resetting any
            # dynamic state.  From this exact grasped state onward the balance
            # policy owns the legs and torso while the task arm remains under
            # the same direct gravity-compensated controller.
            data.eq_active[base_weld_id] = 0
            base_released = True
            base_release_actual_time = now
            base_release_base_position = data.qpos[:3].copy()
            base_release_palm_position = data.xpos[palm_body_id].copy()
            base_release_palm_matrix = data.xmat[palm_body_id].reshape(3, 3).copy()
            release_torso_position = data.xpos[torso_body_id].copy()
            release_torso_matrix = data.xmat[torso_body_id].reshape(3, 3).copy()
            base_release_torso_palm_position = release_torso_matrix.T @ (
                base_release_palm_position - release_torso_position
            )
            base_release_torso_palm_matrix = (
                release_torso_matrix.T @ base_release_palm_matrix
            )
            base_release_arm = data.qpos[arm_addresses].copy()
            ik_seed = base_release_arm.copy()
            walk_start_scheduled_time = now + args.free_base_static_hold_s
            release_yaw = base_yaw(data.qpos)
            body_to_world = Rotation.from_euler("z", release_yaw).as_matrix()[
                :2, :2
            ]
            walk_world_direction = (
                body_to_world @ body_axis_vectors[args.walk_body_axis]
            )
            walk_world_direction /= np.linalg.norm(walk_world_direction)

        if (
            base_released
            and args.walk_distance_m > 0.0
            and walk_origin_base_xy is None
            and now >= walk_start_scheduled_time
        ):
            walk_start_actual_time = now
            walk_origin_base_xy = data.qpos[:2].copy()

        if not base_released:
            locomotion_phase = "fixed_base"
        elif args.walk_distance_m <= 0.0 or walk_origin_base_xy is None:
            locomotion_phase = "free_base_static_hold"
        elif not walk_completed:
            locomotion_phase = "walk"
        else:
            locomotion_phase = "post_walk_hold"
        pre_release_transition_active = bool(
            args.base_release_time_s is not None
            and not base_released
            and args.pre_release_posture_blend_s > 0.0
            and now
            >= args.base_release_time_s - args.pre_release_posture_blend_s
        )
        pre_release_carry_active = bool(
            args.base_release_time_s is not None
            and not base_released
            and np.linalg.norm(pre_release_carry_offset[:2]) > 0.0
            and now
            >= args.base_release_time_s - args.pre_release_carry_duration_s
        )
        if (
            args.actual_state_lift_anchor
            and lift_anchor_time is None
            and now >= phases["lift_start"]
        ):
            lift_anchor_time = now
            lift_anchor_palm_position = data.xpos[palm_body_id].copy()
            lift_anchor_palm_matrix = data.xmat[palm_body_id].reshape(3, 3).copy()
            lift_anchor_arm = data.qpos[arm_addresses].copy()
            ik_seed = lift_anchor_arm.copy()
        if now < phases["close_start"]:
            close_alpha = 0.0
        elif now < phases["close_end"]:
            close_alpha = (now - phases["close_start"]) / (
                phases["close_end"] - phases["close_start"]
            )
        else:
            close_alpha = 1.0
        if args.full_pick_place and now >= phases["release_start"]:
            release_alpha = (now - phases["release_start"]) / (
                phases["release_end"] - phases["release_start"]
            )
            finger_target = interpolate(
                closed_fingers, open_fingers, release_alpha
            )
        else:
            finger_target = interpolate(open_fingers, closed_fingers, close_alpha)
            close_duration = phases["close_end"] - phases["close_start"]
            if args.thumb_close_completion_advance > 0.0:
                thumb_close_alpha = (now - phases["close_start"]) / (
                    close_duration - args.thumb_close_completion_advance
                )
                finger_target[0:3] = interpolate(
                    open_fingers[0:3],
                    closed_fingers[0:3],
                    thumb_close_alpha,
                )
            if args.middle_close_completion_advance > 0.0:
                middle_close_alpha = (now - phases["close_start"]) / (
                    close_duration - args.middle_close_completion_advance
                )
                finger_target[5:7] = interpolate(
                    open_fingers[5:7],
                    closed_fingers[5:7],
                    middle_close_alpha,
                )
            if args.index_close_delay > 0.0:
                index_close_start = (
                    phases["close_start"] + args.index_close_delay
                )
                index_close_alpha = (now - index_close_start) / (
                    phases["close_end"] - index_close_start
                )
                finger_target[3:5] = interpolate(
                    open_fingers[3:5],
                    closed_fingers[3:5],
                    index_close_alpha,
                )
        index_tighten_start_time = (
            args.base_release_time_s - args.index_tighten_lead_s
            if args.base_release_time_s is not None
            else math.inf
        )
        if (
            now >= index_tighten_start_time
            and args.post_release_index_tighten_rad > 0.0
        ):
            finger_tighten_alpha = smoothstep(
                (now - index_tighten_start_time)
                / args.post_release_finger_ramp_s
            )
            finger_target[3:5] += (
                finger_tighten_alpha * args.post_release_index_tighten_rad
            )
            finger_target = np.clip(
                finger_target, limits[:, 0], limits[:, 1]
            )

        if now < phases["lift_start"]:
            arm_target = grasp_arm
            desired_palm_position = source_grasp_palm_position
            desired_palm_matrix = source_grasp_palm_matrix
        elif now < phases["lift_end"]:
            lift_alpha = (now - phases["lift_start"]) / (
                phases["lift_end"] - phases["lift_start"]
            )
            if args.actual_state_lift_anchor:
                arm_target = lift_anchor_arm
                desired_palm_position = interpolate(
                    lift_anchor_palm_position,
                    lift_anchor_palm_position + actual_lift_offset,
                    lift_alpha,
                )
                desired_palm_matrix = lift_anchor_palm_matrix
            else:
                arm_target = interpolate(
                    grasp_arm,
                    lift_arm,
                    lift_alpha,
                )
                desired_palm_position = interpolate(
                    source_grasp_palm_position,
                    source_lift_palm_position,
                    lift_alpha,
                )
                desired_palm_matrix = interpolate_rotation(
                    source_grasp_palm_matrix,
                    source_lift_palm_matrix,
                    lift_alpha,
                )
        elif args.full_pick_place and now < phases["carry_start"]:
            arm_target = lift_arm
            desired_palm_position = source_lift_palm_position
            desired_palm_matrix = source_lift_palm_matrix
        elif args.full_pick_place and now < phases["carry_end"]:
            carry_alpha = (now - phases["carry_start"]) / (
                phases["carry_end"] - phases["carry_start"]
            )
            arm_target = interpolate(lift_arm, carry_arm, carry_alpha)
            desired_palm_position = interpolate(
                source_lift_palm_position,
                source_carry_palm_position,
                carry_alpha,
            )
            desired_palm_matrix = interpolate_rotation(
                source_lift_palm_matrix, source_carry_palm_matrix, carry_alpha
            )
        elif args.full_pick_place and now < phases["lower_start"]:
            arm_target = carry_arm
            desired_palm_position = source_carry_palm_position
            desired_palm_matrix = source_carry_palm_matrix
        elif (
            args.full_pick_place
            and args.contact_aware_placement
            and support_stop_triggered
            and now < phases["retract_start"]
        ):
            arm_target = support_stop_arm
            desired_palm_position = support_stop_palm_position
            desired_palm_matrix = support_stop_palm_matrix
        elif args.full_pick_place and now < phases["lower_end"]:
            lower_alpha = (now - phases["lower_start"]) / (
                phases["lower_end"] - phases["lower_start"]
            )
            arm_target = interpolate(carry_arm, place_arm, lower_alpha)
            desired_palm_position = interpolate(
                source_carry_palm_position,
                source_place_palm_position,
                lower_alpha,
            )
            desired_palm_matrix = interpolate_rotation(
                source_carry_palm_matrix, source_place_palm_matrix, lower_alpha
            )
        elif args.full_pick_place and now < phases["release_end"]:
            arm_target = place_arm
            desired_palm_position = source_place_palm_position
            desired_palm_matrix = source_place_palm_matrix
        elif args.full_pick_place and args.contact_aware_placement:
            retract_origin = (
                support_stop_palm_position
                if support_stop_palm_position is not None
                else source_place_palm_position
            )
            retract_matrix = (
                support_stop_palm_matrix
                if support_stop_palm_matrix is not None
                else source_place_palm_matrix
            )
            retract_arm = (
                support_stop_arm if support_stop_arm is not None else place_arm
            )
            # This diagonal was selected from the measured release pose by a
            # fixed-wrist 6D reachability scan.  The former -x/+y then +z
            # route crossed an orientation singularity and made the arm loop.
            retract_position = retract_origin + np.array([-0.10, 0.04, 0.04])
            arm_target = retract_arm
            if now < phases["retract_start"]:
                desired_palm_position = retract_origin
            else:
                retract_alpha = (now - phases["retract_start"]) / (
                    phases["retract_end"] - phases["retract_start"]
                )
                desired_palm_position = interpolate(
                    retract_origin, retract_position, retract_alpha
                )
            desired_palm_matrix = retract_matrix
        elif args.full_pick_place:
            retract_alpha = (now - phases["release_end"]) / (
                phases["retract_end"] - phases["release_end"]
            )
            retract_position = source_place_palm_position + np.array(
                [0.0, 0.12, 0.10]
            )
            arm_target = place_arm
            desired_palm_position = interpolate(
                source_place_palm_position, retract_position, retract_alpha
            )
            desired_palm_matrix = source_place_palm_matrix
        else:
            if args.actual_state_lift_anchor:
                arm_target = lift_anchor_arm
                desired_palm_position = (
                    lift_anchor_palm_position + actual_lift_offset
                )
                desired_palm_matrix = lift_anchor_palm_matrix
            else:
                arm_target = lift_arm
                desired_palm_position = source_lift_palm_position
                desired_palm_matrix = source_lift_palm_matrix

        if pre_release_carry_active:
            carry_alpha = smoothstep(
                (
                    now
                    - (
                        args.base_release_time_s
                        - args.pre_release_carry_duration_s
                    )
                )
                / args.pre_release_carry_duration_s
            )
            desired_palm_position = (
                desired_palm_position
                + carry_alpha * pre_release_carry_offset
            )

        if base_released:
            if args.free_base_carry_frame in {"torso", "torso-height"}:
                torso_position = data.xpos[torso_body_id]
                torso_matrix = data.xmat[torso_body_id].reshape(3, 3)
                desired_palm_position = (
                    torso_position
                    + torso_matrix @ base_release_torso_palm_position
                )
                if args.free_base_carry_frame == "torso-height":
                    desired_palm_position[2] = base_release_palm_position[2]
                desired_palm_matrix = (
                    torso_matrix @ base_release_torso_palm_matrix
                )
            else:
                # Follow planar translation while compensating base bob and
                # attitude to keep the cup upright in world coordinates.
                desired_palm_position = base_release_palm_position.copy()
                desired_palm_position[:2] += (
                    data.qpos[:2] - base_release_base_position[:2]
                )
                desired_palm_matrix = base_release_palm_matrix
            arm_target = base_release_arm

        if step % policy_every == 0:
            previous_arm_command = arm_command.copy()
            if base_released:
                if locomotion_phase == "walk":
                    start_alpha = smoothstep(
                        (now - walk_start_actual_time) / args.walk_command_ramp_s
                    )
                    stop_alpha = 1.0
                    if args.walk_stop_ramp_distance_m > 0.0:
                        current_walk_progress = float(
                            np.dot(
                                data.qpos[:2] - walk_origin_base_xy,
                                walk_world_direction,
                            )
                        )
                        remaining_distance = max(
                            0.0,
                            args.walk_distance_m
                            - walk_completion_tolerance_m
                            - current_walk_progress,
                        )
                        stop_alpha = smoothstep(
                            remaining_distance
                            / args.walk_stop_ramp_distance_m
                        )
                    command_alpha = min(start_alpha, stop_alpha)
                    body_command = (
                        body_axis_vectors[args.walk_body_axis]
                        * args.walk_speed_mps
                        * command_alpha
                    )
                    controller.lin_vel_x = float(body_command[0])
                    controller.lin_vel_y = float(body_command[1])
                else:
                    controller.lin_vel_x = 0.0
                    controller.lin_vel_y = 0.0
                controller.ang_vel_z = 0.0
            walker_target = (
                controller.step()
                if base_released
                or pre_release_transition_active
                or args.warm_walker_before_base_release
                else None
            )
            # A fixed-base manipulation baseline must also hold the torso and
            # non-task joints.  Continuing to run the free-standing balance
            # policy moves the shoulder frame and can make the same world-pose
            # IK target alternate between reachable and unreachable branches.
            target = (
                fixed_body_target.copy()
                if args.stabilize_robot_base
                and not args.keep_walker_with_stabilized_base
                and not base_released
                and not pre_release_transition_active
                else walker_target
                if walker_target is not None
                else controller.step()
            )
            if args.online_ik:
                try:
                    previous_ik_seed = ik_seed.copy()
                    solved_ik, ik_position_error, ik_orientation_error = solve_palm_pose(
                        model,
                        ik_data,
                        data.qpos.copy(),
                        arm_addresses,
                        arm_lower,
                        arm_upper,
                        palm_body_id,
                        desired_palm_position,
                        desired_palm_matrix,
                        ik_seed,
                        arm_target,
                    )
                    active_ik_max_joint_step = (
                        min(args.ik_max_joint_step, 0.03)
                        if args.contact_aware_placement
                        and now >= phases.get("retract_start", math.inf)
                        else args.ik_max_joint_step
                    )
                    ik_delta = solved_ik - previous_ik_seed
                    if (
                        args.contact_aware_placement
                        and now >= phases.get("retract_start", math.inf)
                    ):
                        ik_delta = scale_delta_preserving_direction(
                            ik_delta, active_ik_max_joint_step
                        )
                    else:
                        ik_delta = np.clip(
                            ik_delta,
                            -active_ik_max_joint_step,
                            active_ik_max_joint_step,
                        )
                    ik_seed = previous_ik_seed + ik_delta
                    arm_target = ik_seed
                    ik_position_errors.append(ik_position_error)
                    ik_orientation_errors.append(ik_orientation_error)
                except RuntimeError:
                    # Retain the preceding feasible seed.  The final report
                    # exposes the number of successful solves and tracking
                    # errors, so a missed solve cannot masquerade as success.
                    arm_target = ik_seed
            # A small outer-loop position correction compensates the measured
            # static sag of the translated arm controller while leaving the
            # target plant, torque limits and inner controller unchanged.
            actual_arm = data.qpos[arm_addresses]
            arm_command = arm_target + args.arm_tracking_gain * (
                arm_target - actual_arm
            )
            current_palm_position = data.xpos[palm_body_id]
            current_palm_matrix = data.xmat[palm_body_id].reshape(3, 3)
            position_error = desired_palm_position - current_palm_position
            orientation_error = Rotation.from_matrix(
                desired_palm_matrix @ current_palm_matrix.T
            ).as_rotvec()
            max_palm_position_error = max(
                max_palm_position_error, float(np.linalg.norm(position_error))
            )
            max_palm_orientation_error = max(
                max_palm_orientation_error, float(np.linalg.norm(orientation_error))
            )
            mujoco.mj_jacBody(
                model,
                data,
                jacobian_position,
                jacobian_rotation,
                palm_body_id,
            )
            # Position is weighted above orientation because retaining the
            # opposing pinch during vertical lift is the immediate causal
            # requirement.  Damped least squares avoids singular spikes.
            jacobian = np.vstack(
                [
                    5.0 * jacobian_position[:, arm_dof_addresses],
                    0.5 * jacobian_rotation[:, arm_dof_addresses],
                ]
            )
            pose_error = np.concatenate(
                [5.0 * position_error, 0.5 * orientation_error]
            )
            damping = 1.0e-3
            cartesian_correction = jacobian.T @ np.linalg.solve(
                jacobian @ jacobian.T
                + damping * np.eye(jacobian.shape[0]),
                pose_error,
            )
            active_cartesian_max_joint_correction = (
                min(args.cartesian_max_joint_correction, 0.03)
                if args.contact_aware_placement
                and now >= phases.get("retract_start", math.inf)
                else args.cartesian_max_joint_correction
            )
            cartesian_correction = args.cartesian_gain * cartesian_correction
            if (
                args.contact_aware_placement
                and now >= phases.get("retract_start", math.inf)
            ):
                cartesian_correction = scale_delta_preserving_direction(
                    cartesian_correction, active_cartesian_max_joint_correction
                )
            else:
                cartesian_correction = np.clip(
                    cartesian_correction,
                    -active_cartesian_max_joint_correction,
                    active_cartesian_max_joint_correction,
                )
            arm_command += cartesian_correction
            if (
                args.contact_aware_placement
                and now >= phases.get("retract_start", math.inf)
            ):
                arm_command = previous_arm_command + scale_delta_preserving_direction(
                    arm_command - previous_arm_command,
                    args.retract_max_joint_command_step,
                )
            arm_limits = np.asarray(
                [model.jnt_range[model.joint(name).id] for name in ARM_NAMES]
            )
            arm_command = np.clip(
                arm_command, arm_limits[:, 0], arm_limits[:, 1]
            )
            target[controller.right_arm_indices] = arm_command.astype(np.float32)
            controller.frozen_arm_pos = arm_command.astype(np.float32)

        controller.apply_pd_control(target)
        fixed_posture_blend_weight = (
            1.0
            - smoothstep(
                (
                    now
                    - (
                        args.base_release_time_s
                        - args.pre_release_posture_blend_s
                    )
                )
                / args.pre_release_posture_blend_s
            )
            if args.direct_fixed_posture_pd and pre_release_transition_active
            else 1.0
            if args.direct_fixed_posture_pd and not base_released
            else 1.0
            - smoothstep(
                (now - base_release_actual_time)
                / args.base_release_posture_blend_s
            )
            if args.direct_fixed_posture_pd
            and base_released
            and args.base_release_posture_blend_s > 0.0
            else 0.0
        )
        if fixed_posture_blend_weight > 0.0:
            posture_position = data.qpos[fixed_posture_addresses]
            posture_velocity = data.qvel[fixed_posture_dof_addresses]
            posture_torque = (
                fixed_posture_kp * (fixed_posture_targets - posture_position)
                - fixed_posture_kd * posture_velocity
                + data.qfrc_bias[fixed_posture_dof_addresses]
            )
            posture_torque = np.clip(
                posture_torque,
                model.actuator_ctrlrange[fixed_posture_actuator_ids, 0],
                model.actuator_ctrlrange[fixed_posture_actuator_ids, 1],
            )
            data.ctrl[fixed_posture_actuator_ids] = (
                fixed_posture_blend_weight * posture_torque
                + (1.0 - fixed_posture_blend_weight)
                * data.ctrl[fixed_posture_actuator_ids]
            )
        if args.direct_fixed_base_arm_pd or (
            args.direct_lift_arm_pd and now >= phases["lift_start"]
        ) or (
            args.direct_retract_arm_pd
            and now >= phases.get("retract_start", math.inf)
        ):
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
        data.ctrl[finger_actuators] = finger_target
        data.xfrc_applied[:] = 0.0
        applied_cup_force = 0.0
        if (
            args.cup_lateral_force_newtons > 0.0
            and args.cup_force_start <= now <= args.cup_force_end
        ):
            ramp_in = smoothstep(
                (now - args.cup_force_start) / max(args.cup_force_ramp, dt)
            )
            ramp_out = smoothstep(
                (args.cup_force_end - now) / max(args.cup_force_ramp, dt)
            )
            applied_cup_force = args.cup_lateral_force_newtons * min(
                ramp_in, ramp_out
            )
            data.xfrc_applied[mug_body_id, 0] = -applied_cup_force
        mujoco.mj_step(model, data)

        if walk_origin_base_xy is not None:
            walk_progress = float(
                np.dot(
                    data.qpos[:2] - walk_origin_base_xy,
                    walk_world_direction,
                )
            )
            max_walk_progress = max(max_walk_progress, walk_progress)
            if (
                not walk_completed
                and walk_progress
                >= args.walk_distance_m - walk_completion_tolerance_m
            ):
                walk_completed = True
                walk_complete_time = float(data.time)

        sample = contact_sample(model, data, mug_geom_id)
        if (
            args.contact_aware_placement
            and phase == "lower"
            and not support_stop_triggered
        ):
            support_contact_run_steps = (
                support_contact_run_steps + 1 if sample["support"] else 0
            )
            if support_contact_run_steps >= int(round(0.10 / dt)):
                support_stop_triggered = True
                support_stop_time = float(data.time)
                support_stop_palm_position = data.xpos[palm_body_id].copy()
                support_stop_palm_matrix = data.xmat[palm_body_id].reshape(3, 3).copy()
                support_stop_arm = data.qpos[arm_addresses].copy()
        if args.contact_aware_placement and now >= phases["release_end"]:
            if now < phases["retract_start"]:
                no_hand_contact_run_steps = (
                    0 if sample["hand"] else no_hand_contact_run_steps + 1
                )
                max_pre_retract_no_hand_contact_run_steps = max(
                    max_pre_retract_no_hand_contact_run_steps,
                    no_hand_contact_run_steps,
                )
            elif sample["hand"]:
                post_retract_hand_contact_steps += 1
                if post_retract_first_hand_contact_time is None:
                    post_retract_first_hand_contact_time = float(data.time)
                post_retract_max_hand_normal_force = max(
                    post_retract_max_hand_normal_force,
                    max(row["normal_force_N"] for row in sample["hand"]),
                )
        max_mug_penetration = max(
            max_mug_penetration, sample["max_mug_contact_penetration_m"]
        )
        if sample["hand"]:
            hand_contact_steps += 1
            if phase in {"lift", "hold", "hold_lift", "carry", "hold_carry", "lower"}:
                lifted_hand_contact_steps += 1
            for row in sample["hand"]:
                hand_contact_bodies.add(row["body"])
                max_hand_normal_force = max(
                    max_hand_normal_force, row["normal_force_N"]
                )
                max_hand_tangential_force = max(
                    max_hand_tangential_force, row["tangential_force_N"]
                )
        if sample["support"]:
            support_contact_steps += 1
            if phase in {"lift", "hold", "hold_lift", "carry", "hold_carry", "lower"}:
                lifted_support_contact_steps += 1
            support_contact_geoms.update(row["geom"] for row in sample["support"])
        if applied_cup_force > 0.0:
            disturbance_steps += 1
            disturbance_force_impulse += applied_cup_force * dt
            max_disturbance_force = max(
                max_disturbance_force, applied_cup_force
            )
            disturbance_hand_contact_steps += int(bool(sample["hand"]))
            disturbance_support_contact_steps += int(bool(sample["support"]))
            if sample["hand"]:
                disturbance_max_hand_normal_force = max(
                    disturbance_max_hand_normal_force,
                    max(row["normal_force_N"] for row in sample["hand"]),
                )

        base_quat = data.qpos[3:7]
        upright = 1.0 - 2.0 * (base_quat[1] ** 2 + base_quat[2] ** 2)
        fall_hits = fall_hits + 1 if data.qpos[2] < 0.40 or upright < 0.5 else 0
        if fall_hits >= 80:
            fell = True

        if step % video_every == 0:
            qpos_states.append(data.qpos.copy())
            visual_positions.append(data.geom_xpos[visual_ids].copy())
            visual_matrices.append(
                data.geom_xmat[visual_ids].reshape(-1, 3, 3).copy()
            )
            mug_positions.append(data.xpos[mug_body_id].copy())
            mug_matrices.append(data.xmat[mug_body_id].reshape(3, 3).copy())
            palm_positions.append(data.xpos[palm_body_id].copy())
            palm_matrices.append(data.xmat[palm_body_id].reshape(3, 3).copy())
            times.append(float(data.time))
            timeline.append(
                {
                    "time_s": float(data.time),
                    "phase": (
                        locomotion_phase if base_released else phase
                    ),
                    "task_phase": phase,
                    "pre_release_carry_active": pre_release_carry_active,
                    "locomotion_phase": locomotion_phase,
                    "base_xyz_m": data.qpos[:3].tolist(),
                    "base_yaw_deg": math.degrees(base_yaw(data.qpos)),
                    "base_upright_component": float(upright),
                    "mug_xyz_m": data.xpos[mug_body_id].tolist(),
                    "walk_progress_m": (
                        float(
                            np.dot(
                                data.qpos[:2] - walk_origin_base_xy,
                                walk_world_direction,
                            )
                        )
                        if walk_origin_base_xy is not None
                        else None
                    ),
                    "hand_contact_bodies": sorted(
                        {row["body"] for row in sample["hand"]}
                    ),
                    "support_contact_geoms": sorted(
                        {row["geom"] for row in sample["support"]}
                    ),
                    "hand_normal_force_N": float(
                        sum(row["normal_force_N"] for row in sample["hand"])
                    ),
                    "hand_tangential_force_N": float(
                        sum(row["tangential_force_N"] for row in sample["hand"])
                    ),
                    "max_mug_contact_penetration_m": sample[
                        "max_mug_contact_penetration_m"
                    ],
                }
            )
        if fell:
            break

    qpos_states = np.asarray(qpos_states)
    visual_positions = np.asarray(visual_positions)
    visual_matrices = np.asarray(visual_matrices)
    mug_positions = np.asarray(mug_positions)
    mug_matrices = np.asarray(mug_matrices)
    palm_positions = np.asarray(palm_positions)
    palm_matrices = np.asarray(palm_matrices)
    times_array = np.asarray(times)

    relative_positions = np.einsum(
        "nij,nj->ni", np.transpose(palm_matrices, (0, 2, 1)), mug_positions - palm_positions
    )
    if args.full_pick_place:
        hold_mask = (times_array >= phases["lift_end"]) & (
            times_array < phases["lower_start"]
        )
    else:
        hold_mask = times_array >= phases["lift_end"]
    hold_indices = np.flatnonzero(hold_mask)
    if len(hold_indices):
        reference_relative = relative_positions[hold_indices[0]]
        max_hold_slip = float(
            np.max(
                np.linalg.norm(
                    relative_positions[hold_indices] - reference_relative, axis=1
                )
            )
        )
        hold_contact_fraction = float(
            np.mean(
                [
                    bool(row["hand_contact_bodies"])
                    for row in np.asarray(timeline, dtype=object)[hold_mask]
                ]
            )
        )
        hold_support_fraction = float(
            np.mean(
                [
                    bool(row["support_contact_geoms"])
                    for row in np.asarray(timeline, dtype=object)[hold_mask]
                ]
            )
        )
        hold_three_digit_contact_fraction = float(
            np.mean(
                [
                    all(
                        any(f"right_hand_{digit}_" in body for body in row["hand_contact_bodies"])
                        for digit in ("thumb", "index", "middle")
                    )
                    for row in np.asarray(timeline, dtype=object)[hold_mask]
                ]
            )
        )
    else:
        max_hold_slip = math.inf
        hold_contact_fraction = 0.0
        hold_support_fraction = 1.0
        hold_three_digit_contact_fraction = 0.0

    initial_settled_mask = (times_array >= 0.5) & (times_array < phases["close_start"])
    settled_z = float(np.median(mug_positions[initial_settled_mask, 2]))
    max_lift = float(np.max(mug_positions[:, 2]) - settled_z)
    final_lift = float(mug_positions[-1, 2] - settled_z)
    max_horizontal_displacement = float(
        np.max(
            np.linalg.norm(
                mug_positions[:, :2] - mug_positions[0, :2], axis=1
            )
        )
    )
    final_rotation = Rotation.from_matrix(mug_matrices[-1])
    final_tilt = float(
        math.degrees(
            math.acos(
                float(np.clip(mug_matrices[-1, 2, 2], -1.0, 1.0))
            )
        )
    )
    cup_equality_constraints = []
    for equality_id in range(model.neq):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_EQUALITY, equality_id)
        object1 = int(model.eq_obj1id[equality_id])
        object2 = int(model.eq_obj2id[equality_id])
        if mug_body_id in (object1, object2):
            cup_equality_constraints.append(name or str(equality_id))

    final_window = times_array >= max(0.0, float(data.time) - 1.0)
    final_rows = np.asarray(timeline, dtype=object)[final_window]
    final_hand_contact_fraction = float(
        np.mean([bool(row["hand_contact_bodies"]) for row in final_rows])
    )
    final_support_contact_fraction = float(
        np.mean([bool(row["support_contact_geoms"]) for row in final_rows])
    )
    mug_dof_address = int(model.jnt_dofadr[mug_joint_id])
    final_mug_linear_speed = float(
        np.linalg.norm(data.qvel[mug_dof_address : mug_dof_address + 3])
    )
    final_mug_angular_speed = float(
        np.linalg.norm(data.qvel[mug_dof_address + 3 : mug_dof_address + 6])
    )
    final_place_xy_error = float(
        np.linalg.norm(
            mug_positions[-1, :2]
            - np.array([1.48 + args.transport_distance, 0.31])
        )
    )
    saved_dt = float(np.median(np.diff(times_array)))
    mug_tilts = np.degrees(
        np.arccos(np.clip(mug_matrices[:, 2, 2], -1.0, 1.0))
    )
    timeline_array = np.asarray(timeline, dtype=object)

    def carry_phase_metrics(mask: np.ndarray) -> dict[str, float]:
        indices = np.flatnonzero(mask)
        if not len(indices):
            return {
                "duration_s": 0.0,
                "hand_contact_fraction": 0.0,
                "support_contact_fraction": 1.0,
                "three_digit_contact_fraction": 0.0,
                "max_relative_position_slip_m": math.inf,
                "max_mug_tilt_deg": math.inf,
                "max_base_tilt_deg": math.inf,
                "min_base_height_m": -math.inf,
                "max_base_yaw_drift_deg": math.inf,
            }
        rows = timeline_array[mask]
        reference_relative = relative_positions[indices[0]]
        reference_yaw = base_yaw(qpos_states[indices[0]])
        yaw_drifts = [
            abs(
                (base_yaw(qpos_states[index]) - reference_yaw + math.pi)
                % (2.0 * math.pi)
                - math.pi
            )
            for index in indices
        ]
        upright_components = 1.0 - 2.0 * (
            qpos_states[indices, 4] ** 2 + qpos_states[indices, 5] ** 2
        )
        return {
            "duration_s": float(len(indices) * saved_dt),
            "hand_contact_fraction": float(
                np.mean([bool(row["hand_contact_bodies"]) for row in rows])
            ),
            "support_contact_fraction": float(
                np.mean([bool(row["support_contact_geoms"]) for row in rows])
            ),
            "three_digit_contact_fraction": float(
                np.mean(
                    [
                        all(
                            any(
                                f"right_hand_{digit}_" in body
                                for body in row["hand_contact_bodies"]
                            )
                            for digit in ("thumb", "index", "middle")
                        )
                        for row in rows
                    ]
                )
            ),
            "max_relative_position_slip_m": float(
                np.max(
                    np.linalg.norm(
                        relative_positions[indices] - reference_relative,
                        axis=1,
                    )
                )
            ),
            "max_mug_tilt_deg": float(np.max(mug_tilts[indices])),
            "max_base_tilt_deg": float(
                np.degrees(
                    np.max(
                        np.arccos(np.clip(upright_components, -1.0, 1.0))
                    )
                )
            ),
            "min_base_height_m": float(np.min(qpos_states[indices, 2])),
            "max_base_yaw_drift_deg": float(math.degrees(max(yaw_drifts))),
        }

    if base_release_actual_time is not None:
        free_base_mask = times_array >= base_release_actual_time
        static_hold_end = walk_start_scheduled_time
        free_base_static_mask = free_base_mask & (
            times_array < static_hold_end + 0.5 * saved_dt
        )
        free_base_settled_mask = free_base_static_mask & (
            times_array >= base_release_actual_time + 0.5
        )
        walk_mask = (
            times_array >= walk_start_actual_time
            if walk_start_actual_time is not None
            else np.zeros(len(times_array), dtype=bool)
        )
        post_walk_mask = (
            times_array >= walk_complete_time
            if walk_complete_time is not None
            else np.zeros(len(times_array), dtype=bool)
        )
    else:
        free_base_mask = np.zeros(len(times_array), dtype=bool)
        free_base_static_mask = free_base_mask.copy()
        free_base_settled_mask = free_base_mask.copy()
        walk_mask = free_base_mask.copy()
        post_walk_mask = free_base_mask.copy()
    free_base_metrics = carry_phase_metrics(free_base_mask)
    free_base_static_metrics = carry_phase_metrics(free_base_static_mask)
    free_base_settled_metrics = carry_phase_metrics(free_base_settled_mask)
    walk_metrics = carry_phase_metrics(walk_mask)
    post_walk_metrics = carry_phase_metrics(post_walk_mask)

    free_base_static_hold_target_met = bool(
        base_release_actual_time is not None
        and not fell
        and free_base_static_metrics["duration_s"]
        >= args.free_base_static_hold_s - 0.10
        and free_base_static_metrics["hand_contact_fraction"] >= 0.80
        and free_base_static_metrics["support_contact_fraction"] <= 0.05
        and free_base_static_metrics["three_digit_contact_fraction"] >= 0.80
        and free_base_static_metrics["max_relative_position_slip_m"] <= 0.005
        and free_base_static_metrics["max_mug_tilt_deg"] <= 10.0
        and free_base_static_metrics["max_base_tilt_deg"] <= 15.0
        and free_base_static_metrics["min_base_height_m"] >= 0.60
        and max_mug_penetration <= 0.005
        and not cup_equality_constraints
        and mug_pose_writes_after_initialization == 0
    )
    locomotion_admission_target_met = bool(
        base_release_actual_time is not None
        and not fell
        and free_base_settled_metrics["duration_s"]
        >= args.free_base_static_hold_s - 0.60
        and free_base_settled_metrics["hand_contact_fraction"] >= 0.80
        and free_base_settled_metrics["support_contact_fraction"] <= 0.05
        and free_base_settled_metrics["three_digit_contact_fraction"] >= 0.80
        and free_base_settled_metrics["max_relative_position_slip_m"] <= 0.005
        and free_base_settled_metrics["max_mug_tilt_deg"] <= 12.0
        and free_base_settled_metrics["max_base_tilt_deg"] <= 15.0
        and free_base_settled_metrics["min_base_height_m"] >= 0.60
        and max_mug_penetration <= 0.005
        and not cup_equality_constraints
        and mug_pose_writes_after_initialization == 0
    )
    walk_target_met = bool(
        args.walk_distance_m > 0.0
        and locomotion_admission_target_met
        and walk_completed
        and max_walk_progress
        >= args.walk_distance_m - walk_completion_tolerance_m
        and not fell
        and walk_metrics["hand_contact_fraction"] >= 0.80
        and walk_metrics["support_contact_fraction"] <= 0.05
        and walk_metrics["three_digit_contact_fraction"] >= 0.80
        and walk_metrics["max_relative_position_slip_m"] <= 0.010
        and walk_metrics["max_mug_tilt_deg"] <= 15.0
        and walk_metrics["max_base_tilt_deg"] <= 20.0
        and walk_metrics["min_base_height_m"] >= 0.55
        and max_mug_penetration <= 0.005
        and not cup_equality_constraints
        and mug_pose_writes_after_initialization == 0
    )
    post_release_mask = (
        times_array >= phases["release_end"]
        if args.full_pick_place
        else np.zeros(len(times_array), dtype=bool)
    )
    max_post_release_tilt = float(
        np.max(mug_tilts[post_release_mask])
        if np.any(post_release_mask)
        else math.inf
    )
    palm_speed_times = times_array[:-1]
    palm_speeds = np.linalg.norm(np.diff(palm_positions, axis=0), axis=1) / saved_dt
    palm_acceleration_times = times_array[1:-1]
    palm_accelerations = (
        np.linalg.norm(np.diff(palm_positions, n=2, axis=0), axis=1)
        / saved_dt**2
    )
    mug_acceleration_times = times_array[1:-1]
    mug_accelerations = (
        np.linalg.norm(np.diff(mug_positions, n=2, axis=0), axis=1)
        / saved_dt**2
    )
    retract_start = phases.get("retract_start", math.inf)
    post_retract_speed_mask = palm_speed_times >= retract_start
    post_retract_acceleration_mask = palm_acceleration_times >= retract_start
    post_retract_mug_acceleration_mask = mug_acceleration_times >= retract_start
    max_post_retract_palm_speed = float(
        np.max(palm_speeds[post_retract_speed_mask])
        if np.any(post_retract_speed_mask)
        else math.inf
    )
    max_post_retract_palm_acceleration = float(
        np.max(palm_accelerations[post_retract_acceleration_mask])
        if np.any(post_retract_acceleration_mask)
        else math.inf
    )
    max_post_retract_mug_acceleration = float(
        np.max(mug_accelerations[post_retract_mug_acceleration_mask])
        if np.any(post_retract_mug_acceleration_mask)
        else math.inf
    )
    retract_saved_mask = times_array >= retract_start
    retract_positions = palm_positions[retract_saved_mask]
    retract_cup_positions = mug_positions[retract_saved_mask]
    retract_matrices = palm_matrices[retract_saved_mask]
    if len(retract_positions) >= 2:
        retract_steps = np.diff(retract_positions, axis=0)
        retract_path_length = float(
            np.sum(np.linalg.norm(retract_steps, axis=1))
        )
        retract_displacement = float(
            np.linalg.norm(retract_positions[-1] - retract_positions[0])
        )
        retract_path_efficiency = retract_displacement / max(
            retract_path_length, 1.0e-9
        )
        retract_clearance_gain = float(
            np.linalg.norm(retract_positions[-1] - retract_cup_positions[-1])
            - np.linalg.norm(retract_positions[0] - retract_cup_positions[0])
        )
        retract_orientation_changes = Rotation.from_matrix(
            retract_matrices
            @ np.swapaxes(retract_matrices[0][None, :, :], 1, 2)
        ).magnitude()
        retract_orientation_steps = Rotation.from_matrix(
            retract_matrices[1:]
            @ np.swapaxes(retract_matrices[:-1], 1, 2)
        ).magnitude()
        max_retract_orientation_change = float(
            np.degrees(np.max(retract_orientation_changes))
        )
        retract_orientation_path = float(
            np.degrees(np.sum(retract_orientation_steps))
        )
        max_retract_angular_speed = float(
            np.degrees(np.max(retract_orientation_steps / saved_dt))
        )
    else:
        retract_path_length = math.inf
        retract_displacement = 0.0
        retract_path_efficiency = 0.0
        retract_clearance_gain = -math.inf
        max_retract_orientation_change = math.inf
        retract_orientation_path = math.inf
        max_retract_angular_speed = math.inf
    clearance_end = phases.get("clearance_end", retract_start)
    clearance_saved_mask = (times_array >= retract_start) & (
        times_array <= clearance_end
    )
    clearance_positions = palm_positions[clearance_saved_mask]
    clearance_direction = np.array([-0.10, 0.04, 0.04], dtype=float)
    clearance_direction /= np.linalg.norm(clearance_direction)
    if len(clearance_positions) >= 2:
        clearance_relative = clearance_positions - clearance_positions[0]
        clearance_progress = clearance_relative @ clearance_direction
        clearance_progress_steps = np.diff(clearance_progress)
        final_clearance_progress = float(clearance_progress[-1])
        clearance_backward_travel = float(
            np.sum(np.maximum(-clearance_progress_steps, 0.0))
        )
        clearance_vertical_excursion = float(
            np.max(np.abs(clearance_relative[:, 2]))
        )
    else:
        final_clearance_progress = -math.inf
        clearance_backward_travel = math.inf
        clearance_vertical_excursion = math.inf
    lifted_retract_saved_mask = (times_array >= clearance_end) & (
        times_array <= phases.get("retract_end", args.duration)
    )
    lifted_retract_positions = palm_positions[lifted_retract_saved_mask]
    retract_downward_travel = (
        float(np.sum(np.maximum(-np.diff(lifted_retract_positions[:, 2]), 0.0)))
        if len(lifted_retract_positions) >= 2
        else math.inf
    )
    pre_retract_no_hand_contact_dwell = (
        max_pre_retract_no_hand_contact_run_steps * dt
    )
    if args.full_pick_place:
        task_success = bool(
            not fell
            and max_lift >= 0.08
            and max_horizontal_displacement >= 0.07
            and hold_contact_fraction >= 0.80
            and hold_support_fraction <= 0.05
            and max_hold_slip <= 0.04
            and final_hand_contact_fraction <= 0.05
            and final_support_contact_fraction >= 0.80
            and final_place_xy_error <= 0.07
            and abs(final_lift) <= 0.04
            and final_tilt <= 40.0
            and final_mug_linear_speed <= 0.05
            and final_mug_angular_speed <= 0.50
            and not cup_equality_constraints
            and mug_pose_writes_after_initialization == 0
        )
    else:
        task_success = bool(
            not fell
            and max_lift >= 0.08
            and final_lift >= 0.08
            and hold_contact_fraction >= 0.80
            and hold_support_fraction <= 0.05
            and max_hold_slip <= 0.035
            and final_tilt <= 35.0
            and not cup_equality_constraints
            and mug_pose_writes_after_initialization == 0
        )
    stability_target_met = bool(
        not fell
        and max_lift >= 0.08
        and final_lift >= 0.08
        and hold_contact_fraction >= 0.80
        and hold_support_fraction <= 0.05
        and hold_three_digit_contact_fraction >= 0.80
        and max_hold_slip <= 0.005
        and final_tilt <= 10.0
        and max_mug_penetration <= 0.005
        and not cup_equality_constraints
        and mug_pose_writes_after_initialization == 0
    )
    placement_target_met = bool(
        args.full_pick_place
        and not fell
        and max_lift >= 0.08
        and max_horizontal_displacement >= max(0.05, args.transport_distance - 0.02)
        and hold_contact_fraction >= 0.80
        and hold_support_fraction <= 0.05
        and hold_three_digit_contact_fraction >= 0.80
        and max_hold_slip <= 0.01
        and final_hand_contact_fraction <= 0.05
        and final_support_contact_fraction >= 0.80
        and final_place_xy_error <= 0.035
        and abs(final_lift) <= 0.03
        and final_tilt <= 15.0
        and final_mug_linear_speed <= 0.05
        and final_mug_angular_speed <= 0.50
        and max_mug_penetration <= 0.005
        and not cup_equality_constraints
        and mug_pose_writes_after_initialization == 0
    )
    clean_placement_target_met = bool(
        placement_target_met
        and args.contact_aware_placement
        and support_stop_triggered
        and pre_retract_no_hand_contact_dwell >= 0.25
        and post_retract_hand_contact_steps == 0
        and max_post_release_tilt <= 15.0
        and max_post_retract_palm_speed <= 0.25
        and max_post_retract_palm_acceleration <= 2.0
        and max_post_retract_mug_acceleration <= 1.0
        and retract_path_efficiency >= 0.60
        and retract_clearance_gain >= 0.05
        and final_clearance_progress >= 0.05
        and clearance_backward_travel <= 0.01
        and clearance_vertical_excursion <= 0.035
        and retract_downward_travel <= 0.01
        and max_retract_orientation_change <= 35.0
        and retract_orientation_path <= 50.0
        and max_retract_angular_speed <= 45.0
    )
    disturbance_target_met = bool(
        args.cup_lateral_force_newtons > 0.0
        and not fell
        and max_lift >= 0.08
        and final_lift >= 0.08
        and disturbance_steps > 0
        and disturbance_hand_contact_steps / disturbance_steps >= 0.80
        and disturbance_support_contact_steps / disturbance_steps <= 0.05
        and max_hold_slip <= 0.005
        and final_tilt <= 15.0
        and max_mug_penetration <= 0.005
        and not cup_equality_constraints
        and mug_pose_writes_after_initialization == 0
    )

    trajectory_path = args.output / "ROBOT_CUP_PHYSICS_TRAJECTORY.npz"
    np.savez_compressed(
        trajectory_path,
        qpos=qpos_states,
        positions=visual_positions,
        matrices=visual_matrices,
        times=times_array,
        cup_positions=mug_positions,
        cup_matrices=mug_matrices,
        right_palm_positions=palm_positions,
        right_palm_matrices=palm_matrices,
    )
    report = {
        "schema": "bedroom_g1_dynamic_mug_friction_lift_v1",
        "label": (
            "physics_contact_feasibility_pass"
            if task_success
            else "physics_contact_feasibility_failed"
        ),
        "task_success": task_success,
        "scope": (
            "continuous_fixed_base_grasp_lift_then_free_base_carry_walk"
            if args.base_release_time_s is not None and args.walk_distance_m > 0.0
            else "continuous_fixed_base_grasp_lift_then_free_base_static_hold"
            if args.base_release_time_s is not None
            else
            "fixed_base_dynamic_friction_pick_transport_place_release"
            if args.full_pick_place
            else "stand_in_place_close_lift_and_hold_before_full_pick_place"
        ),
        "scene": "own_generator/bedroom_composition_detail/mainline_full_v2",
        "robot": "full_body_unitree_g1",
        "controller": (
            "continuous_weld_release_walker_plus_world_upright_direct_task_arm"
            if args.base_release_time_s is not None
            else
            "direct_fixed_body_and_task_arm_pd_plus_online_6d_ik_and_finger_targets"
            if args.direct_fixed_base_arm_pd and args.direct_fixed_posture_pd
            else "fixed_posture_direct_gravity_compensated_arm_pd_plus_finger_targets"
            if args.direct_fixed_base_arm_pd
            else "base_stabilized_walker_plus_online_6d_ik_with_direct_lift_arm_pd"
            if args.direct_lift_arm_pd
            else "base_stabilized_walker_plus_online_6d_ik_with_direct_retract_arm_pd"
            if args.direct_retract_arm_pd
            else "base_stabilized_walker_plus_online_6d_arm_ik_and_finger_targets"
            if args.keep_walker_with_stabilized_base
            else "fixed_non_task_posture_plus_online_6d_arm_ik_and_finger_targets"
            if args.stabilize_robot_base
            else "online_walker_balance_plus_joint_space_arm_and_finger_targets"
        ),
        "model_xml": str(model_xml),
        "model_xml_sha256": sha256(model_xml),
        "trajectory": str(trajectory_path),
        "trajectory_sha256": sha256(trajectory_path),
        "source_visual_trajectory": str(SOURCE_VISUAL_TRAJECTORY),
        "source_visual_trajectory_sha256": sha256(SOURCE_VISUAL_TRAJECTORY),
        "phases_s": phases,
        "physics": {
            "executed": True,
            "timestep_s": dt,
            "steps": step + 1,
            "duration_s": float(data.time),
            "walker_control_period_s": dt * policy_every,
            "saved_trajectory_fps": 1.0 / (dt * video_every),
            "mug_mass_kg": args.mug_mass,
            "mug_sliding_friction": args.mug_friction,
            "mug_collision_proxy_radius_m": args.mug_radius,
            "mug_collision_proxy_half_height_m": args.mug_half_height,
            "grasp_azimuth_offset_deg": args.grasp_azimuth_offset_deg,
            "grasp_radial_inset_m": args.grasp_radial_inset_m,
            "grasp_vertical_offset_m": args.grasp_vertical_offset_m,
            "enveloping_reference": enveloping_reference,
            "stable_stance_reference": stable_stance_reference,
            "grasp_azimuth_preflight": grasp_azimuth_preflight,
            "actual_state_lift_anchor": args.actual_state_lift_anchor,
            "lift_duration_s": args.lift_duration,
            "actual_lift_offset_xyz_m": (
                actual_lift_offset.tolist()
                if args.actual_state_lift_anchor
                else None
            ),
            "lift_anchor_time_s": lift_anchor_time,
            "lift_anchor_palm_xyz_m": (
                lift_anchor_palm_position.tolist()
                if lift_anchor_palm_position is not None
                else None
            ),
            "lift_anchor_arm_rad": (
                lift_anchor_arm.tolist() if lift_anchor_arm is not None else None
            ),
            "mug_is_dynamic_free_body": True,
            "mug_pose_writes_after_initialization": mug_pose_writes_after_initialization,
            "mug_weld_or_equality_constraints": cup_equality_constraints,
            "robot_base_stabilization_weld": args.stabilize_robot_base,
            "robot_base_stabilization_weld_released_during_run": (
                base_release_actual_time is not None
            ),
            "requested_base_release_time_s": args.base_release_time_s,
            "actual_base_release_time_s": base_release_actual_time,
            "base_release_xyz_m": (
                base_release_base_position.tolist()
                if base_release_base_position is not None
                else None
            ),
            "free_base_static_hold_commanded_s": args.free_base_static_hold_s,
            "base_release_posture_blend_s": args.base_release_posture_blend_s,
            "pre_release_posture_blend_s": args.pre_release_posture_blend_s,
            "pre_release_carry_offset_xyz_m": (
                pre_release_carry_offset.tolist()
            ),
            "pre_release_carry_duration_s": args.pre_release_carry_duration_s,
            "post_release_index_tighten_rad": (
                args.post_release_index_tighten_rad
            ),
            "post_release_finger_ramp_s": args.post_release_finger_ramp_s,
            "index_tighten_lead_s": args.index_tighten_lead_s,
            "walker_policy_warmed_while_base_welded": (
                args.warm_walker_before_base_release
                or args.pre_release_posture_blend_s > 0.0
            ),
            "walk_body_axis": (
                args.walk_body_axis if args.walk_distance_m > 0.0 else None
            ),
            "walk_world_direction_xy": (
                walk_world_direction.tolist()
                if args.walk_distance_m > 0.0
                and walk_world_direction is not None
                else None
            ),
            "walk_commanded_distance_m": args.walk_distance_m,
            "walk_commanded_speed_mps": args.walk_speed_mps,
            "walk_command_ramp_s": args.walk_command_ramp_s,
            "walk_stop_ramp_distance_m": args.walk_stop_ramp_distance_m,
            "walk_completion_tolerance_m": walk_completion_tolerance_m,
            "walk_start_actual_time_s": walk_start_actual_time,
            "walk_complete_time_s": walk_complete_time,
            "walk_completed": walk_completed,
            "free_base_carry_frame": (
                args.free_base_carry_frame
                if base_release_actual_time is not None
                else None
            ),
            "world_upright_carry_frame": (
                base_release_actual_time is not None
                and args.free_base_carry_frame == "world-upright"
            ),
            "base_release_arm_rad": (
                base_release_arm.tolist()
                if base_release_arm is not None
                else None
            ),
            "finger_actuators_enabled": True,
            "direct_fixed_base_arm_pd": args.direct_fixed_base_arm_pd,
            "direct_fixed_posture_pd": args.direct_fixed_posture_pd,
            "direct_fixed_posture_joint_names": list(fixed_posture_names),
            "direct_fixed_posture_kp": fixed_posture_kp.tolist(),
            "direct_fixed_posture_kd": fixed_posture_kd.tolist(),
            "direct_lift_arm_pd": args.direct_lift_arm_pd,
            "direct_retract_arm_pd": args.direct_retract_arm_pd,
            "direct_arm_pd_kp": arm_pd_kp.tolist(),
            "direct_arm_pd_kd": arm_pd_kd.tolist(),
            "direct_arm_pd_torque_limits_preserved": True,
            "contact_aware_placement": args.contact_aware_placement,
            "external_grip_load_test": args.cup_lateral_force_newtons > 0.0,
            "cup_lateral_force_direction_world": (
                [-1.0, 0.0, 0.0]
                if args.cup_lateral_force_newtons > 0.0
                else None
            ),
            "cup_lateral_force_peak_command_N": args.cup_lateral_force_newtons,
            "cup_lateral_force_window_s": [
                args.cup_force_start,
                args.cup_force_end,
            ],
            "cup_lateral_force_ramp_s": args.cup_force_ramp,
        },
        "contact_evidence": {
            "hand_contact_step_fraction": hand_contact_steps / max(1, step + 1),
            "support_contact_step_fraction": support_contact_steps / max(1, step + 1),
            "lift_and_hold_hand_contact_step_fraction": lifted_hand_contact_steps
            / max(1, int((args.duration - phases["lift_start"]) / dt)),
            "lift_and_hold_support_contact_step_fraction": lifted_support_contact_steps
            / max(1, int((args.duration - phases["lift_start"]) / dt)),
            "hold_hand_contact_saved_frame_fraction": hold_contact_fraction,
            "hold_support_contact_saved_frame_fraction": hold_support_fraction,
            "hold_three_digit_contact_saved_frame_fraction": hold_three_digit_contact_fraction,
            "contacted_hand_bodies": sorted(hand_contact_bodies),
            "contacted_support_geoms": sorted(support_contact_geoms),
            "max_hand_normal_force_N": max_hand_normal_force,
            "max_hand_tangential_force_N": max_hand_tangential_force,
            "max_mug_contact_penetration_m": max_mug_penetration,
            "support_stop_triggered": support_stop_triggered,
            "support_stop_time_s": support_stop_time,
            "pre_retract_no_hand_contact_dwell_s": pre_retract_no_hand_contact_dwell,
            "post_retract_hand_contact_steps": post_retract_hand_contact_steps,
            "post_retract_first_hand_contact_time_s": post_retract_first_hand_contact_time,
            "post_retract_max_hand_normal_force_N": post_retract_max_hand_normal_force,
            "disturbance_steps": disturbance_steps,
            "disturbance_peak_applied_force_N": max_disturbance_force,
            "disturbance_applied_impulse_Ns": disturbance_force_impulse,
            "disturbance_hand_contact_step_fraction": (
                disturbance_hand_contact_steps / disturbance_steps
                if disturbance_steps
                else None
            ),
            "disturbance_support_contact_step_fraction": (
                disturbance_support_contact_steps / disturbance_steps
                if disturbance_steps
                else None
            ),
            "disturbance_max_single_hand_contact_normal_force_N": (
                disturbance_max_hand_normal_force
                if disturbance_steps
                else None
            ),
            "free_base_all": free_base_metrics,
            "free_base_static_hold": free_base_static_metrics,
            "free_base_settled_after_handover": free_base_settled_metrics,
            "walk_and_post_walk": walk_metrics,
            "post_walk_hold": post_walk_metrics,
        },
        "motion_evidence": {
            "settled_mug_center_z_m": settled_z,
            "max_lift_m": max_lift,
            "final_lift_m": final_lift,
            "max_horizontal_displacement_m": max_horizontal_displacement,
            "max_hold_relative_position_slip_m": max_hold_slip,
            "final_mug_tilt_deg": final_tilt,
            "final_mug_rotvec_rad": final_rotation.as_rotvec().tolist(),
            "robot_fell": fell,
            "final_base_xyz_m": data.qpos[:3].tolist(),
            "maximum_walk_progress_m": max_walk_progress,
            "walk_completed": walk_completed,
            "walk_complete_time_s": walk_complete_time,
            "final_place_xy_error_m": final_place_xy_error,
            "commanded_transport_distance_m": args.transport_distance,
            "final_mug_linear_speed_mps": final_mug_linear_speed,
            "final_mug_angular_speed_rad_s": final_mug_angular_speed,
            "final_hand_contact_saved_frame_fraction": final_hand_contact_fraction,
            "final_support_contact_saved_frame_fraction": final_support_contact_fraction,
            "max_command_update_palm_position_error_m": max_palm_position_error,
            "max_command_update_palm_orientation_error_deg": math.degrees(
                max_palm_orientation_error
            ),
            "max_post_release_mug_tilt_deg": max_post_release_tilt,
            "max_post_retract_palm_speed_mps": max_post_retract_palm_speed,
            "max_post_retract_palm_acceleration_mps2": max_post_retract_palm_acceleration,
            "max_post_retract_mug_acceleration_mps2": max_post_retract_mug_acceleration,
            "post_retract_path_length_m": retract_path_length,
            "post_retract_displacement_m": retract_displacement,
            "post_retract_path_efficiency": retract_path_efficiency,
            "post_retract_hand_mug_clearance_gain_m": retract_clearance_gain,
            "clearance_stage_final_progress_m": final_clearance_progress,
            "clearance_stage_backward_travel_m": clearance_backward_travel,
            "clearance_stage_vertical_excursion_m": clearance_vertical_excursion,
            "lifted_retract_stage_downward_travel_m": retract_downward_travel,
            "max_post_retract_palm_orientation_change_deg": max_retract_orientation_change,
            "post_retract_palm_orientation_path_deg": retract_orientation_path,
            "max_post_retract_palm_angular_speed_deg_s": max_retract_angular_speed,
        },
        "acceptance": {
            "minimum_lift_m": 0.08,
            "minimum_hold_s": args.duration - phases["lift_end"],
            "minimum_hold_hand_contact_fraction": 0.80,
            "maximum_hold_support_contact_fraction": 0.05,
            "maximum_hold_slip_m": 0.035,
            "maximum_final_tilt_deg": 35.0,
            "stability_target_met": stability_target_met,
            "stability_target": {
                "minimum_lift_m": 0.08,
                "minimum_hold_three_digit_contact_fraction": 0.80,
                "maximum_hold_support_contact_fraction": 0.05,
                "maximum_hold_slip_m": 0.005,
                "maximum_final_tilt_deg": 10.0,
                "maximum_mug_contact_penetration_m": 0.005,
            },
            "free_base_static_hold_target_met": free_base_static_hold_target_met,
            "free_base_static_hold_target": {
                "minimum_duration_s": args.free_base_static_hold_s,
                "minimum_hand_contact_fraction": 0.80,
                "maximum_support_contact_fraction": 0.05,
                "minimum_three_digit_contact_fraction": 0.80,
                "maximum_relative_position_slip_m": 0.005,
                "maximum_mug_tilt_deg": 10.0,
                "maximum_base_tilt_deg": 15.0,
                "minimum_base_height_m": 0.60,
                "maximum_mug_contact_penetration_m": 0.005,
            },
            "locomotion_admission_target_met": locomotion_admission_target_met,
            "locomotion_admission_target": {
                "handover_transient_excluded_s": 0.5,
                "minimum_settled_duration_s": max(
                    0.0, args.free_base_static_hold_s - 0.60
                ),
                "minimum_hand_contact_fraction": 0.80,
                "maximum_support_contact_fraction": 0.05,
                "minimum_three_digit_contact_fraction": 0.80,
                "maximum_relative_position_slip_m": 0.005,
                "maximum_mug_tilt_deg": 12.0,
                "maximum_base_tilt_deg": 15.0,
                "minimum_base_height_m": 0.60,
            },
            "walk_target_met": walk_target_met,
            "walk_target": {
                "requires_free_base_static_hold_target": True,
                "minimum_projected_progress_m": (
                    args.walk_distance_m - walk_completion_tolerance_m
                ),
                "minimum_hand_contact_fraction": 0.80,
                "maximum_support_contact_fraction": 0.05,
                "minimum_three_digit_contact_fraction": 0.80,
                "maximum_relative_position_slip_m": 0.010,
                "maximum_mug_tilt_deg": 15.0,
                "maximum_base_tilt_deg": 20.0,
                "minimum_base_height_m": 0.55,
                "maximum_mug_contact_penetration_m": 0.005,
            },
            "placement_target_met": placement_target_met,
            "placement_target": {
                "minimum_lift_m": 0.08,
                "minimum_horizontal_displacement_m": max(
                    0.05, args.transport_distance - 0.02
                ),
                "minimum_hold_three_digit_contact_fraction": 0.80,
                "maximum_hold_support_contact_fraction": 0.05,
                "maximum_hold_slip_m": 0.01,
                "maximum_final_hand_contact_fraction": 0.05,
                "minimum_final_support_contact_fraction": 0.80,
                "maximum_final_place_xy_error_m": 0.035,
                "maximum_absolute_final_lift_m": 0.03,
                "maximum_final_tilt_deg": 15.0,
                "maximum_final_linear_speed_mps": 0.05,
                "maximum_final_angular_speed_rad_s": 0.50,
                "maximum_mug_contact_penetration_m": 0.005,
            },
            "clean_placement_target_met": clean_placement_target_met,
            "disturbance_target_met": disturbance_target_met,
            "disturbance_target": {
                "minimum_peak_lateral_force_N": args.cup_lateral_force_newtons,
                "minimum_disturbance_hand_contact_fraction": 0.80,
                "maximum_disturbance_support_contact_fraction": 0.05,
                "maximum_hold_slip_m": 0.005,
                "maximum_final_tilt_deg": 15.0,
                "maximum_mug_contact_penetration_m": 0.005,
            },
            "clean_placement_target": {
                "contact_aware_support_stop_required": True,
                "minimum_pre_retract_no_hand_contact_dwell_s": 0.25,
                "maximum_post_retract_hand_contact_steps": 0,
                "maximum_post_release_mug_tilt_deg": 15.0,
                "maximum_post_retract_palm_speed_mps": 0.25,
                "maximum_post_retract_palm_acceleration_mps2": 2.0,
                "maximum_post_retract_mug_acceleration_mps2": 1.0,
                "minimum_post_retract_path_efficiency": 0.60,
                "minimum_post_retract_hand_mug_clearance_gain_m": 0.05,
                "minimum_clearance_stage_final_progress_m": 0.05,
                "maximum_clearance_stage_backward_travel_m": 0.01,
                "maximum_clearance_stage_vertical_excursion_m": 0.035,
                "maximum_lifted_retract_stage_downward_travel_m": 0.01,
                "maximum_post_retract_palm_orientation_change_deg": 35.0,
                "maximum_post_retract_palm_orientation_path_deg": 50.0,
                "maximum_post_retract_palm_angular_speed_deg_s": 45.0,
            },
            "full_pick_place_claimed": args.full_pick_place and task_success,
            "production_accepted": False,
            "learning_validated": False,
        },
        "finger_targets_rad": {
            "joint_names": list(FINGER_NAMES),
            "open": open_fingers.tolist(),
            "closed": closed_fingers.tolist(),
            "custom_closed_targets_used": args.closed_finger_targets_rad is not None,
            "closure_fraction_before_scale": closure_fraction.tolist(),
            "thumb_close_fraction_before_scale": args.thumb_close_fraction,
            "index_close_fraction_before_scale": args.index_close_fraction,
            "index_close_delay_s": args.index_close_delay,
            "thumb_close_completion_advance_s": (
                args.thumb_close_completion_advance
            ),
            "middle_close_completion_advance_s": (
                args.middle_close_completion_advance
            ),
            "close_scale": args.close_scale,
        },
        "arm_tracking_outer_gain": args.arm_tracking_gain,
        "cartesian_tracking": {
            "enabled": args.cartesian_gain > 0.0,
            "gain": args.cartesian_gain,
            "max_joint_correction_rad": args.cartesian_max_joint_correction,
            "position_weight": 5.0,
            "orientation_weight": 0.5,
            "online_6d_ik_replan": args.online_ik,
            "online_ik_max_joint_step_per_control_update_rad": args.ik_max_joint_step,
            "rotation_targets_interpolated_continuously": True,
            "contact_aware_retract_ik_max_joint_step_rad": (
                min(args.ik_max_joint_step, 0.03)
                if args.contact_aware_placement
                else None
            ),
            "contact_aware_retract_cartesian_max_joint_correction_rad": (
                min(args.cartesian_max_joint_correction, 0.03)
                if args.contact_aware_placement
                else None
            ),
            "contact_aware_retract_max_joint_command_step_rad": (
                args.retract_max_joint_command_step
                if args.contact_aware_placement
                else None
            ),
            "online_ik_successful_updates": len(ik_position_errors),
            "online_ik_max_position_error_m": (
                max(ik_position_errors) if ik_position_errors else None
            ),
            "online_ik_max_orientation_error_deg": (
                math.degrees(max(ik_orientation_errors))
                if ik_orientation_errors
                else None
            ),
        },
        "timeline": timeline,
    }
    write_json(args.output / "REPORT.json", report)
    print(
        json.dumps(
            {
                "task_success": task_success,
                "motion_evidence": report["motion_evidence"],
                "contact_evidence": report["contact_evidence"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
