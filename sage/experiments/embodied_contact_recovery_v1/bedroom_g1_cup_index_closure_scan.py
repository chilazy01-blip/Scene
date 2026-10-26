#!/usr/bin/env python3
"""Zero-integration index-finger closure scan on a saved failed lift.

For every saved squeeze/lift/hold state, the script applies only the target
delta implied by a candidate index closure fraction, then recomputes contacts
without calling ``mj_step``.  This is a geometric screen, not evidence that a
dynamic finger controller will retain the mug.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import mujoco
import numpy as np

from .bedroom_g1_cup_pick_place_physics_v1 import MUG_BODY, joint_addresses
from .bedroom_g1_cup_pick_place_v3 import FINGER_NAMES, contact_classification, sha256


ROOT = Path("/data/wsj/main")
DEFAULT_RUN = (
    ROOT
    / "scene_runs/codex_trellis_v2"
    / "bedroom_g1_cup_body_grasp_lift_20261013_v5_diagonal"
)
DEFAULT_OUTPUT = (
    ROOT
    / "scene_runs/codex_trellis_v2"
    / "bedroom_g1_cup_index_closure_scan_20261013_v2/PREFLIGHT.json"
)
FULLY_CLOSED = np.array(
    [0.80, -0.90, -1.50, 1.40, 1.50, 1.40, 1.50], dtype=float
)


def phase_masks(times: np.ndarray, phases: dict[str, float]) -> dict[str, np.ndarray]:
    return {
        "squeeze": (times >= phases["close_end"]) & (times < phases["lift_start"]),
        "lift": (times >= phases["lift_start"]) & (times < phases["lift_end"]),
        "hold": times >= phases["lift_end"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", nargs="?", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--run", type=Path, default=DEFAULT_RUN)
    parser.add_argument(
        "--fractions",
        type=float,
        nargs="+",
        default=[0.28, 0.30, 0.31, 0.32, 0.33, 0.34, 0.35],
    )
    args = parser.parse_args()
    if args.output.exists():
        raise RuntimeError(f"output already exists: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)

    report_path = args.run / "REPORT.json"
    trajectory_path = args.run / "ROBOT_CUP_PHYSICS_TRAJECTORY.npz"
    report = json.loads(report_path.read_text())
    trajectory = np.load(trajectory_path)
    model_path = Path(report["model_xml"])
    model = mujoco.MjModel.from_xml_path(str(model_path))
    data = mujoco.MjData(model)
    cup_body_id = model.body(MUG_BODY).id
    finger_addresses = joint_addresses(model, FINGER_NAMES)
    finger_joint_ids = np.asarray([model.joint(name).id for name in FINGER_NAMES])
    finger_limits = model.jnt_range[finger_joint_ids]
    index_local = np.asarray([3, 4], dtype=int)
    index_addresses = finger_addresses[index_local]

    baseline_fraction = float(
        report["finger_targets_rad"]["index_close_fraction_before_scale"]
        if "index_close_fraction_before_scale" in report["finger_targets_rad"]
        else report["finger_targets_rad"]["closure_fraction_before_scale"][3]
    )
    close_scale = float(report["finger_targets_rad"]["close_scale"])
    open_fingers = np.asarray(report["finger_targets_rad"]["open"], dtype=float)
    baseline_target = np.asarray(report["finger_targets_rad"]["closed"], dtype=float)
    masks = phase_masks(trajectory["times"], report["phases_s"])

    candidates = []
    for fraction in args.fractions:
        target = open_fingers + close_scale * np.asarray(
            [0.55, 0.55, 0.55, fraction, fraction, 0.35, 0.35]
        ) * (FULLY_CLOSED - open_fingers)
        target = np.clip(target, finger_limits[:, 0], finger_limits[:, 1])
        index_delta = target[index_local] - baseline_target[index_local]
        phase_rows = {
            phase: {
                "frames": int(np.count_nonzero(mask)),
                "any_hand_frames": 0,
                "index_frames": 0,
                "three_digit_frames": 0,
                "max_index_cup_penetration_m": 0.0,
                "max_any_cup_penetration_m": 0.0,
                "robot_room_collision_frames": 0,
                "robot_self_collision_frames": 0,
            }
            for phase, mask in masks.items()
        }
        for frame_index, qpos in enumerate(trajectory["qpos"]):
            phase = next(
                (name for name, mask in masks.items() if bool(mask[frame_index])),
                None,
            )
            if phase is None:
                continue
            work = qpos.copy()
            work[index_addresses] = np.clip(
                work[index_addresses] + index_delta,
                finger_limits[index_local, 0],
                finger_limits[index_local, 1],
            )
            data.qpos[:] = work
            data.qvel[:] = 0.0
            mujoco.mj_forward(model, data)
            mujoco.mj_collision(model, data)
            digits = set()
            any_hand = False
            max_index_penetration = 0.0
            max_cup_penetration = 0.0
            for contact in data.contact[: data.ncon]:
                geom1 = int(contact.geom1)
                geom2 = int(contact.geom2)
                body1 = int(model.geom_bodyid[geom1])
                body2 = int(model.geom_bodyid[geom2])
                if cup_body_id not in (body1, body2):
                    continue
                other = body2 if body1 == cup_body_id else body1
                body_name = (
                    mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, other)
                    or ""
                )
                penetration = max(0.0, -float(contact.dist))
                max_cup_penetration = max(max_cup_penetration, penetration)
                if body_name.startswith("right_hand_"):
                    any_hand = True
                    for digit in ("thumb", "index", "middle"):
                        if digit in body_name:
                            digits.add(digit)
                    if "index" in body_name:
                        max_index_penetration = max(
                            max_index_penetration, penetration
                        )
            contacts = contact_classification(model, data, cup_body_id)
            row = phase_rows[phase]
            row["any_hand_frames"] += int(any_hand)
            row["index_frames"] += int("index" in digits)
            row["three_digit_frames"] += int(len(digits) == 3)
            row["max_index_cup_penetration_m"] = max(
                row["max_index_cup_penetration_m"], max_index_penetration
            )
            row["max_any_cup_penetration_m"] = max(
                row["max_any_cup_penetration_m"], max_cup_penetration
            )
            row["robot_room_collision_frames"] += int(
                bool(contacts["robot_room"])
            )
            row["robot_self_collision_frames"] += int(
                bool(contacts["robot_self"])
            )

        for row in phase_rows.values():
            denominator = max(row["frames"], 1)
            for key in ("any_hand", "index", "three_digit"):
                row[f"{key}_fraction"] = row[f"{key}_frames"] / denominator
        candidates.append(
            {
                "index_close_fraction_before_scale": fraction,
                "index_target_delta_rad": index_delta.tolist(),
                "index_target_rad": target[index_local].tolist(),
                "phase_evidence": phase_rows,
                "preflight_pass": False,
            }
        )

    baseline = next(
        row
        for row in candidates
        if abs(row["index_close_fraction_before_scale"] - baseline_fraction)
        < 1.0e-12
    )
    for row in candidates:
        phase_rows = row["phase_evidence"]
        no_added_collision_frames = all(
            phase_rows[phase][category]
            <= baseline["phase_evidence"][phase][category]
            for phase in masks
            for category in (
                "robot_room_collision_frames",
                "robot_self_collision_frames",
            )
        )
        row["preflight_pass"] = bool(
            phase_rows["squeeze"]["three_digit_fraction"] >= 0.8
            and phase_rows["lift"]["index_fraction"] >= 0.8
            and max(
                phase["max_any_cup_penetration_m"]
                for phase in phase_rows.values()
            )
            <= 0.005
            and no_added_collision_frames
        )
    passing = [row for row in candidates if row["preflight_pass"]]
    selected = min(
        passing,
        key=lambda row: row["index_close_fraction_before_scale"],
        default=None,
    )
    payload = {
        "schema": "scene.index_closure_replay_preflight.v1",
        "scope": "zero-integration qpos perturbation of the saved v5 failure trajectory",
        "physics_rollout_executed": False,
        "mj_step_calls": 0,
        "source_run": str(args.run),
        "source_report_sha256": sha256(report_path),
        "source_trajectory_sha256": sha256(trajectory_path),
        "model_xml_sha256": sha256(model_path),
        "baseline_index_close_fraction_before_scale": baseline_fraction,
        "selection_rule": (
            "smallest candidate with squeeze three-digit and lift index contact "
            "fractions >= 0.8, <=5 mm cup penetration, and no collision-frame "
            "increase relative to the 0.28 replay baseline"
        ),
        "selected_candidate": selected,
        "candidates": candidates,
        "claim_boundary": (
            "Saved mug and arm states are replayed kinematically; dynamic grasp "
            "retention is untested. Hold contact is not a selection gate because "
            "the saved mug has already undergone the rotation this intervention "
            "is intended to prevent."
        ),
    }
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "selected_candidate": selected,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
