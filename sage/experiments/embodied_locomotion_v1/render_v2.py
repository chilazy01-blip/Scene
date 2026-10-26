"""Render bound, measured SONIC state traces without any physics integration.

Meshes are absent: colored proxy links show real body-frame kinematics only.
No reference poses, pose interpolation or imagined completion are used.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path

from sage.experiments.embodied_data_stability_v1.audit_candidates import (
    canonical_sha256,
    sha256_file,
    write_json_atomic,
)
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)
from sage.experiments.embodied_data_stability_v1.sonic_walk_official_model import (
    official_body_model_xml,
)


def render(root, output):
    os.environ.setdefault("LP_NUM_THREADS", "1")
    os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:4])
    os.environ.setdefault("MUJOCO_GL", "egl")
    os.environ.setdefault("PYOPENGL_PLATFORM", "egl")
    os.environ.setdefault("EGL_PLATFORM", "surfaceless")
    os.environ.setdefault("LIBGL_ALWAYS_SOFTWARE", "1")
    import cv2
    import mujoco
    import numpy as np

    report = read_bound_json(root / "REPORT.json")
    trace_path = Path(report["trace"]["path"])
    if sha256_file(trace_path) != report["trace"]["sha256"]:
        raise RuntimeError("trace file binding changed")
    trace = read_bound_json(trace_path)
    rows = [r for r in trace["records"] if r["sonic_candidate_consumed_by_physics"]]
    if not rows:
        raise ValueError("no executed SONIC states to render")
    case = report["case_config"]
    model_binding = read_bound_json(Path(case["scene_manifest_path"]))
    model = mujoco.MjModel.from_xml_path(case["model_path"])
    data = mujoco.MjData(model)
    for key in ("model", "sonic_walk_official_model"):
        binding = report["source_bindings"][key]
        if sha256_file(Path(binding["path"])) != binding["sha256"]:
            raise RuntimeError("model source changed")
    audit_path = root / "AUDIT.json"
    independent = read_bound_json(audit_path)
    if independent["report"]["sha256"] != sha256_file(root / "REPORT.json"):
        raise RuntimeError("independent audit belongs to another run")
    task_passed = independent.get("task_passed", False)
    output.mkdir(parents=True, exist_ok=False)
    # Render-only scene decoration. These geoms never enter a physical model.
    model.vis.global_.offwidth = 960
    model.vis.global_.offheight = 600
    renderer = mujoco.Renderer(model, height=600, width=960)
    camera = mujoco.MjvCamera()
    end_x = rows[-1]["actual_root_xyz_after_m"][0]
    camera.lookat[:] = [
        (case["start_xy_m"][0] + end_x) * 0.5,
        case["start_xy_m"][1] - 0.05,
        0.64,
    ]
    camera.distance, camera.azimuth, camera.elevation = 1.95, 80, -16
    model.vis.headlight.ambient[:] = [0.5, 0.5, 0.5]
    model.vis.headlight.diffuse[:] = [0.8, 0.8, 0.8]
    movie = output / "motion.mp4"
    from .video import H264Writer

    writer = H264Writer(movie, 960, 600, 50)
    if not writer.isOpened():
        raise RuntimeError("MP4 writer unavailable")
    contact_sheet = []
    visibility_counts = []

    def add_geom(kind, size, pos, rotation, rgba):
        scene = renderer.scene
        geom = scene.geoms[scene.ngeom]
        mujoco.mjv_initGeom(
            geom,
            kind,
            np.asarray(size),
            np.asarray(pos),
            np.asarray(rotation).reshape(9),
            np.asarray(rgba, dtype=np.float32),
        )
        geom.specular = 0.3
        scene.ngeom += 1
        return geom

    def link(a, b, radius, color):
        if np.linalg.norm(b - a) < 0.025:
            return
        geom = add_geom(
            mujoco.mjtGeom.mjGEOM_CAPSULE, [radius] * 3, (a + b) / 2, np.eye(3), color
        )
        mujoco.mjv_connector(geom, mujoco.mjtGeom.mjGEOM_CAPSULE, radius, a, b)

    try:
        for index, row in enumerate(rows):
            # Each pose is an actual pre-control-tick observation, not reference.
            data.qpos[:] = np.r_[
                row["actual_root_xyz_before_m"],
                row["actual_quaternion"],
                row["actual_qpos"],
            ]
            mujoco.mj_forward(model, data)
            renderer.update_scene(data, camera=camera)
            for grid in range(-6, 15):
                c = grid * 0.2
                for a, b in (
                    ([-1.2, c, 0.001], [2.8, c, 0.001]),
                    ([c, -1.2, 0.001], [c, 2.8, 0.001]),
                ):
                    geom = add_geom(
                        mujoco.mjtGeom.mjGEOM_LINE,
                        [1, 1, 1],
                        (0, 0, 0),
                        np.eye(3),
                        [0.62, 0.66, 0.72, 1],
                    )
                    mujoco.mjv_connector(
                        geom, mujoco.mjtGeom.mjGEOM_LINE, 1, np.array(a), np.array(b)
                    )
            for side in ("left", "right"):
                bid = model.body(side + "_ankle_roll_link").id
                gid = next(i for i in range(model.ngeom) if model.geom_bodyid[i] == bid)
                rotation = data.geom_xmat[gid].reshape(3, 3)
                color = (
                    [0.12, 0.5, 0.85, 1] if side == "left" else [0.85, 0.35, 0.08, 1]
                )
                add_geom(
                    mujoco.mjtGeom.mjGEOM_BOX,
                    [0.095, 0.042, 0.018],
                    data.geom_xpos[gid] + rotation @ np.array([0, 0, 0.013]),
                    rotation,
                    color,
                )
            for angle in range(32):
                a = 2 * np.pi * angle / 32
                b = 2 * np.pi * (angle + 1) / 32
                center = np.array([*case["goal_xy_m"], 0.004])
                start = center + np.array([0.15 * np.cos(a), 0.15 * np.sin(a), 0])
                end = center + np.array([0.15 * np.cos(b), 0.15 * np.sin(b), 0])
                geom = add_geom(
                    mujoco.mjtGeom.mjGEOM_LINE,
                    [2, 2, 2],
                    center,
                    np.eye(3),
                    [0.1, 0.95, 0.25, 1],
                )
                mujoco.mjv_connector(geom, mujoco.mjtGeom.mjGEOM_LINE, 3, start, end)
            for body in range(2, model.nbody):
                name = model.body(body).name
                if not (name.startswith(("left_", "right_", "waist_", "torso"))):
                    continue
                if any(x in name for x in ("thumb", "middle", "index")):
                    continue
                color = (
                    [0.2, 0.65, 0.95, 1]
                    if name.startswith("left")
                    else [0.95, 0.55, 0.18, 1]
                )
                radius = 0.045 if any(x in name for x in ("knee", "ankle")) else 0.032
                link(
                    data.xpos[model.body_parentid[body]], data.xpos[body], radius, color
                )
            pelvis = model.body("pelvis").id
            torso = model.body("torso_link").id
            add_geom(
                mujoco.mjtGeom.mjGEOM_BOX,
                [0.085, 0.10, 0.065],
                data.xpos[pelvis],
                data.xmat[pelvis],
                [0.75, 0.8, 0.87, 1],
            )
            rotation = data.xmat[torso].reshape(3, 3)
            add_geom(
                mujoco.mjtGeom.mjGEOM_BOX,
                [0.075, 0.115, 0.12],
                data.xpos[torso] + rotation @ np.array([0, 0, 0.10]),
                rotation,
                [0.78, 0.83, 0.9, 1],
            )
            add_geom(
                mujoco.mjtGeom.mjGEOM_SPHERE,
                [0.073] * 3,
                data.xpos[torso] + rotation @ np.array([0, 0, 0.30]),
                rotation,
                [0.9, 0.93, 0.97, 1],
            )
            rgb = renderer.render()
            area = rgb[85:525].astype(float)
            blue = int(
                np.count_nonzero(
                    (area[:, :, 2] > 130) & (area[:, :, 2] > area[:, :, 0] * 1.4)
                )
            )
            orange = int(
                np.count_nonzero(
                    (area[:, :, 0] > 150)
                    & (area[:, :, 0] > area[:, :, 2] * 1.7)
                    & (area[:, :, 1] > 70)
                )
            )
            if min(blue, orange) < 100:
                raise RuntimeError(
                    "robot visual occluded: insufficient both-side colored pixels"
                )
            visibility_counts.append({"blue": blue, "orange": orange})
            frame = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            cv2.rectangle(frame, (0, 0), (960, 80), (24, 29, 39), -1)
            cv2.putText(
                frame,
                f"SAGE {case['scene_id']} | SONIC real-state replay | proxy robot visual",
                (22, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (235, 240, 250),
                1,
                cv2.LINE_AA,
            )
            stop_frame = report["planner"].get("stop_command_frame")
            brake_frame = report["planner"].get("brake_command_frame", stop_frame)
            phase = (
                ("START" if index < 25 else "WALK")
                if index < brake_frame
                else ("BRAKE" if index < stop_frame else "STANDING HOLD")
            )
            x = (
                row["actual_root_xyz_before_m"][0]
                - rows[0]["actual_root_xyz_before_m"][0]
            )
            label = (
                f"t={index*.02:.2f}s   goal={case['goal_distance_m']:.1f}m   {phase}"
            )
            cv2.putText(
                frame,
                label,
                (22, 61),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.62,
                (160, 220, 250),
                1,
                cv2.LINE_AA,
            )
            acceptance = report.get("controlled_stop_acceptance")
            speed = float(
                np.linalg.norm(row["substeps"][-1]["root_velocity_after_m_s"][:2])
            )
            status = (
                "Start / walk / stop: PASSED" if task_passed else "Task NOT validated"
            )
            status += f"   speed={speed:.3f}m/s   green circle=goal region"
            cv2.putText(
                frame,
                status,
                (22, 570),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (230, 230, 230),
                1,
                cv2.LINE_AA,
            )
            writer.write(frame)
            if index in (
                {0, 74, 110, len(rows) - 1}
                if len(rows) > 131
                else {0, len(rows) // 3, 2 * len(rows) // 3, len(rows) - 1}
            ):
                contact_sheet.append(frame.copy())
    finally:
        writer.release()
        renderer.close()
    cap = cv2.VideoCapture(str(movie))
    decoded = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if frame.shape != (600, 960, 3) or np.std(frame) < 5:
            raise RuntimeError("invalid video frame")
        decoded += 1
    cap.release()
    if decoded != len(rows):
        raise RuntimeError("encoded frame count mismatch")
    sheet = np.concatenate(
        [
            np.concatenate(contact_sheet[:2], axis=1),
            np.concatenate(contact_sheet[2:], axis=1),
        ],
        axis=0,
    )
    cv2.imwrite(str(output / "preview.jpg"), sheet)
    # Self-contained local report, not a hosted site. MP4 remains separately usable.
    encoded = base64.b64encode(movie.read_bytes()).decode()
    (output / "replay.html").write_text(
        '<!doctype html><meta charset="utf-8"><title>SONIC真实轨迹回放</title>'
        '<body style="background:#151b25;color:#eee;font:18px sans-serif;max-width:1000px;margin:32px auto">'
        "<h2>SONIC 真实仿真轨迹回放</h2><p>按实测姿态回放；简化外观，不是完整网格模型。不重新积分物理、不使用参考动作代替实测动作。</p>"
        f'<video controls loop playsinline style="width:100%" src="data:video/mp4;base64,{encoded}"></video>'
        "<p>蓝色：左侧；橙色：右侧。时间为主动控制阶段。停止是否通过以画面标记和审计报告为准。</p></body>",
        encoding="utf-8",
    )
    manifest = {
        "schema": "generated-locomotion-replay/v1",
        "report": _file_binding(root / "REPORT.json"),
        "trace": _file_binding(trace_path),
        "renderer": _file_binding(Path(__file__)),
        "independent_audit": _file_binding(audit_path),
        "task_passed": task_passed,
        "minimum_robot_visibility_pixels": {
            color: min(v[color] for v in visibility_counts)
            for color in ("blue", "orange")
        },
        "model": model_binding,
        "frames": decoded,
        "fps": 50,
        "physics_steps": 0,
        "reference_poses_rendered": False,
        "visual_geometry": "render-only proxy links; exact measured qpos and official kinematics",
        "artifacts": {
            p.name: _file_binding(p) for p in output.iterdir() if p.is_file()
        },
    }
    manifest["content_sha256_excluding_this_field"] = canonical_sha256(manifest)
    write_json_atomic(output / "MANIFEST.json", manifest)
    return {"output": str(output), "frames": decoded, "physics_steps": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(render(args.run_root, args.output_root), indent=2))


if __name__ == "__main__":
    main()
