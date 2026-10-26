"""Render the full official G1 from actual native physical traces, never proxies."""

import argparse
from pathlib import Path
from fractions import Fraction
import time
import numpy as np
from .protocol import require_motion_protocol
from .dynamics_replay import rows
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.audit_candidates import sha256_file
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def run(root, episode, inspect=False, diagnostic=False):
    import mujoco
    import cv2
    import av

    require_motion_protocol(root)
    report = read_bound_json(episode / "REPORT.json")
    audit = read_bound_json(episode / "AUDIT.json")
    assert report["trace"]["sha256"] == sha256_file(Path(report["trace"]["path"]))
    assert audit["report"]["sha256"] == sha256_file(episode / "REPORT.json")
    if not inspect and not diagnostic:
        assert (
            report["task_passed"] and audit["task_passed"] and audit["control_passed"]
        )
    trace = read_bound_json(Path(report["trace"]["path"]))
    physical = list(rows(trace))
    cid = episode.parent.name
    suffix = "camera_check" if inspect else "diagnostic" if diagnostic else "complete"
    output = root / f"video_{cid}_{suffix}"
    output.mkdir(exist_ok=False)
    model = load_model(report["model"]["path"])
    model.vis.global_.offwidth = 960
    model.vis.global_.offheight = 720
    model.vis.global_.fovy = 50
    model.vis.headlight.active = 1
    model.vis.headlight.ambient[:] = [0.45] * 3
    model.vis.headlight.diffuse[:] = [0.8] * 3
    model.vis.headlight.specular[:] = [0.1] * 3
    options = mujoco.MjvOption()
    options.geomgroup[:] = 1
    options.flexgroup[:] = 0
    for i in range(model.ngeom):
        name = model.geom(i).name or ""
        if name.startswith("robot_") and (
            model.geom_contype[i] or model.geom_conaffinity[i]
        ):
            model.geom_rgba[i] = [0, 0, 0, 0]
    data = mujoco.MjData(model)
    data.qpos[:] = trace["initial_qpos"]
    mujoco.mj_kinematics(model, data)
    mujoco.mj_comPos(model, data)
    mujoco.mj_flex(model, data)
    renderer = mujoco.Renderer(model, height=720, width=960)
    camera = mujoco.MjvCamera()
    camera.type = mujoco.mjtCamera.mjCAMERA_FREE
    camera.azimuth = 180
    camera.elevation = -18
    camera.distance = 2.25

    def frame(row):
        data.qpos[:] = row["full_qpos_after"]
        mujoco.mj_kinematics(model, data)
        mujoco.mj_comPos(model, data)
        camera.lookat[:] = [data.qpos[0] + 0.10, data.qpos[1], 0.78]
        renderer.update_scene(data, camera=camera, scene_option=options)
        rgb = renderer.render().copy()
        text = f"NATIVE STUDY / FULL G1 / CASE {cid} / ACTUAL PHYSICS"
        if diagnostic or inspect:
            text = "DIAGNOSTIC / NOT A QUALIFIED COMPLETE RUN / " + cid
        cv2.rectangle(rgb, (0, 0), (960, 45), (24, 24, 24), -1)
        cv2.putText(
            rgb,
            text,
            (12, 28),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.56,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        cv2.rectangle(rgb, (0, 672), (960, 720), (24, 24, 24), -1)
        cv2.putText(
            rgb,
            f"t={row['time_after_s']:.2f}s  {row['phase']}  | no external support | 1x real time",
            (12, 701),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.57,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        return rgb

    checkpoints = sorted(
        set(
            [0, len(physical) // 2, len(physical) - 1]
            + [next(i for i, s in enumerate(physical) if s["phase"] == "walking")]
            if any(s["phase"] == "walking" for s in physical)
            else [0, len(physical) - 1]
        )
    )
    pictures = []
    for index in checkpoints:
        rgb = frame(physical[index])
        cv2.imwrite(
            str(output / f"state_{index:05d}.jpg"), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        )
        pictures.append(rgb)
    sheet = np.concatenate(pictures, axis=1)
    cv2.imwrite(
        str(output / "contact_sheet.jpg"), cv2.cvtColor(sheet, cv2.COLOR_RGB2BGR)
    )
    frames = 0
    started = time.monotonic()
    if not inspect:
        assert len(physical) % 4 == 0
        movie = av.open(str(output / "motion.mp4"), "w")
        stream = movie.add_stream("libx264", rate=50)
        stream.width, stream.height = 960, 720
        stream.pix_fmt = "yuv420p"
        stream.options = {"crf": "20", "preset": "fast"}
        for i, row in enumerate(physical[3::4]):
            rgb = frame(row)
            vf = av.VideoFrame.from_ndarray(rgb, format="rgb24")
            vf.pts = i
            vf.time_base = Fraction(1, 50)
            for packet in stream.encode(vf):
                movie.mux(packet)
            frames += 1
            if frames % 100 == 0:
                print(
                    {
                        "case": cid,
                        "rendered_frames": frames,
                        "physical_time_s": row["time_after_s"],
                    },
                    flush=True,
                )
        for packet in stream.encode():
            movie.mux(packet)
        movie.close()
    renderer.close()
    save(
        output / "MANIFEST.json",
        {
            "schema": "native-walk-real-state-render/v1",
            "report": _file_binding(episode / "REPORT.json"),
            "audit": _file_binding(episode / "AUDIT.json"),
            "trace": report["trace"],
            "model": report["model"],
            "scene": _file_binding(root / "model/SCENE.json"),
            "implementation": _file_binding(Path(__file__)),
            "frames": frames,
            "fps": 50,
            "duration_s": frames / 50,
            "source_physics_steps": len(physical),
            "source_duration_s": len(physical) * 0.005,
            "sampling": "each actual 20ms interval-end full qpos, no interpolation, no concatenation, no freeze-padding",
            "camera_check_only": inspect,
            "diagnostic_only": diagnostic or inspect,
            "new_physics_steps": 0,
            "render_only_duplicate_collision_geometry_hidden": True,
            "physical_collision_changes": False,
            "layout_changes": False,
            "full_official_robot_visuals": True,
            "proxy_body": False,
            "manual_visual_review_pending": True,
            "render_wall_s": time.monotonic() - started,
            "files": {
                f.name: _file_binding(f)
                for f in sorted(output.iterdir())
                if f.is_file()
            },
        },
    )
    print({"output": str(output), "frames": frames}, flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--episode", type=Path, required=True)
    ap.add_argument("--inspect", action="store_true")
    ap.add_argument("--diagnostic", action="store_true")
    args = ap.parse_args()
    run(args.root, args.episode, args.inspect, args.diagnostic)
