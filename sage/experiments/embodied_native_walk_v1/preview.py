"""Same-state original-room and physical-collision inspection, no motion frames."""

import argparse
from pathlib import Path
import math
import numpy as np
from .preflight import authorize
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def run(root):
    import mujoco
    import cv2

    authorize(root)
    output = root / "environment_preview"
    output.mkdir(exist_ok=False)
    scene = read_bound_json(root / "model/SCENE.json")
    pre = read_bound_json(root / "GEOMETRY_PREFLIGHT.json")
    model = load_model(scene["model"]["path"])
    data = mujoco.MjData(model)
    data.qpos[:] = pre["conditions"][0]["initial_qpos"]
    mujoco.mj_kinematics(model, data)
    mujoco.mj_comPos(model, data)
    mujoco.mj_flex(model, data)
    model.vis.global_.offwidth = 960
    model.vis.global_.offheight = 720
    model.vis.global_.fovy = 65
    renderer = mujoco.Renderer(model, height=720, width=960)
    camera = mujoco.MjvCamera()
    camera.type = mujoco.mjtCamera.mjCAMERA_FREE
    visual_rgba = model.geom_rgba.copy()
    flex_rgba = model.flex_rgba.copy()
    pictures = {}

    def render(
        name,
        title,
        position,
        azimuth,
        elevation,
        distance,
        collision=False,
        cutaway=False,
    ):
        model.geom_rgba[:] = visual_rgba
        model.flex_rgba[:] = flex_rgba
        options = mujoco.MjvOption()
        options.geomgroup[:] = 1
        options.flexgroup[:] = 0
        options.flags[mujoco.mjtVisFlag.mjVIS_FLEXVERT] = False
        options.flags[mujoco.mjtVisFlag.mjVIS_FLEXEDGE] = False
        options.flags[mujoco.mjtVisFlag.mjVIS_FLEXFACE] = True
        if cutaway:
            options.geomgroup[4] = 0
        for i in range(model.ngeom):
            n = model.geom(i).name or ""
            collidable = bool(model.geom_contype[i] or model.geom_conaffinity[i])
            if n.startswith("robot_") and collidable:
                model.geom_rgba[i] = (
                    [0.12, 0.55, 0.95, 1] if collision else [0, 0, 0, 0]
                )
        if collision:
            # Robot collision meshes rendered as their actual convex hulls; flex scene stays nonconvex.
            options.flags[mujoco.mjtVisFlag.mjVIS_CONVEXHULL] = True
            options.geomgroup[1] = 0
            options.geomgroup[3] = 0
            options.geomgroup[4] = 0
            options.flexgroup[5] = 1
            model.flex_rgba[:] = [0.85, 0.5, 0.12, 1]
            model.geom_rgba[model.geom("native_floor").id] = [0.43, 0.47, 0.5, 1]
        camera.lookat[:] = position
        camera.azimuth = azimuth
        camera.elevation = elevation
        camera.distance = distance
        renderer.update_scene(data, camera=camera, scene_option=options)
        frame = renderer.render().copy()
        cv2.rectangle(frame, (0, 0), (960, 45), (25, 25, 25), -1)
        cv2.putText(
            frame,
            title,
            (12, 28),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.59,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            "STATIC CHECK ONLY - NO PHYSICS STEPS",
            (12, 705),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.52,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        cv2.imwrite(
            str(output / (name + ".jpg")), cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        )
        pictures[name] = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

    render(
        "interior",
        "NATIVE GENERATED STUDY / FULL G1 / NO TASK PROPS",
        [2.1, 2, 0.8],
        35,
        -20,
        3.0,
    )
    render(
        "overview",
        "NATIVE ROOM OVERVIEW / ACTUAL GENERATED LAYOUT",
        [2.4, 2, 0.0],
        90,
        -90,
        4.5,
    )
    render(
        "cutaway",
        "INSPECTION CUTAWAY / WALLS HIDDEN FOR RENDER ONLY",
        [2.35, 2, 0.55],
        35,
        -35,
        5.3,
        cutaway=True,
    )
    render(
        "collision",
        "PHYSICAL COVERAGE / FULL ROOM STILL ENABLED",
        [2.4, 2, 0.0],
        90,
        -90,
        4.5,
        collision=True,
    )
    sheet = np.concatenate(
        [
            np.concatenate([pictures["interior"], pictures["cutaway"]], axis=1),
            np.concatenate([pictures["overview"], pictures["collision"]], axis=1),
        ],
        axis=0,
    )
    cv2.imwrite(str(output / "environment_check.jpg"), sheet)
    renderer.close()
    save(
        output / "MANIFEST.json",
        {
            "schema": "native-environment-confirmation-preview/v1",
            "model": scene["model"],
            "scene": _file_binding(root / "model/SCENE.json"),
            "preflight": _file_binding(root / "GEOMETRY_PREFLIGHT.json"),
            "initial_condition": "A",
            "full_official_robot_visual_mesh": True,
            "robot_proxy": False,
            "no_task_props": True,
            "layout_changed": False,
            "physical_walls_hidden": False,
            "cutaway_wall_visibility_changed_for_render_only": True,
            "physics_steps": 0,
            "motion_frames": 0,
            "dynamic_task_passed": False,
            "manual_visual_review_pending": True,
            "files": {p.name: _file_binding(p) for p in sorted(output.glob("*.jpg"))},
            "implementation": _file_binding(Path(__file__)),
        },
    )
    print(
        {
            "preview": str(output / "environment_check.jpg"),
            "physics_steps": 0,
            "manual_visual_review_pending": True,
        },
        flush=True,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    run(p.parse_args().root)
