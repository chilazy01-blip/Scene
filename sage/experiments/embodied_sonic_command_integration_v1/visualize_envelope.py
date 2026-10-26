"""Real full mesh visualization, static checks or complete actual physical trace."""

import argparse
from pathlib import Path
from fractions import Fraction
import numpy as np
from .protocol_envelope import authorize
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def run(root, output, episode=None):
    import mujoco
    import cv2
    import av

    p = authorize(root)
    c = read_bound_json(Path(p["case"]["path"]))
    scene = read_bound_json(Path(p["scene"]["path"]))
    output.mkdir(parents=True, exist_ok=False)
    model = load_model(scene["model"]["path"])
    data = mujoco.MjData(model)
    model.vis.global_.offwidth = 960
    model.vis.global_.offheight = 720
    model.vis.global_.fovy = 60
    model.vis.headlight.active = 1
    model.vis.headlight.ambient[:] = [0.45] * 3
    model.vis.headlight.diffuse[:] = [0.8] * 3
    model.vis.headlight.specular[:] = [0.1] * 3
    opt = mujoco.MjvOption()
    opt.geomgroup[:] = 1
    opt.flexgroup[:] = 0
    for i in range(model.ngeom):
        if (model.geom(i).name or "").startswith("robot_") and (
            model.geom_contype[i] or model.geom_conaffinity[i]
        ):
            model.geom_rgba[i] = [0, 0, 0, 0]
    data.qpos[:50] = c["initial_robot_qpos"]
    a = int(model.joint("payload_free").qposadr[0])
    data.qpos[a : a + 7] = [*c["source_object_xyz_m"], *c["source_object_quat"]]
    mujoco.mj_kinematics(model, data)
    mujoco.mj_comPos(model, data)
    mujoco.mj_flex(model, data)
    renderer = mujoco.Renderer(model, height=720, width=960)
    camera = mujoco.MjvCamera()
    camera.type = mujoco.mjtCamera.mjCAMERA_FREE

    def render(
        q=None, t=0.0, stage="STATIC CHECK - NO MOTION", close=False, diagnostic=False
    ):
        if q is not None:
            data.qpos[:] = q
        mujoco.mj_kinematics(model, data)
        mujoco.mj_comPos(model, data)
        if close:
            camera.lookat[:] = data.xpos[model.body("payload").id]
            camera.azimuth = 225
            camera.elevation = -30
            camera.distance = 0.38
        else:
            camera.lookat[:] = [data.qpos[0] + 0.10, 2.72, 0.78]
            camera.azimuth = 180
            camera.elevation = -18
            camera.distance = 2.20
        renderer.update_scene(data, camera=camera, scene_option=opt)
        rgb = renderer.render().copy()
        title = "SONIC29 / EXACT CHECKPOINT CONTINUATION / ACTUAL DYNAMICS"
        if episode is not None and diagnostic:
            title = "DIAGNOSTIC - TASK NOT COMPLETED / FULL G1 + MUG"
        cv2.rectangle(rgb, (0, 0), (960, 42), (24, 24, 24), -1)
        cv2.putText(
            rgb,
            title,
            (12, 28),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.56,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        cv2.rectangle(rgb, (0, 675), (960, 720), (24, 24, 24), -1)
        cv2.putText(
            rgb,
            f"t={t:.2f}s  {stage}  | original furniture, no extra supports",
            (12, 704),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.52,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        return rgb

    frames = 0
    report = None
    pictures = []
    if episode is None:
        for name, close in (("native_task_layout", False), ("selected_mug", True)):
            rgb = render(close=close)
            cv2.imwrite(
                str(output / (name + ".jpg")), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            )
            pictures.append(rgb)
    else:
        report = read_bound_json(episode / "REPORT.json")
        trace = read_bound_json(Path(report["trace"]["path"]))
        rows = trace["warmup_substeps"] + [
            s for record in trace["records"] for s in record["substeps"]
        ]
        diagnostic = not report["task_passed"]
        states = [rows[i] for i in range(3, len(rows), 4)]
        if len(rows) % 4:
            states.append(rows[-1])
        assert states
        indices = {0, len(states) - 1}
        for stage in (
            "ready_arm",
            "approach",
            "insert",
            "close",
            "lift",
            "carry",
            "place",
            "release",
            "settle",
        ):
            hits = [i for i, s in enumerate(states) if s["stage"] == stage]
            if hits:
                indices.add(hits[len(hits) // 2])
        for i in sorted(indices):
            s = states[i]
            rgb = render(
                s["full_qpos_after"],
                s["time_after_s"],
                s["stage"],
                diagnostic=diagnostic,
            )
            cv2.imwrite(
                str(output / f"actual_{i:04d}.jpg"),
                cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR),
            )
            pictures.append(rgb)
        movie = av.open(str(output / "motion.mp4"), "w")
        stream = movie.add_stream("libx264", rate=50)
        stream.width = 960
        stream.height = 720
        stream.pix_fmt = "yuv420p"
        stream.options = {"crf": "20", "preset": "fast"}
        for i, s in enumerate(states):
            rgb = render(
                s["full_qpos_after"],
                s["time_after_s"],
                s["stage"],
                diagnostic=diagnostic,
            )
            vf = av.VideoFrame.from_ndarray(rgb, format="rgb24")
            vf.pts = i
            vf.time_base = Fraction(1, 50)
            for packet in stream.encode(vf):
                movie.mux(packet)
            frames += 1
            if frames % 100 == 0:
                print(
                    {
                        "video_frames": frames,
                        "actual_time_s": s["time_after_s"],
                        "stage": s["stage"],
                    },
                    flush=True,
                )
        for packet in stream.encode():
            movie.mux(packet)
        movie.close()
    if pictures:
        thumbs = [cv2.resize(f, (640, 480)) for f in pictures]
        while len(thumbs) % 3:
            thumbs.append(np.zeros_like(thumbs[0]))
        grid = np.concatenate(
            [
                np.concatenate(thumbs[i : i + 3], axis=1)
                for i in range(0, len(thumbs), 3)
            ],
            axis=0,
        )
        cv2.imwrite(str(output / "preview.jpg"), cv2.cvtColor(grid, cv2.COLOR_RGB2BGR))
    renderer.close()
    safe_save(
        output / "MANIFEST.json",
        {
            "schema": "native-mug-real-state-visual/v1",
            "model": scene["model"],
            "scene": p["scene"],
            "case": p["case"],
            "report": (
                None if episode is None else _file_binding(episode / "REPORT.json")
            ),
            "trace": None if report is None else report["trace"],
            "new_physics_steps": 0,
            "frames": frames,
            "fps": 50,
            "video_duration_s": frames / 50,
            "source_duration_s": (
                None if report is None else report["physics_steps"] * 0.005
            ),
            "interval_end_sampling_no_interpolation_or_freeze_padding": True,
            "maximum_display_duration_rounding_s": 0.015,
            "static_only": episode is None,
            "task_passed": False if report is None else report["task_passed"],
            "independent_task_audit_not_implied_by_render": True,
            "original_full_mug_mesh_and_official_G1": True,
            "no_added_supports": True,
            "no_layout_or_collision_changes": True,
            "manual_review_pending": True,
            "implementation": _file_binding(Path(__file__)),
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
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--episode", type=Path)
    a = ap.parse_args()
    run(a.root, a.output, a.episode)

