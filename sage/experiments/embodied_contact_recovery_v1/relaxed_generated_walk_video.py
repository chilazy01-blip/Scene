#!/usr/bin/env python3
"""Render a task-level G1 walking demo in an existing generated scene.

This intentionally does not use the project's production physics gates as
episode abort conditions.  Penetration and contact force are still measured
and disclosed in the report; only a sustained fall aborts the rollout.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import types
from fractions import Fraction
from pathlib import Path

import av
import cv2
import mujoco
import numpy as np


ROOT = Path(
    "/data/wsj/main/scene_runs/codex_trellis_v2/"
    "embodied_stretch_ai_admission_20260926_v1/full_body_milestone/"
    "feasibility_guard_v4/prepared/payload_data_20261009"
)
NATIVE = ROOT / "native_parallel_12h_20261011"
GENERATED = ROOT / "contact_recovery_run_20261011/generated/development_05/package"
SOURCE = NATIVE / "branches/A/source"
DEFAULT_OUTPUT = Path(
    "/data/wsj/main/scene_runs/codex_trellis_v2/"
    "relaxed_generated_g1_walk_20261012_v1"
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


def upright_component(qpos: np.ndarray) -> float:
    return float(1.0 - 2.0 * (qpos[4] ** 2 + qpos[5] ** 2))


def install_controller_adapter(output: Path):
    os.environ.update(
        NP_ROOT=str(NATIVE),
        NP_JOB=str(output),
        CONTACT_MODEL_XML=str(GENERATED / "MODEL.xml"),
        CONTACT_NAMED_INITIAL="1",
        CONTACT_STOW_JOINT="right_elbow_joint",
        CONTACT_STOW_OFFSET="-0.21",
    )
    sys.path.insert(0, str(NATIVE / "tools"))
    sys.path.insert(0, str(SOURCE))

    # The adapter logs optional trace channels through this module.  This demo
    # records its own compact telemetry and deliberately does not create a
    # production trace.
    instrument = types.ModuleType("instrument")
    instrument.ACTIVE_TRACE = None
    sys.modules["instrument"] = instrument

    from .target_adapter_r4 import install

    adapter = install("A", "gain_translation", output / "adapter")
    import run

    return run, adapter


def initialize(model: mujoco.MjModel, data: mujoco.MjData, adapter_path: Path) -> None:
    preflight = json.loads((GENERATED / "TASK_INITIALIZATION_PREFLIGHT.json").read_text())
    adapter = json.loads(adapter_path.read_text())
    pose = np.asarray(preflight["initial_base_pose"], dtype=float)
    data.qpos[:3] = pose[:3]
    data.qpos[3:7] = yaw_quat(float(preflight["effective_kwargs"]["spawn_yaw"]))
    for name, value in adapter["initial_angles_by_physical_joint"].items():
        joint = model.joint(name)
        data.qpos[model.jnt_qposadr[joint.id]] = value
    object_joint = model.joint("red_block_joint")
    object_qpos = model.jnt_qposadr[object_joint.id]
    data.qpos[object_qpos : object_qpos + 3] = preflight["initial_cylinder_xyz"]
    data.qpos[object_qpos + 3 : object_qpos + 7] = [1.0, 0.0, 0.0, 0.0]
    data.qvel[:] = 0.0
    data.ctrl[:] = 0.0
    mujoco.mj_forward(model, data)


def simulate(output: Path, run_module) -> tuple[mujoco.MjModel, list[np.ndarray], dict]:
    model = mujoco.MjModel.from_binary_path(str(GENERATED / "MODEL.mjb"))
    data = mujoco.MjData(model)
    initialize(model, data, output / "adapter/ADAPTER.json")

    config = json.loads((SOURCE / "model_config.json").read_text())
    policies = [
        run_module.ONNXPolicy(str(SOURCE / f"{name}.onnx"))
        for name in ("walker", "croucher", "rotator")
    ]
    controller = run_module.G1Controller(model, data, *policies, config)

    dt = float(model.opt.timestep)
    policy_every = 8
    video_every = 20
    target_speed = 0.50
    settle_seconds = 1.5
    ramp_up_seconds = 1.0
    target_displacement = 0.62
    ramp_down_seconds = 0.8
    final_hold_seconds = 2.0
    hard_timeout_seconds = 12.0

    target = controller.default_joint_pos.copy()
    walk_origin = None
    stop_start = None
    stopped_at = None
    fall_hits = 0
    fell = False
    states: list[np.ndarray] = []
    timeline = []
    max_penetration = 0.0
    max_contact_force = 0.0
    max_tilt_degrees = 0.0
    min_base_height = float(data.qpos[2])
    base_start = data.qpos[:3].copy()

    max_steps = int(hard_timeout_seconds / dt)
    for step in range(max_steps):
        now = float(data.time)
        if step % policy_every == 0:
            if now < settle_seconds:
                speed = 0.0
                phase = "settle"
            else:
                if walk_origin is None:
                    walk_origin = data.qpos[:2].copy()
                displacement = float(np.linalg.norm(data.qpos[:2] - walk_origin))
                if stop_start is None and displacement >= target_displacement:
                    stop_start = now
                if stop_start is None:
                    speed = target_speed * min(1.0, (now - settle_seconds) / ramp_up_seconds)
                    phase = "ramp_up" if speed < target_speed else "walk"
                else:
                    fraction = max(0.0, 1.0 - (now - stop_start) / ramp_down_seconds)
                    speed = target_speed * fraction
                    phase = "ramp_down" if fraction > 0.0 else "hold"
                    if fraction == 0.0 and stopped_at is None:
                        stopped_at = now
            controller.lin_vel_x = float(speed)
            controller.lin_vel_y = 0.0
            controller.ang_vel_z = 0.0
            target = controller.step()

        controller.apply_pd_control(target)
        for actuator_id in range(model.nu):
            if "hand" in (model.actuator(actuator_id).name or ""):
                data.ctrl[actuator_id] = 0.0
        mujoco.mj_step(model, data)

        if data.ncon:
            max_penetration = max(
                max_penetration,
                max(0.0, max(-float(data.contact[i].dist) for i in range(data.ncon))),
            )
            force = np.empty(6, dtype=float)
            for contact_id in range(data.ncon):
                mujoco.mj_contactForce(model, data, contact_id, force)
                max_contact_force = max(max_contact_force, float(np.linalg.norm(force[:3])))

        up = upright_component(data.qpos)
        tilt = math.degrees(math.acos(float(np.clip(up, -1.0, 1.0))))
        max_tilt_degrees = max(max_tilt_degrees, tilt)
        min_base_height = min(min_base_height, float(data.qpos[2]))
        if data.qpos[2] < 0.40 or up < 0.5:
            fall_hits += 1
        else:
            fall_hits = 0
        if fall_hits >= 80:  # 0.2 s sustained at 400 Hz
            fell = True

        if step % video_every == 0:
            if now < settle_seconds:
                frame_phase = "settle"
            elif stop_start is None:
                frame_phase = "walk"
            elif stopped_at is None:
                frame_phase = "ramp_down"
            else:
                frame_phase = "hold"
            distance = 0.0 if walk_origin is None else float(
                np.linalg.norm(data.qpos[:2] - walk_origin)
            )
            states.append(data.qpos.copy())
            timeline.append(
                {
                    "time_s": float(data.time),
                    "phase": frame_phase,
                    "distance_m": distance,
                    "base_height_m": float(data.qpos[2]),
                    "upright_component": up,
                }
            )

        if fell:
            break
        if stopped_at is not None and float(data.time) - stopped_at >= final_hold_seconds:
            break

    displacement_xy = (data.qpos[:2] - (walk_origin if walk_origin is not None else base_start[:2]))
    final_linear_speed = float(np.linalg.norm(data.qvel[:3]))
    task_success = bool(
        not fell
        and np.linalg.norm(displacement_xy) >= 0.50
        and data.qpos[2] >= 0.55
        and upright_component(data.qpos) >= math.cos(math.radians(20.0))
        and final_linear_speed <= 0.20
    )
    report = {
        "schema": "relaxed_generated_scene_walk_demo_v1",
        "label": "task_level_visual_demo_not_production_accepted",
        "scene": "own_generator/development_05/modern_study",
        "robot": "full_body_unitree_g1",
        "controller": "retained_online_walker_onnx_with_current_actuator_translation",
        "source_environment_used": False,
        "generated_scene_dynamic_physics": True,
        "task": {
            "description": "walk forward at least 0.50 m and finish upright",
            "target_displacement_m": target_displacement,
            "actual_displacement_xy_m": displacement_xy.tolist(),
            "actual_displacement_m": float(np.linalg.norm(displacement_xy)),
            "task_success": task_success,
            "fell": fell,
            "final_base_height_m": float(data.qpos[2]),
            "final_upright_component": upright_component(data.qpos),
            "final_linear_speed_mps": final_linear_speed,
        },
        "disclosed_diagnostics_not_used_as_abort_gates": {
            "max_penetration_m": max_penetration,
            "max_contact_force_N": max_contact_force,
            "max_base_tilt_deg": max_tilt_degrees,
            "min_base_height_m": min_base_height,
        },
        "rollout": {
            "physics_steps": step + 1,
            "duration_s": float(data.time),
            "physics_hz": 1.0 / dt,
            "policy_hz": 1.0 / (dt * policy_every),
            "video_fps": 1.0 / (dt * video_every),
            "saved_video_states": len(states),
        },
        "acceptance": {
            "visual_demo_generated": False,
            "strict_physics_gate_applied": False,
            "production_accepted": False,
            "learning_validated": False,
        },
        "provenance": {
            "generated_model": str(GENERATED / "MODEL.mjb"),
            "generated_model_sha256": sha256(GENERATED / "MODEL.mjb"),
            "generated_scene_glb": str(GENERATED.parent / "generator/scene_codex_trellis_v2.glb"),
            "walker_onnx_sha256": sha256(SOURCE / "walker.onnx"),
        },
        "timeline": timeline,
    }
    np.savez_compressed(output / "ROLLOUT_STATES.npz", qpos=np.asarray(states))
    write_json(output / "REPORT.json", report)
    return model, states, report


def annotate(frame: np.ndarray, row: dict) -> np.ndarray:
    image = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    overlay = image.copy()
    cv2.rectangle(overlay, (16, 14), (610, 92), (18, 18, 18), -1)
    cv2.addWeighted(overlay, 0.62, image, 0.38, 0.0, image)
    cv2.putText(
        image,
        "Generated study | Full-body G1 walking",
        (30, 43),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.70,
        (245, 245, 245),
        2,
        cv2.LINE_AA,
    )
    cv2.putText(
        image,
        f"relaxed demo  |  {row['phase']}  |  {row['time_s']:.1f}s  |  {row['distance_m']:.2f}m",
        (30, 75),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.52,
        (120, 220, 255),
        1,
        cv2.LINE_AA,
    )
    return image


def render(output: Path, model: mujoco.MjModel, states: list[np.ndarray], report: dict) -> None:
    # The generated package intentionally retains the source model's 640 px
    # offscreen framebuffer cap, so keep the delivery inside that contract.
    width, height = 640, 480
    data = mujoco.MjData(model)
    renderer = mujoco.Renderer(model, height=height, width=width)
    video = output / "generated_study_g1_walk_relaxed.mp4"
    container = av.open(str(video), "w", format="mp4", options={"movflags": "+faststart"})
    stream = container.add_stream("libx264", rate=20)
    stream.width = width
    stream.height = height
    stream.pix_fmt = "yuv420p"
    stream.options = {"crf": "18", "preset": "medium", "profile": "high"}
    samples = []
    sample_indices = set(np.linspace(0, len(states) - 1, 6, dtype=int).tolist())
    try:
        for index, qpos in enumerate(states):
            data.qpos[:] = qpos
            data.qvel[:] = 0.0
            mujoco.mj_forward(model, data)
            renderer.update_scene(data, camera="side_view")
            rgb = renderer.render().copy()
            bgr = annotate(rgb, report["timeline"][index])
            frame = av.VideoFrame.from_ndarray(bgr, format="bgr24")
            frame.pts = index
            frame.time_base = Fraction(1, 20)
            for packet in stream.encode(frame):
                container.mux(packet)
            if index in sample_indices:
                samples.append(bgr)
    finally:
        for packet in stream.encode():
            container.mux(packet)
        container.close()
        renderer.close()

    thumb_width, thumb_height = 320, 240
    thumbs = [cv2.resize(frame, (thumb_width, thumb_height)) for frame in samples]
    sheet = np.vstack([np.hstack(thumbs[:3]), np.hstack(thumbs[3:6])])
    cv2.imwrite(str(output / "contact_sheet.png"), sheet)

    report["acceptance"]["visual_demo_generated"] = True
    report["video"] = {
        "path": str(video),
        "sha256": sha256(video),
        "bytes": video.stat().st_size,
        "codec": "h264/yuv420p",
        "resolution": [width, height],
        "fps": 20,
        "frames": len(states),
    }
    write_json(output / "REPORT.json", report)


def main() -> None:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT
    output.mkdir(parents=True, exist_ok=False)
    run_module, adapter = install_controller_adapter(output)
    write_json(output / "ADAPTER_SUMMARY.json", adapter)
    model, states, report = simulate(output, run_module)
    if not report["task"]["task_success"]:
        raise RuntimeError("walking rollout did not satisfy the relaxed task-level success predicate")
    render(output, model, states, report)
    print(json.dumps({"video": report.get("video"), "task": report["task"]}, indent=2))


if __name__ == "__main__":
    main()
