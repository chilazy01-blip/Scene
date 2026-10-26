#!/usr/bin/env python3
"""Simulate a prescribed hand proxy tipping the four upper-shelf books.

The room and robot are rendered separately.  This model intentionally keeps
the physical claim narrow: four free rigid books, a rigid shelf, and one
kinematic spherical contact proxy whose path is later matched by the G1 hand.
There are no pose resets after contact and no forces are applied directly to
the books.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import mujoco
import numpy as np


BOOK_NAMES = tuple(f"upright_book_{index}" for index in range(4))
BOOK_CENTERS_X = np.array([1.320, 1.378, 1.436, 1.494], dtype=float)
BOOK_SIZES = np.array(
    [
        [0.04388392, 0.16682744, 0.22999990],
        [0.04983854, 0.15821373, 0.23000002],
        [0.05427396, 0.15587714, 0.23000002],
        [0.04388392, 0.16682744, 0.22999990],
    ],
    dtype=float,
)
BOOK_COLORS = (
    "0.10 0.50 0.49 1",
    "0.57 0.18 0.11 1",
    "0.08 0.15 0.31 1",
    "0.10 0.50 0.49 1",
)
SHELF_TOP_Z = 1.15239
BOOK_Y = 0.400
PUSHER_Y = 0.505
PUSHER_Z = SHELF_TOP_Z + 0.205
PUSHER_RADIUS = 0.012
PUSHED_BOOK_X = 1.360


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def smoothstep(value: float) -> float:
    value = float(np.clip(value, 0.0, 1.0))
    return value * value * (3.0 - 2.0 * value)


def pusher_position(time_s: float, travel_m: float) -> np.ndarray:
    """Deterministic reach, push, hold, and retract path."""
    # Press the fingertip against the front of the first book, then sweep
    # sideways.  Friction transfers the lateral force without requiring the
    # hand to enter the unusably narrow gap beside the book.
    start = np.array([PUSHED_BOOK_X, PUSHER_Y, PUSHER_Z], dtype=float)
    contact = start + np.array([travel_m, -0.040, 0.0])
    if time_s < 0.80:
        return start
    if time_s < 1.55:
        alpha = smoothstep((time_s - 0.80) / 0.75)
        return (1.0 - alpha) * start + alpha * contact
    if time_s < 1.75:
        return contact
    if time_s < 2.35:
        alpha = smoothstep((time_s - 1.75) / 0.60)
        return (1.0 - alpha) * contact + alpha * start
    return start


def build_xml(friction: float, travel_m: float) -> str:
    del travel_m  # encoded only in the mocap path, retained in the API/report.
    book_bodies = []
    for name, center_x, size, color in zip(
        BOOK_NAMES, BOOK_CENTERS_X, BOOK_SIZES, BOOK_COLORS
    ):
        center_z = SHELF_TOP_Z + size[2] * 0.5 + 0.0003
        half = size * 0.5
        book_bodies.append(
            f"""
    <body name="{name}" pos="{center_x:.8f} {BOOK_Y:.8f} {center_z:.8f}">
      <freejoint name="{name}_free"/>
      <geom name="{name}_collision" type="box"
            size="{half[0]:.8f} {half[1]:.8f} {half[2]:.8f}"
            mass="0.32" friction="{friction:.5f} 0.005 0.0001"
            solref="0.006 1" solimp="0.96 0.995 0.002"
            rgba="{color}"/>
    </body>"""
        )
    bodies = "".join(book_bodies)
    return f"""<mujoco model="bedroom_upper_shelf_book_push">
  <compiler angle="radian" inertiafromgeom="true"/>
  <option timestep="0.0005" gravity="0 0 -9.81" integrator="implicitfast"
          cone="elliptic" solver="Newton" iterations="80" tolerance="1e-10"/>
  <size njmax="2000" nconmax="400"/>
  <default>
    <geom contype="1" conaffinity="1" condim="6" margin="0.00005" gap="0"/>
  </default>
  <contact>
    <!-- The real hand enters the open shelf from the front.  The spherical
         proxy only represents its book contact and therefore ignores the
         bookcase's left side panel. -->
    <exclude body1="hand_proxy" body2="left_bookcase_side"/>
  </contact>
  <worldbody>
    <geom name="shelf_collision" type="box" pos="1.640 0.360 {SHELF_TOP_Z - 0.018:.8f}"
          size="0.350 0.219 0.018" friction="{friction:.5f} 0.005 0.0001"
          solref="0.006 1" solimp="0.96 0.995 0.002" rgba="0.45 0.30 0.18 1"/>
    <geom name="shelf_back_stop" type="box" pos="1.640 0.100 {SHELF_TOP_Z + 0.150:.8f}"
          size="0.350 0.050 0.300" friction="{friction:.5f} 0.005 0.0001"
          solref="0.004 1" solimp="0.97 0.997 0.001"
          rgba="0.45 0.30 0.18 1"/>
    <body name="left_bookcase_side" pos="1.275 0.400 {SHELF_TOP_Z + 0.130:.8f}">
      <geom name="left_bookcase_side_collision" type="box" size="0.008 0.105 0.130"
            friction="{friction:.5f} 0.005 0.0001" rgba="0.45 0.30 0.18 1"/>
    </body>
    <!-- Existing generated upper_leaning_book: represented conservatively as
         a fixed neighbor so the moving row cannot pass through its visual. -->
    <body name="upper_leaning_book_static" pos="1.714 0.400 {SHELF_TOP_Z + 0.123:.8f}">
      <geom name="upper_leaning_book_collision" type="box" size="0.024 0.082 0.123"
            friction="{friction:.5f} 0.005 0.0001" rgba="0.08 0.15 0.31 1"/>
    </body>
    {bodies}
    <body name="hand_proxy" mocap="true" pos="{PUSHED_BOOK_X:.8f} {PUSHER_Y:.8f} {PUSHER_Z:.8f}">
      <geom name="hand_proxy_collision" type="sphere" size="{PUSHER_RADIUS:.8f}"
            friction="0.80 0.005 0.0001" solref="0.004 1"
            solimp="0.97 0.997 0.001" rgba="0.95 0.70 0.30 0.65"/>
    </body>
  </worldbody>
