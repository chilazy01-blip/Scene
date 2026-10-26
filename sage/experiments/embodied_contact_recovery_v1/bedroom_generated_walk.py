#!/usr/bin/env python3
"""Run the retained G1 walker inside the project's complete generated bedroom.

The bedroom's accepted visual GLB is kept as the rendering source.  This
module builds a separate MuJoCo execution model from the same bedroom's
collision model, adds the unchanged G1, and records robot visual transforms
for a Blender render against the original GLB.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import types
import xml.etree.ElementTree as ET

import mujoco
import numpy as np


ROOT = Path("/data/wsj/main")
PAYLOAD = (
    ROOT
    / "scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1"
    / "full_body_milestone/feasibility_guard_v4/prepared/payload_data_20261009"
)
NATIVE = PAYLOAD / "native_parallel_12h_20261011"
SOURCE = NATIVE / "branches/A/source"
G1_PACKAGE = (
    PAYLOAD
    / "contact_recovery_run_20261011/generated/development_05/package"
)
BEDROOM = (
    ROOT
    / "scene_runs/codex_trellis_v2/bedroom_composition_detail_20260909_v1"
    / "mainline_full_v2"
)
BEDROOM_COLLISION_XML = BEDROOM / "physics/normal_0.001000/model.xml"
BEDROOM_VISUAL_GLB = BEDROOM / "physics/scene_physics_final.glb"
BEDROOM_LAYOUT = BEDROOM / "physics/layout_plan_physics_final.json"
DEFAULT_OUTPUT = (
    ROOT
    / "scene_runs/codex_trellis_v2/full_bedroom_g1_walk_20261012_v1"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def yaw_quat(yaw: float) -> np.ndarray:
    return np.array([math.cos(yaw / 2), 0.0, 0.0, math.sin(yaw / 2)])


def quaternion_multiply_wxyz(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    lw, lx, ly, lz = left
    rw, rx, ry, rz = right
    return np.array(
        [
            lw * rw - lx * rx - ly * ry - lz * rz,
            lw * rx + lx * rw + ly * rz - lz * ry,
            lw * ry - lx * rz + ly * rw + lz * rx,
            lw * rz + lx * ry - ly * rx + lz * rw,
        ]
    )


def upright_component(qpos: np.ndarray) -> float:
    return float(1.0 - 2.0 * (qpos[4] ** 2 + qpos[5] ** 2))


def base_yaw(qpos: np.ndarray) -> float:
    w, x, y, z = qpos[3:7]
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def wrap_angle(value: float) -> float:
    return (value + math.pi) % (2.0 * math.pi) - math.pi


def command_envelope(value: float, kind: str) -> float:
    """Return a normalized linear or zero-slope cubic command envelope."""
    value = float(np.clip(value, 0.0, 1.0))
    if kind == "linear":
        return value
    if kind == "cubic_smoothstep":
        return value * value * (3.0 - 2.0 * value)
    raise ValueError(f"unknown command envelope: {kind}")


def _prefix_names(element: ET.Element, mesh_names: dict[str, str]) -> None:
    name = element.get("name")
    if name:
        element.set("name", "bedroom_" + name)
    mesh = element.get("mesh")
    if mesh:
        element.set("mesh", mesh_names[mesh])
    for child in element:
        _prefix_names(child, mesh_names)


def build_execution_model(output: Path) -> Path:
    """Merge the complete bedroom collision model with the unchanged G1."""
    root = ET.parse(G1_PACKAGE / "MODEL.xml").getroot()
    asset = root.find("asset")
    world = root.find("worldbody")
    assert asset is not None and world is not None

    # Remove every object that belonged to the sparse study task.  The robot,
    # its two lights, and no scene-specific furniture are retained.
    removed_bodies = {
        "table",
        "table_white",
        "red_block",
        "scene_office_chair",
        "scene_bookcase",
        "scene_floor_lamp",
        "generated_architecture",
    }
    for child in list(world):
        if child.tag == "geom" and child.get("name") == "ground":
            world.remove(child)
        elif child.tag == "camera":
            world.remove(child)
        elif child.tag == "body" and child.get("name") in removed_bodies:
            world.remove(child)

    # Drop visual/collision assets that only served the sparse study.
    for child in list(asset):
        name = child.get("name", "")
        if (
            name.startswith("scene_")
            or name.startswith("architecture_")
            or name in {"table_wood", "table_blue", "red_plastic"}
        ):
            asset.remove(child)

    bedroom_root = ET.parse(BEDROOM_COLLISION_XML).getroot()
    bedroom_asset = bedroom_root.find("asset")
    bedroom_world = bedroom_root.find("worldbody")
    assert bedroom_asset is not None and bedroom_world is not None
    mesh_names: dict[str, str] = {}
    for source_mesh in bedroom_asset.findall("mesh"):
        old = source_mesh.get("name")
        assert old
        copied = deepcopy(source_mesh)
        copied.set("name", "bedroom_" + old)
        mesh_names[old] = copied.get("name")
        asset.append(copied)

    imported_geoms: list[str] = []
    for source_child in list(bedroom_world):
        copied = deepcopy(source_child)
        _prefix_names(copied, mesh_names)
        for geom in ([copied] if copied.tag == "geom" else copied.findall(".//geom")):
            # Preserve the bedroom physics model's declared contact settings
            # explicitly instead of relying on the G1 model's defaults.
            geom.set("friction", ".5 0 0")
            geom.set("margin", "0")
            geom.set("gap", "0")
            geom.set("solref", ".004 1")
            geom.set("solimp", ".95 .99 .001 .5 2")
            geom.set("condim", "3")
            geom.set("group", "3")
            geom.set("rgba", "0 0 0 0")
            imported_geoms.append(geom.get("name"))
        world.append(copied)

    # The rendering camera is handled in Blender, but this camera makes the
    # execution package independently inspectable in MuJoCo.
    ET.SubElement(
        world,
        "camera",
        name="bedroom_execution_view",
        pos="4.5 -3.2 2.2",
        xyaxes="0.95 0.31 0 -0.10 0.31 0.945",
        fovy="48",
    )
    ET.indent(root)
    model_xml = output / "MODEL.xml"
    ET.ElementTree(root).write(model_xml, encoding="unicode")
    write_json(
        output / "MODEL_BINDING.json",
        {
            "schema": "full_bedroom_g1_binding_v1",
            "g1_source_xml": str(G1_PACKAGE / "MODEL.xml"),
            "g1_source_sha256": sha256(G1_PACKAGE / "MODEL.xml"),
            "bedroom_collision_xml": str(BEDROOM_COLLISION_XML),
            "bedroom_collision_sha256": sha256(BEDROOM_COLLISION_XML),
            "bedroom_visual_glb": str(BEDROOM_VISUAL_GLB),
            "bedroom_visual_glb_sha256": sha256(BEDROOM_VISUAL_GLB),
            "bedroom_layout": str(BEDROOM_LAYOUT),
            "bedroom_layout_sha256": sha256(BEDROOM_LAYOUT),
            "removed_sparse_study_bodies": sorted(removed_bodies),
            "bedroom_collision_geom_count": len(imported_geoms),
            "bedroom_collision_geom_names": imported_geoms,
            "bedroom_visuals_in_physics_model": False,
            "render_uses_exact_bedroom_visual_glb": True,
        },
    )
    return model_xml


def install_controller_adapter(output: Path, model_xml: Path):
    os.environ.update(
        NP_ROOT=str(NATIVE),
        NP_JOB=str(output),
        CONTACT_MODEL_XML=str(model_xml),
        CONTACT_NAMED_INITIAL="1",
        CONTACT_STOW_JOINT="right_elbow_joint",
        CONTACT_STOW_OFFSET="-0.21",
    )
    sys.path.insert(0, str(NATIVE / "tools"))
    sys.path.insert(0, str(SOURCE))
    instrument = types.ModuleType("instrument")
    instrument.ACTIVE_TRACE = None
    sys.modules["instrument"] = instrument

    from .target_adapter_r4 import install

    adapter = install("A", "gain_translation", output / "adapter")
    import run

    return run, adapter


def initialize(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    adapter_path: Path,
    initial_qpos: np.ndarray | None = None,
) -> None:
    if initial_qpos is not None:
        if initial_qpos.shape != (model.nq,):
            raise RuntimeError(
                f"initial qpos shape {initial_qpos.shape} != {(model.nq,)}"
            )
        data.qpos[:] = initial_qpos
        data.qvel[:] = 0.0
        data.ctrl[:] = 0.0
        mujoco.mj_forward(model, data)
        return
    adapter = json.loads(adapter_path.read_text())
    data.qpos[:3] = [2.45, 0.86, 0.76]
    data.qpos[3:7] = yaw_quat(0.0)
    for name, value in adapter["initial_angles_by_physical_joint"].items():
        data.qpos[model.jnt_qposadr[model.joint(name).id]] = value
    data.qvel[:] = 0.0
    data.ctrl[:] = 0.0
    mujoco.mj_forward(model, data)


def visual_manifest(model: mujoco.MjModel) -> tuple[list[int], list[dict]]:
    source_root = ET.parse(G1_PACKAGE / "MODEL.xml").getroot()
    mesh_paths = {
        mesh.get("name"): mesh.get("file")
        for mesh in source_root.findall("./asset/mesh")
    }
    geom_to_mesh = {
        geom.get("name"): geom.get("mesh")
        for geom in source_root.findall(".//body[@name='base']//geom")
        if geom.get("type") == "mesh" and geom.get("group") == "1"
    }
    ids: list[int] = []
    rows: list[dict] = []
    for geom_id in range(model.ngeom):
        name = model.geom(geom_id).name
        if name not in geom_to_mesh:
            continue
        mesh_name = geom_to_mesh[name]
        mesh_id = model.mesh(mesh_name).id
        path = Path(mesh_paths[mesh_name])
        if not path.is_absolute():
            path = G1_PACKAGE / path
        assert path.is_file(), path
        ids.append(geom_id)
        rows.append(
            {
                "geom_id": geom_id,
                "geom_name": name,
                "mesh_name": mesh_name,
                "mesh_path": str(path),
                "mesh_sha256": sha256(path),
                "mujoco_mesh_pos": model.mesh_pos[mesh_id].tolist(),
                "mujoco_mesh_quat_wxyz": model.mesh_quat[mesh_id].tolist(),
                "rgba": model.geom_rgba[geom_id].tolist(),
            }
        )
    assert len(ids) == len(geom_to_mesh) and ids
    return ids, rows


def simulate(
    output: Path,
    run_module,
    *,
    envelope: str,
    target_speed: float,
    settle_seconds: float,
    ramp_up_seconds: float,
    target_displacement: float,
    ramp_down_seconds: float,
    final_hold_seconds: float,
    hard_timeout_seconds: float,
    lateral_gain: float,
    yaw_gain: float,
    body_axis: str,
    goal_displacement: float | None,
    goal_tolerance: float,
    initial_qpos: np.ndarray | None,
    initial_state_provenance: dict | None,
    counter_brake_speed: float,
    counter_brake_seconds: float,
) -> dict:
    model = mujoco.MjModel.from_xml_path(str(output / "MODEL.xml"))
    mujoco.mj_saveModel(model, str(output / "MODEL.mjb"))
    data = mujoco.MjData(model)
    initialize(
        model,
        data,
        output / "adapter/ADAPTER.json",
        initial_qpos=initial_qpos,
    )
    initial_base_xyz = data.qpos[:3].copy()
    initial_base_yaw = base_yaw(data.qpos)

    config = json.loads((SOURCE / "model_config.json").read_text())
    policies = [
        run_module.ONNXPolicy(str(SOURCE / f"{name}.onnx"))
        for name in ("walker", "croucher", "rotator")
    ]
    controller = run_module.G1Controller(model, data, *policies, config)
    visual_ids, visual_rows = visual_manifest(model)

    dt = float(model.opt.timestep)
    policy_every = 8
    video_every = 20
    target = controller.default_joint_pos.copy()
    walk_origin = None
    walk_origin_yaw = None
    walk_world_direction = None
    stop_start = None
    stop_start_speed = None
    counter_brake_start = None
    stopped_at = None
    fall_hits = 0
    fell = False
    qpos_states: list[np.ndarray] = []
    visual_positions: list[np.ndarray] = []
    visual_matrices: list[np.ndarray] = []
    timeline: list[dict] = []
    max_penetration = 0.0
    max_contact_force = 0.0
    min_base_height = float(data.qpos[2])
    max_tilt_degrees = 0.0
    tilt_squared_sum = 0.0
    stability_sample_count = 0
    max_base_angular_speed = 0.0
    max_lateral_drift = 0.0
    room_nonfloor_contacts: set[tuple[str, str]] = set()
    floor_contact_samples = 0
    post_stop_max_tilt_degrees = 0.0
    post_stop_min_base_height = float("inf")
    post_stop_max_linear_speed = 0.0
    body_axis_vectors = {
        "forward": np.array([1.0, 0.0]),
        "backward": np.array([-1.0, 0.0]),
        "left": np.array([0.0, 1.0]),
        "right": np.array([0.0, -1.0]),
    }

    for step in range(int(hard_timeout_seconds / dt)):
        now = float(data.time)
        if step % policy_every == 0:
            if now < settle_seconds:
                speed = 0.0
                phase = "settle"
            else:
                if walk_origin is None:
                    walk_origin = data.qpos[:2].copy()
                    walk_origin_yaw = base_yaw(data.qpos)
                    body_to_world = np.array(
                        [
                            [math.cos(walk_origin_yaw), -math.sin(walk_origin_yaw)],
                            [math.sin(walk_origin_yaw), math.cos(walk_origin_yaw)],
                        ]
                    )
                    walk_world_direction = (
                        body_to_world @ body_axis_vectors[body_axis]
                    )
                progress = float(
                    np.dot(data.qpos[:2] - walk_origin, walk_world_direction)
                )
                ramp_up_speed = target_speed * command_envelope(
                    (now - settle_seconds) / ramp_up_seconds, envelope
                )
                if (
                    counter_brake_speed > 0.0
                    and counter_brake_start is None
                    and progress >= target_displacement
                ):
                    counter_brake_start = now
                if counter_brake_start is not None:
                    counter_elapsed = now - counter_brake_start
                    if counter_elapsed < counter_brake_seconds:
                        speed = -counter_brake_speed
                        phase = "counter_brake"
                    else:
                        speed = 0.0
                        phase = "hold"
                        if stopped_at is None:
                            stopped_at = now
                elif stop_start is None and progress >= target_displacement:
                    stop_start = now
                    stop_start_speed = ramp_up_speed
                if counter_brake_start is not None:
                    pass
                elif stop_start is None:
                    speed = ramp_up_speed
                    phase = "ramp_up" if speed < target_speed else "walk"
                else:
                    fraction = 1.0 - command_envelope(
                        (now - stop_start) / ramp_down_seconds, envelope
                    )
                    speed = stop_start_speed * fraction
                    phase = "ramp_down" if fraction > 0.0 else "hold"
                    if fraction == 0.0 and stopped_at is None:
                        stopped_at = now
            body_command = body_axis_vectors[body_axis] * speed
            controller.lin_vel_x = float(body_command[0])
            controller.lin_vel_y = float(body_command[1])
            if walk_origin is None:
                controller.ang_vel_z = 0.0
            elif body_axis in {"forward", "backward"}:
                lateral_error = float(data.qpos[1] - walk_origin[1])
                yaw_error = wrap_angle(base_yaw(data.qpos) - walk_origin_yaw)
                controller.lin_vel_y += float(
                    np.clip(-lateral_gain * lateral_error, -0.08, 0.08)
                )
                controller.ang_vel_z = float(
                    np.clip(-yaw_gain * yaw_error, -0.15, 0.15)
                )
            else:
                controller.ang_vel_z = 0.0
            target = controller.step()

        controller.apply_pd_control(target)
        for actuator_id in range(model.nu):
            if "hand" in (model.actuator(actuator_id).name or ""):
                data.ctrl[actuator_id] = 0.0
        mujoco.mj_step(model, data)

        if data.ncon:
            force = np.empty(6, dtype=float)
            for contact_id in range(data.ncon):
                contact = data.contact[contact_id]
                max_penetration = max(max_penetration, max(0.0, -float(contact.dist)))
                mujoco.mj_contactForce(model, data, contact_id, force)
                max_contact_force = max(
                    max_contact_force, float(np.linalg.norm(force[:3]))
                )
                names = (
                    model.geom(contact.geom1).name or f"geom_{contact.geom1}",
                    model.geom(contact.geom2).name or f"geom_{contact.geom2}",
                )
                bedroom_names = [name for name in names if name.startswith("bedroom_")]
                if "bedroom_floor" in bedroom_names:
                    floor_contact_samples += 1
                elif len(bedroom_names) == 1:
                    room_nonfloor_contacts.add(tuple(sorted(names)))

        up = upright_component(data.qpos)
        tilt = math.degrees(math.acos(float(np.clip(up, -1.0, 1.0))))
        max_tilt_degrees = max(max_tilt_degrees, tilt)
        tilt_squared_sum += tilt * tilt
        stability_sample_count += 1
        max_base_angular_speed = max(
            max_base_angular_speed, float(np.linalg.norm(data.qvel[3:6]))
        )
        if stopped_at is not None:
            post_stop_max_tilt_degrees = max(
                post_stop_max_tilt_degrees, tilt
            )
            post_stop_min_base_height = min(
                post_stop_min_base_height, float(data.qpos[2])
            )
            post_stop_max_linear_speed = max(
                post_stop_max_linear_speed,
                float(np.linalg.norm(data.qvel[:3])),
            )
        if walk_origin is not None:
            max_lateral_drift = max(
                max_lateral_drift, abs(float(data.qpos[1] - walk_origin[1]))
            )
        min_base_height = min(min_base_height, float(data.qpos[2]))
        fall_hits = fall_hits + 1 if data.qpos[2] < 0.40 or up < 0.5 else 0
        if fall_hits >= 80:
            fell = True

        if step % video_every == 0:
            distance = 0.0 if walk_origin is None else float(
                np.linalg.norm(data.qpos[:2] - walk_origin)
            )
            progress = (
                0.0
                if walk_origin is None
                else float(
                    np.dot(
                        data.qpos[:2] - walk_origin,
                        walk_world_direction,
                    )
                )
            )
            qpos_states.append(data.qpos.copy())
            visual_positions.append(data.geom_xpos[visual_ids].copy())
            visual_matrices.append(data.geom_xmat[visual_ids].reshape(-1, 3, 3).copy())
            timeline.append(
                {
                    "time_s": float(data.time),
                    "phase": phase,
                    "distance_m": distance,
                    "projected_progress_m": progress,
                    "base_xyz_m": data.qpos[:3].tolist(),
                    "upright_component": up,
                }
            )

        if fell:
            break
        if stopped_at is not None and float(data.time) - stopped_at >= final_hold_seconds:
            break

    origin = walk_origin if walk_origin is not None else qpos_states[0][:2]
    displacement_xy = data.qpos[:2] - origin
    projected_displacement = (
        float(np.dot(displacement_xy, walk_world_direction))
        if walk_world_direction is not None
        else 0.0
    )
    final_linear_speed = float(np.linalg.norm(data.qvel[:3]))
    endpoint_error = (
        abs(projected_displacement - goal_displacement)
        if goal_displacement is not None
        else None
    )
    displacement_target_met = (
        endpoint_error <= goal_tolerance
        if endpoint_error is not None
        else np.linalg.norm(displacement_xy) >= 0.60
    )
    strict_stop_test = goal_displacement is not None
    task_success = bool(
        not fell
        and displacement_target_met
        and data.qpos[2] >= 0.55
        and upright_component(data.qpos) >= math.cos(math.radians(20.0))
        and final_linear_speed <= (0.10 if strict_stop_test else 0.20)
        and (
            not strict_stop_test
            or (
                stopped_at is not None
                and float(data.time) - stopped_at >= final_hold_seconds - dt
                and post_stop_max_tilt_degrees <= 15.0
                and post_stop_min_base_height >= 0.60
            )
        )
        and not room_nonfloor_contacts
    )
    np.savez_compressed(
        output / "ROBOT_VISUAL_TRAJECTORY.npz",
        qpos=np.asarray(qpos_states),
        positions=np.asarray(visual_positions),
        matrices=np.asarray(visual_matrices),
        times=np.asarray([row["time_s"] for row in timeline]),
    )
    write_json(output / "ROBOT_VISUALS.json", visual_rows)
    report = {
        "schema": "full_generated_bedroom_g1_walk_v1",
        "label": "task_level_visual_demo_not_production_accepted",
        "scene": "own_generator/bedroom_composition_detail/mainline_full_v2",
        "robot": "full_body_unitree_g1",
        "controller": "retained_online_walker_onnx_with_current_actuator_translation",
        "command_profile": {
            "envelope": envelope,
            "target_speed_mps": target_speed,
            "settle_seconds": settle_seconds,
            "ramp_up_seconds": ramp_up_seconds,
            "stop_trigger_displacement_m": target_displacement,
            "ramp_down_seconds": ramp_down_seconds,
            "ramp_down_start_speed_mps": stop_start_speed,
            "final_hold_seconds": final_hold_seconds,
            "lateral_feedback_gain": lateral_gain,
            "yaw_feedback_gain": yaw_gain,
            "body_axis": body_axis,
            "goal_displacement_m": goal_displacement,
            "goal_tolerance_m": goal_tolerance,
            "counter_brake_speed_mps": counter_brake_speed,
            "counter_brake_seconds": counter_brake_seconds,
        },
        "integration": {
            "same_bedroom_visual_glb_as_existing_showcase": True,
            "bedroom_collision_model_loaded_into_g1_physics": True,
            "sparse_study_removed": True,
            "background_compositing_used": False,
            "spawn_xyz_m": initial_base_xyz.tolist(),
            "spawn_yaw_rad": initial_base_yaw,
            "initial_state_reference": initial_state_provenance,
            "bedroom_collision_geom_count": len(
                json.loads((output / "MODEL_BINDING.json").read_text())[
                    "bedroom_collision_geom_names"
                ]
            ),
        },
        "task": {
            "description": "walk through the open foreground corridor and finish upright",
            "target_displacement_m": target_displacement,
            "actual_displacement_xy_m": displacement_xy.tolist(),
            "actual_displacement_m": float(np.linalg.norm(displacement_xy)),
            "actual_projected_displacement_m": projected_displacement,
            "endpoint_error_m": endpoint_error,
            "displacement_target_met": bool(displacement_target_met),
            "task_success": task_success,
            "fell": fell,
            "final_base_height_m": float(data.qpos[2]),
            "final_upright_component": upright_component(data.qpos),
            "final_linear_speed_mps": final_linear_speed,
            "nonfloor_bedroom_contacts": [list(pair) for pair in sorted(room_nonfloor_contacts)],
            "post_stop_hold_duration_s": (
                float(data.time) - stopped_at if stopped_at is not None else 0.0
            ),
            "post_stop_max_base_tilt_deg": post_stop_max_tilt_degrees,
            "post_stop_min_base_height_m": (
                post_stop_min_base_height
                if math.isfinite(post_stop_min_base_height)
                else None
            ),
            "post_stop_max_linear_speed_mps": post_stop_max_linear_speed,
        },
        "diagnostics_not_used_as_strict_production_gates": {
            "max_penetration_m": max_penetration,
            "max_contact_force_N": max_contact_force,
            "max_base_tilt_deg": max_tilt_degrees,
            "rms_base_tilt_deg": math.sqrt(
                tilt_squared_sum / max(1, stability_sample_count)
            ),
            "max_base_angular_speed_rad_s": max_base_angular_speed,
            "max_lateral_drift_m": max_lateral_drift,
            "min_base_height_m": min_base_height,
            "floor_contact_samples": floor_contact_samples,
        },
        "rollout": {
            "physics_steps": step + 1,
            "duration_s": float(data.time),
            "physics_hz": 1.0 / dt,
            "policy_hz": 1.0 / (dt * policy_every),
            "video_fps": 1.0 / (dt * video_every),
            "saved_video_states": len(qpos_states),
        },
        "acceptance": {
            "visual_demo_generated": False,
            "strict_physics_gate_applied": strict_stop_test,
            "production_accepted": False,
            "learning_validated": False,
        },
        "provenance": {
            "execution_model": str(output / "MODEL.mjb"),
            "execution_model_sha256": sha256(output / "MODEL.mjb"),
            "bedroom_visual_glb": str(BEDROOM_VISUAL_GLB),
            "bedroom_visual_glb_sha256": sha256(BEDROOM_VISUAL_GLB),
            "bedroom_collision_xml": str(BEDROOM_COLLISION_XML),
            "bedroom_collision_xml_sha256": sha256(BEDROOM_COLLISION_XML),
            "walker_onnx_sha256": sha256(SOURCE / "walker.onnx"),
        },
        "timeline": timeline,
    }
    write_json(output / "REPORT.json", report)
    if not task_success:
        raise RuntimeError("G1 did not complete the relaxed bedroom walking task")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", nargs="?", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--envelope", choices=("linear", "cubic_smoothstep"), default="linear"
    )
    parser.add_argument("--target-speed", type=float, default=0.42)
    parser.add_argument("--settle-seconds", type=float, default=1.5)
    parser.add_argument("--ramp-up-seconds", type=float, default=1.0)
    parser.add_argument("--target-displacement", type=float, default=0.72)
    parser.add_argument("--ramp-down-seconds", type=float, default=0.8)
    parser.add_argument("--final-hold-seconds", type=float, default=2.0)
    parser.add_argument("--hard-timeout-seconds", type=float, default=12.0)
    parser.add_argument("--lateral-gain", type=float, default=0.0)
    parser.add_argument("--yaw-gain", type=float, default=0.0)
    parser.add_argument(
        "--body-axis",
        choices=("forward", "backward", "left", "right"),
        default="forward",
    )
    parser.add_argument("--goal-displacement", type=float)
    parser.add_argument("--goal-tolerance", type=float, default=0.02)
    parser.add_argument("--initial-state-run", type=Path)
    parser.add_argument("--initial-state-time", type=float, default=2.0)
    parser.add_argument("--spawn-x", type=float, default=1.68)
    parser.add_argument("--spawn-y", type=float, default=0.85)
    parser.add_argument("--spawn-yaw-deg", type=float, default=-90.0)
    parser.add_argument("--counter-brake-speed", type=float, default=0.0)
    parser.add_argument("--counter-brake-seconds", type=float, default=0.0)
    args = parser.parse_args()
    if args.goal_displacement is not None and args.goal_displacement <= 0.0:
        parser.error("--goal-displacement must be positive")
    if args.goal_tolerance <= 0.0:
        parser.error("--goal-tolerance must be positive")
    if args.counter_brake_speed < 0.0:
        parser.error("--counter-brake-speed must be nonnegative")
    if args.counter_brake_speed > 0.0 and args.counter_brake_seconds <= 0.0:
        parser.error("positive counter brake requires --counter-brake-seconds")
    output = args.output
    output.mkdir(parents=True, exist_ok=False)
    model_xml = build_execution_model(output)
    run_module, adapter = install_controller_adapter(output, model_xml)
    write_json(output / "ADAPTER_SUMMARY.json", adapter)
    initial_qpos = None
    initial_state_provenance = None
    if args.initial_state_run is not None:
        trajectory_path = args.initial_state_run / "ROBOT_VISUAL_TRAJECTORY.npz"
        trajectory = np.load(trajectory_path)
        state_index = int(
            np.argmin(np.abs(trajectory["times"] - args.initial_state_time))
        )
        initial_qpos = trajectory["qpos"][state_index].copy()
        original_yaw = base_yaw(initial_qpos)
        target_yaw = math.radians(args.spawn_yaw_deg)
        initial_qpos[3:7] = quaternion_multiply_wxyz(
            yaw_quat(target_yaw - original_yaw), initial_qpos[3:7]
        )
        initial_qpos[:2] = [args.spawn_x, args.spawn_y]
        initial_state_provenance = {
            "run": str(args.initial_state_run),
            "trajectory": str(trajectory_path),
            "trajectory_sha256": sha256(trajectory_path),
            "requested_time_s": args.initial_state_time,
            "source_frame_index": state_index,
            "source_time_s": float(trajectory["times"][state_index]),
            "transformed_base_xyz_m": initial_qpos[:3].tolist(),
            "transformed_base_quaternion_wxyz": initial_qpos[3:7].tolist(),
        }
    report = simulate(
        output,
        run_module,
        envelope=args.envelope,
        target_speed=args.target_speed,
        settle_seconds=args.settle_seconds,
        ramp_up_seconds=args.ramp_up_seconds,
        target_displacement=args.target_displacement,
        ramp_down_seconds=args.ramp_down_seconds,
        final_hold_seconds=args.final_hold_seconds,
        hard_timeout_seconds=args.hard_timeout_seconds,
        lateral_gain=args.lateral_gain,
        yaw_gain=args.yaw_gain,
        body_axis=args.body_axis,
        goal_displacement=args.goal_displacement,
        goal_tolerance=args.goal_tolerance,
        initial_qpos=initial_qpos,
        initial_state_provenance=initial_state_provenance,
        counter_brake_speed=args.counter_brake_speed,
        counter_brake_seconds=args.counter_brake_seconds,
    )
    print(json.dumps({"task": report["task"], "rollout": report["rollout"]}, indent=2))


if __name__ == "__main__":
    main()
