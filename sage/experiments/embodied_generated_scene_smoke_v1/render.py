"""Offline-render the recorded generated-scene trajectory without stepping physics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable

from .common import RUN_ROOT, read_json, sha256, write_json
from .runtime import geom_label


def _phase_at(events: list[dict[str, Any]], time_s: float) -> str:
    phase = "start"
    for event in events:
        if float(event["sim_time_s"]) > time_s:
            break
        phase = str(event["phase"])
    return phase


def _deepest_pair(model: Any, data: Any, mujoco: Any) -> str:
    if not data.ncon:
        return "none"
    contact = min(data.contact, key=lambda row: float(row.dist))
    return " <-> ".join(
        (
            geom_label(model, mujoco, int(contact.geom1)),
            geom_label(model, mujoco, int(contact.geom2)),
        )
    )


def render(run_root: Path) -> dict[str, Any]:
    import cv2
    import mujoco
    import numpy as np

    trajectory = run_root / "trajectory_01"
    output = trajectory / "replay"
    output.mkdir(exist_ok=False)
    model_path = run_root / "model/MODEL.xml"
    model = mujoco.MjModel.from_xml_path(str(model_path))
    data = mujoco.MjData(model)
    state_path = trajectory / "state_stream/privileged_state.npz"
    with np.load(state_path, allow_pickle=False) as archive:
        times = archive["sim_time_s"].copy()
        qpos = archive["qpos"].copy()
        qvel = archive["qvel"].copy()
        ctrl = archive["ctrl"].copy()
        min_distances = archive["min_contact_distance_m"].copy()
        max_forces = archive["max_contact_force_n"].copy()
    if qpos.shape[1:] != (model.nq,) or qvel.shape[1:] != (model.nv,):
        raise RuntimeError("recorded state dimensions do not match generated model")
    events = read_json(trajectory / "PHASE_EVENTS.json")["events"]
    result = read_json(trajectory / "RESULT.json")
    object_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "red_block")
    pelvis_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "pelvis")

    renderer = mujoco.Renderer(model, height=360, width=480)
    close_camera = mujoco.MjvCamera()
    close_camera.type = mujoco.mjtCamera.mjCAMERA_FREE
    close_camera.fixedcamid = -1
    close_camera.distance = 0.82
    close_camera.azimuth = 132.0
    close_camera.elevation = -18.0

    def restore(index: int) -> None:
        data.qpos[:] = qpos[index]
        data.qvel[:] = qvel[index]
        data.ctrl[:] = ctrl[index]
        data.time = float(times[index])
        mujoco.mj_forward(model, data)

    def frame(index: int, label: str) -> Any:
        restore(index)
        renderer.update_scene(data, camera="side_view")
        global_rgb = renderer.render().copy()
        close_camera.lookat[:] = 0.78 * data.xpos[object_id] + 0.22 * data.xpos[pelvis_id]
        renderer.update_scene(data, camera=close_camera)
        close_rgb = renderer.render().copy()
        canvas = cv2.cvtColor(
            np.concatenate((global_rgb, close_rgb), axis=1), cv2.COLOR_RGB2BGR
        )
        time_s = float(times[index])
        phase = _phase_at(events, time_s)
        penetration_mm = max(0.0, -float(min_distances[index]) * 1000.0)
        failed = penetration_mm > 10.0
        color = (24, 40, 180) if failed else (32, 32, 32)
        cv2.rectangle(canvas, (0, 0), (canvas.shape[1], 70), color, -1)
        cv2.putText(
            canvas,
            f"OWN GENERATED SCENE  t={time_s:6.2f}s  phase={phase}  {label}",
            (12, 25),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.52,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            canvas,
            f"deepest={penetration_mm:5.1f} mm  force={float(max_forces[index]):6.1f} N  pair={_deepest_pair(model, data, mujoco)}",
            (12, 52),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.43,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        return canvas

    indices = list(range(0, len(times), 20))
    if indices[-1] != len(times) - 1:
        indices.append(len(times) - 1)
    video_path = output / "generated_scene_full_replay_4x_mp4v.mp4"
    writer = cv2.VideoWriter(
        str(video_path), cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (960, 360)
    )
    if not writer.isOpened():
        raise RuntimeError("could not open replay video writer")
    try:
        for index in indices:
            writer.write(frame(index, "4x replay"))
    finally:
        writer.release()

    peak_time = float(result["contact_diagnostics"]["peak"]["sim_time_s"])
    requested_times = [0.02, 28.58, peak_time, 71.83, 99.48, 109.66, 124.16]
    keyframes = []
    for requested in requested_times:
        index = int(np.abs(times - requested).argmin())
        path = output / f"key_{float(times[index]):07.2f}s.png"
        cv2.imwrite(str(path), frame(index, "key evidence"))
        keyframes.append(
            {
                "requested_time_s": requested,
                "recorded_time_s": float(times[index]),
                "path": path.name,
                "sha256": sha256(path),
            }
        )
    renderer.close()
    manifest = {
        "schema": "embodied-generated-scene-offline-replay/v1",
        "physics_advanced": False,
        "render_basis": "recorded qpos/qvel/ctrl restored into generated MODEL.xml",
        "model_sha256": sha256(model_path),
        "state_sha256": sha256(state_path),
        "video": {
            "path": video_path.name,
            "codec": "mp4v intermediate",
            "fps": 10.0,
            "frames": len(indices),
            "sha256": sha256(video_path),
        },
        "keyframes": keyframes,
        "render_passes": len(indices) * 2 + len(keyframes) * 2,
        "production_accepted": False,
    }
    write_json(output / "MANIFEST.json", manifest)
    print(json.dumps(manifest, sort_keys=True))
    return manifest


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, default=RUN_ROOT)
    args = parser.parse_args(argv)
    render(args.run_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

