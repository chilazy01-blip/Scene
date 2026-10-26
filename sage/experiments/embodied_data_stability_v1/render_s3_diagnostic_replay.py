"""Render an offline diagnostic replay from an S3 privileged state stream.

This command never advances physics.  It restores recorded generalized state
into the pinned Source-A model, runs position/kinematics reconstruction, and
writes derived review videos plus an integrity manifest.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Iterable

from .audit_candidates import write_json_atomic
from .run_source_a_native import DEFAULT_SOURCE_A_RUN
from .trajectory_capture import sha256_file


DEFAULT_S3_EPISODE = Path(
    "/data/wsj/main/scene_runs/codex_trellis_v2/"
    "embodied_data_stability_s3_20261014_v1/source_a_task_smoke_01"
)

FAILURE_WINDOWS = (
    (27.0, 31.0, "grasp: hand-object penetration"),
    (82.0, 86.0, "untuck/place-pre: blue-table clearance"),
    (106.0, 110.0, "release: hand-object penetration"),
)


def _load_sweep(source: Path) -> Any:
    spec = importlib.util.spec_from_file_location("s3_replay_sweep", source / "eval/sweep.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load Source-A sweep module")
    sweep = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sweep)
    return sweep


def _body_label(model: Any, mujoco: Any, geom_id: int) -> str:
    geom = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, geom_id)
    body_id = int(model.geom_bodyid[geom_id])
    body = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, body_id)
    return geom or body or f"geom_{geom_id}"


def _deepest_pair(model: Any, data: Any, mujoco: Any) -> tuple[float, str]:
    if not data.ncon:
        return 0.0, "none"
    contact = min(data.contact, key=lambda item: float(item.dist))
    left = _body_label(model, mujoco, int(contact.geom1))
    right = _body_label(model, mujoco, int(contact.geom2))
    return float(contact.dist), f"{left} <-> {right}"


def _phase_at(events: list[dict[str, Any]], time_s: float) -> str:
    phase = "start"
    for event in events:
        if float(event["sim_time_s"]) > time_s:
            break
        phase = str(event["phase"])
    return phase


def render_replay(
    episode_dir: Path,
    output_dir: Path,
    source_a_run: Path,
    reuse_overview: bool = False,
) -> dict[str, Any]:
    import cv2
    import mujoco
    import numpy as np

    source = source_a_run / "branches" / "A" / "source"
    sys.path.insert(0, str(source))
    from ik import pipeline

    case = json.loads((episode_dir / "CASE_DRAW.json").read_text(encoding="utf-8"))
    phase_doc = json.loads((episode_dir / "PHASE_EVENTS.json").read_text(encoding="utf-8"))
    phase_events = phase_doc["events"]

    model, data, _controller = pipeline.ep.build_sim(spawn=case["spawn"])
    pipeline.randomize_scene(
        model,
        data,
        spawn_yaw=np.radians(case["spawn_yaw_deg"]),
        cyl_xy=case["cyl_xy"],
        cyl_mass_scale=case["cyl_mass_scale"],
        cyl_friction=case["cyl_friction"],
        brown_dz=case["brown_dz"],
        blue_dz=case["blue_dz"],
        brown_dxy=case["brown_dxy"],
        blue_dxy=case["blue_dxy"],
    )

    state_path = episode_dir / "state_stream" / "privileged_state.npz"
    with np.load(state_path, allow_pickle=False) as archive:
        times = archive["sim_time_s"].copy()
        qpos = archive["qpos"].copy()
        qvel = archive["qvel"].copy()
        ctrl = archive["ctrl"].copy()
        min_distances = archive["min_contact_distance_m"].copy()
        max_forces = archive["max_contact_force_n"].copy()
    if qpos.shape[1] != model.nq or qvel.shape[1] != model.nv or ctrl.shape[1] != model.nu:
        raise RuntimeError("state stream dimensions do not match reconstructed model")

    object_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "red_block")
    pelvis_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "pelvis")
    if object_id < 0 or pelvis_id < 0:
        raise RuntimeError("required replay bodies are missing")

    output_dir.mkdir(parents=True, exist_ok=reuse_overview)
    renderer = mujoco.Renderer(model, height=360, width=480)
    close_camera = mujoco.MjvCamera()
    close_camera.type = mujoco.mjtCamera.mjCAMERA_FREE
    close_camera.fixedcamid = -1
    close_camera.distance = 0.82
    close_camera.azimuth = 132.0
    close_camera.elevation = -18.0

    def restore(index: int) -> tuple[float, str]:
        data.qpos[:] = qpos[index]
        data.qvel[:] = qvel[index]
        data.ctrl[:] = ctrl[index]
        data.time = float(times[index])
        mujoco.mj_forward(model, data)
        return _deepest_pair(model, data, mujoco)

    def frame(index: int, window_label: str = "full trajectory") -> Any:
        reconstructed_distance, pair = restore(index)
        renderer.update_scene(data, camera="side_view")
        global_rgb = renderer.render().copy()
        object_position = data.xpos[object_id]
        pelvis_position = data.xpos[pelvis_id]
        close_camera.lookat[:] = 0.78 * object_position + 0.22 * pelvis_position
        renderer.update_scene(data, camera=close_camera)
        close_rgb = renderer.render().copy()
        canvas = np.concatenate((global_rgb, close_rgb), axis=1)
        canvas = cv2.cvtColor(canvas, cv2.COLOR_RGB2BGR)
        time_s = float(times[index])
        phase = _phase_at(phase_events, time_s)
        penetration_mm = max(0.0, -float(min_distances[index]) * 1000.0)
        carry_window = 82.0 <= time_s <= 86.0
        failed_penetration = penetration_mm > 10.0
        color = (20, 40, 190) if failed_penetration or carry_window else (35, 35, 35)
        cv2.rectangle(canvas, (0, 0), (canvas.shape[1], 70), color, -1)
        cv2.putText(
            canvas,
            f"t={time_s:6.2f}s  phase={phase}  replay={window_label}",
            (12, 25),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.58,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            canvas,
            f"deepest={penetration_mm:5.1f} mm  force={float(max_forces[index]):6.1f} N  pair={pair}",
            (12, 52),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        if carry_window:
            cv2.putText(
                canvas,
                "CARRY-CLEARANCE FAILURE WINDOW: recorded minimum -7.7 mm",
                (470, 345),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.43,
                (0, 0, 255),
                1,
                cv2.LINE_AA,
            )
        return canvas

    def write_video(path: Path, indices: list[int], fps: float, label_for: Any) -> None:
        writer = cv2.VideoWriter(
            str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (960, 360)
        )
        if not writer.isOpened():
            raise RuntimeError(f"could not open video writer: {path}")
        try:
            for index in indices:
                writer.write(frame(index, label_for(float(times[index]))))
        finally:
            writer.release()

    overview_indices = list(range(0, len(times), 20))
    if overview_indices[-1] != len(times) - 1:
        overview_indices.append(len(times) - 1)
    overview_path = output_dir / "s3_full_replay_4x.mp4"
    if reuse_overview:
        if not overview_path.is_file() or overview_path.stat().st_size <= 1024:
            raise RuntimeError("reusable overview is absent or incomplete")
    else:
        write_video(overview_path, overview_indices, 10.0, lambda _time: "4x overview")

    key_times = (28.58, 45.58, 83.95, 84.75, 107.78, 120.58)
    key_frames = []
    rendered_key_frames: list[Any] = []
    for time_s in key_times:
        index = int(np.abs(times - time_s).argmin())
        path = output_dir / f"key_{float(times[index]):07.2f}s.png"
        rendered = frame(index, "key evidence")
        cv2.imwrite(str(path), rendered)
        rendered_key_frames.append(rendered)
        key_frames.append(
            {"time_s": float(times[index]), "path": path.name, "sha256": sha256_file(path)}
        )
    key_video_path = output_dir / "s3_failure_keyframes.mp4"
    key_writer = cv2.VideoWriter(
        str(key_video_path), cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (960, 360)
    )
    if not key_writer.isOpened():
        raise RuntimeError(f"could not open video writer: {key_video_path}")
    try:
        for rendered in rendered_key_frames:
            for _ in range(15):
                key_writer.write(rendered)
    finally:
        key_writer.release()
    renderer.close()

    result = json.loads((episode_dir / "S3_RESULT.json").read_text(encoding="utf-8"))
    manifest = {
        "schema": "embodied-s3-offline-diagnostic-replay/v1",
        "source_episode": str(episode_dir),
        "source_s3_result_sha256": sha256_file(episode_dir / "S3_RESULT.json"),
        "source_privileged_state_sha256": sha256_file(state_path),
        "physics_advanced": False,
        "render_basis": "recorded qpos/qvel/ctrl restored into the pinned randomized Source-A model",
        "state_sample_period_s": 0.02,
        "classification_unchanged": result["classification"],
        "videos": {
            "overview_4x": {
                "path": overview_path.name,
                "fps": 10.0,
                "frames": len(overview_indices),
                "sha256": sha256_file(overview_path),
            },
            "failure_keyframes": {
                "path": key_video_path.name,
                "fps": 10.0,
                "frames": len(rendered_key_frames) * 15,
                "sha256": sha256_file(key_video_path),
                "windows": [
                    {"start_s": start, "end_s": end, "label": label}
                    for start, end, label in FAILURE_WINDOWS
                ],
            },
        },
        "key_frames": key_frames,
    }
    write_json_atomic(output_dir / "MANIFEST.json", manifest)
    return manifest


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episode-dir", type=Path, default=DEFAULT_S3_EPISODE)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--source-a-run", type=Path, default=DEFAULT_SOURCE_A_RUN)
    parser.add_argument(
        "--reuse-overview",
        action="store_true",
        help="reuse an already completed s3_full_replay_4x.mp4 and render key evidence only",
    )
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    manifest = render_replay(
        args.episode_dir,
        args.output_dir,
        args.source_a_run,
        reuse_overview=args.reuse_overview,
    )
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
