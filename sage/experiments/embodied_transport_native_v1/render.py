"""Full official G1/native-scene visualizer; no proxy limbs, no physical integration."""

import argparse
from .model import load_model
from pathlib import Path
import numpy as np
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def run(root, episode=None):
    import mujoco
    import cv2
    import av

    directory = root / ("static_preview" if episode is None else "diagnostic_motion")
    directory.mkdir(exist_ok=False)
    case = read_bound_json(root / "CASE.json")
    model = load_model(case["model_path"])
    # Render-only hide official collision duplicates. Original full visual mesh stays.
    hidden = []
    for i in range(model.ngeom):
        name = model.geom(i).name or ""
        if name.startswith("robot_") and (
            model.geom_contype[i] or model.geom_conaffinity[i]
        ):
            model.geom_rgba[i, 3] = 0
            hidden.append(name)
    model.vis.global_.offwidth = 960
    model.vis.global_.offheight = 720
    data = mujoco.MjData(model)
    options = mujoco.MjvOption()
    options.flexgroup[:] = 0
    renderer = mujoco.Renderer(model, height=720, width=960)
    cam = mujoco.MjvCamera()
    cam.type = mujoco.mjtCamera.mjCAMERA_FREE
    cam.azimuth = 80
    cam.elevation = -17
    cam.distance = 2.45
    preflight = read_bound_json(root / "NATIVE_PREFLIGHT.json")
    states = [np.asarray(preflight["initial_qpos"])]
    label = "STATIC PREFLIGHT - NO SIMULATION STEPS"
    trace_binding = None
    if episode is not None:
        report = read_bound_json(episode / "REPORT.json")
        trace = read_bound_json(Path(report["trace"]["path"]))
        states = [
            np.asarray(r["substeps"][-1]["full_qpos_after"])
            for r in trace["records"]
            if r["substeps"]
        ]
        label = "FULL MODEL DIAGNOSTIC - TASK NOT QUALIFIED"
        trace_binding = report["trace"]
    container = (
        av.open(str(directory / "motion.mp4"), mode="w")
        if episode is not None
        else None
    )
    if container:
        stream = container.add_stream("libx264", rate=50)
        stream.width = 960
        stream.height = 720
        stream.pix_fmt = "yuv420p"
        stream.options = {"crf": "21", "preset": "fast"}
    for index, qpos in enumerate(states):
        data.qpos[:] = qpos
        # Kinematics only: no collision solve/physical stepping during rendering.
        mujoco.mj_kinematics(model, data)
        mujoco.mj_comPos(model, data)
        cam.lookat[:] = [qpos[0] + 0.15, qpos[1] - 0.06, 0.83]
        renderer.update_scene(data, camera=cam, scene_option=options)
        frame = renderer.render().copy()
        cv2.rectangle(frame, (0, 0), (960, 46), (25, 25, 25), -1)
        cv2.putText(
            frame,
            label,
            (14, 29),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.63,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        if index == 0:
            cv2.imwrite(
                str(directory / "preview.jpg"), cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            )
        if container:
            video = av.VideoFrame.from_ndarray(frame, format="rgb24")
            for packet in stream.encode(video):
                container.mux(packet)
    if container:
        for packet in stream.encode():
            container.mux(packet)
        container.close()
    renderer.close()
    save(
        directory / "MANIFEST.json",
        {
            "schema": "native-full-g1-visualization/v1",
            "model": _file_binding(Path(case["model_path"])),
            "preflight": _file_binding(root / "NATIVE_PREFLIGHT.json"),
            "trace": trace_binding,
            "states_rendered": len(states),
            "physics_steps": 0,
            "task_passed": False,
            "official_mesh_visuals": True,
            "proxy_robot": False,
            "render_only_hidden_collision_duplicates": hidden,
            "label": label,
            "implementation": _file_binding(Path(__file__)),
            "files": [_file_binding(f) for f in directory.iterdir() if f.is_file()],
        },
    )
    print({"visualization": str(directory), "states_rendered": len(states)}, flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--episode", type=Path)
    a = p.parse_args()
    run(a.root, a.episode)