</mujoco>
"""


def geom_name(model: mujoco.MjModel, geom_id: int) -> str:
    return mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, geom_id) or str(geom_id)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--duration", type=float, default=5.0)
    parser.add_argument("--friction", type=float, default=0.58)
    parser.add_argument("--travel", type=float, default=0.115)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    xml_path = args.output / "book_push_model.xml"
    xml_path.write_text(build_xml(args.friction, args.travel))
    model = mujoco.MjModel.from_xml_path(str(xml_path))
    data = mujoco.MjData(model)
    book_body_ids = np.asarray(
        [mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, name) for name in BOOK_NAMES]
    )
    hand_body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "hand_proxy")
    if np.any(book_body_ids < 0) or hand_body_id < 0:
        raise RuntimeError("simulation body lookup failed")

    frame_count = int(round(args.duration * args.fps)) + 1
    times = np.arange(frame_count, dtype=float) / args.fps
    positions = np.empty((frame_count, len(BOOK_NAMES), 3), dtype=float)
    matrices = np.empty((frame_count, len(BOOK_NAMES), 3, 3), dtype=float)
    pusher_positions = np.empty((frame_count, 3), dtype=float)
    pusher_matrices = np.repeat(np.eye(3)[None, :, :], frame_count, axis=0)
    contacts: list[dict] = []
    contact_pairs_seen: set[tuple[str, str]] = set()
    next_frame = 0

    while next_frame < frame_count:
        target_time = times[next_frame]
        while data.time + 1.0e-12 < target_time:
            data.mocap_pos[0] = pusher_position(data.time, args.travel)
            mujoco.mj_step(model, data)
            for contact_index, contact in enumerate(data.contact[: data.ncon]):
                name1 = geom_name(model, int(contact.geom1))
                name2 = geom_name(model, int(contact.geom2))
                pair = tuple(sorted((name1, name2)))
                relevant = "hand_proxy_collision" in pair or (
                    pair[0].startswith("upright_book_")
                    and pair[1].startswith("upright_book_")
                )
                if relevant and pair not in contact_pairs_seen:
                    force = np.zeros(6, dtype=float)
                    mujoco.mj_contactForce(model, data, contact_index, force)
                    contacts.append(
                        {
                            "time_s": float(data.time),
                            "geom1": name1,
                            "geom2": name2,
                            "normal_force_n": float(force[0]),
                        }
                    )
                    contact_pairs_seen.add(pair)
        data.mocap_pos[0] = pusher_position(target_time, args.travel)
        mujoco.mj_forward(model, data)
        positions[next_frame] = data.xpos[book_body_ids]
        matrices[next_frame] = data.xmat[book_body_ids].reshape(-1, 3, 3)
        pusher_positions[next_frame] = data.xpos[hand_body_id]
        next_frame += 1

    local_z_world = matrices[:, :, :, 2]
    tilt_degrees = np.degrees(
        np.arccos(np.clip(np.abs(local_z_world[:, :, 2]), 0.0, 1.0))
    )
    displacements = np.linalg.norm(positions[-1, :, :2] - positions[0, :, :2], axis=1)
    trajectory_path = args.output / "BOOK_PHYSICS_TRAJECTORY.npz"
    np.savez_compressed(
        trajectory_path,
        times=times,
        book_names=np.asarray(BOOK_NAMES),
        book_positions=positions,
        book_matrices=matrices,
        pusher_positions=pusher_positions,
        pusher_matrices=pusher_matrices,
        tilt_degrees=tilt_degrees,
    )
    contacts_path = args.output / "CONTACTS.json"
    contacts_path.write_text(json.dumps(contacts, indent=2) + "\n")
    report = {
        "schema": "bedroom_g1_book_push_physics_v1",
        "physical_scope": "dynamic rigid books, rigid shelf, prescribed kinematic hand proxy",
        "whole_body_robot_dynamics_validated": False,
        "direct_book_pose_resets_or_forces": False,
        "fps": args.fps,
        "duration_s": args.duration,
        "integration_timestep_s": float(model.opt.timestep),
        "book_mass_kg": 0.32,
        "friction_coefficient": args.friction,
        "pusher_radius_m": PUSHER_RADIUS,
        "pusher_travel_m": args.travel,
        "book_names": list(BOOK_NAMES),
        "initial_centers_xyz_m": positions[0].tolist(),
        "final_centers_xyz_m": positions[-1].tolist(),
        "peak_tilt_deg": np.max(tilt_degrees, axis=0).tolist(),
        "final_tilt_deg": tilt_degrees[-1].tolist(),
        "horizontal_displacement_m": displacements.tolist(),
        "first_contacts": contacts,
        "contact_chain_complete": all(
            tuple(sorted((f"upright_book_{index}_collision", f"upright_book_{index + 1}_collision")))
            in contact_pairs_seen
            for index in range(3)
        ),
        "trajectory": str(trajectory_path),
        "trajectory_sha256": sha256(trajectory_path),
        "model_xml": str(xml_path),
        "model_xml_sha256": sha256(xml_path),
    }
    (args.output / "PHYSICS_REPORT.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
