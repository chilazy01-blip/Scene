"""Check canonical data against actual source records without using its writer.

This module never integrates physics, runs a policy, or renders an image. A
successful full physical task is required before any canonical data is opened.
"""
from pathlib import Path
import hashlib
import json

import h5py
import numpy as np


CAMERAS = ("robot0_oak_egoview", "robot0_right_eef_view")
TRAJECTORY = {
    "timestamp", "command_timestamp", "joint_position", "joint_velocity",
    "previous_command", "action_chunk", "action_timestamps", "action_valid", "done",
}
CAMERA_FIELDS = {"rgb", "depth_m", "valid", "K", "optical_to_base"}


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def physical_source(trial):
    trial = Path(trial)
    result = json.loads((trial / "RESULT.json").read_text())
    audit = json.loads((trial / "INDEPENDENT_AUDIT_R1.json").read_text())
    if result.get("mode") != "full" or result.get("passed") is not True:
        raise ValueError("complete_physical_task_required")
    if audit.get("passed") is not True or audit.get("full_task_passed") is not True:
        raise ValueError("independent_full_task_acceptance_required")
    assert result["initial_state_restorations"] == 1
    assert result["mid_episode_state_writes"] == 0
    assert audit["no_state_reset_continuity"]
    assert audit["input_sha256"] == digest(trial / "TRACE.npz")
    return result, audit


def audit_canonical(root, trial, binding):
    root, trial = Path(root), Path(trial)
    result, physics_audit = physical_source(trial)
    assert binding["complete_physical_task"] and binding["independent_full_task_passed"]
    assert binding["capture_complete"]
    path = Path(binding["path"])
    assert digest(path) == binding["sha256"]
    source_files = {name: digest(trial / name) for name in (
        "TRACE.npz", "RESULT.json", "INDEPENDENT_AUDIT_R1.json",
        "MODEL.mjb", "PUBLIC_OBSERVATIONS.json")}
    assert source_files == binding["source_binding"]
    inputs = np.load(root / "prepared/expert_adaptation_20261007/runtime_prepare_r4/CONTROL_INPUTS.npz")
    mapping = inputs["qpos_by_pin"]
    raw = np.load(trial / "TRACE.npz")
    public = json.loads((trial / "PUBLIC_OBSERVATIONS.json").read_text())
    commands, before = raw["joint_commands"], raw["before"]
    count = result["actions"]
    assert count == result["dynamic_forwards"] == len(public) == len(commands)
    assert commands.shape == (count, 43) and 0 < count <= 2600
    assert len(before) == count * 4 == result["physics_steps"]
    assert np.array_equal(raw["command_index"], np.repeat(np.arange(count), 4))
    assert np.array_equal(before[1:], raw["after"][:-1])
    assert np.allclose(np.diff(before[:, 0]), .005, rtol=0, atol=1e-11)
    for i, observation in enumerate(public):
        sensor = before[max(0, 4*i - 1)]
        assert observation["command_index"] == i
        assert observation["command_time"] == before[4*i, 0]
        assert observation["sensor_time"] == sensor[0]
        for key, indices in (("q", 1 + mapping), ("dq", 57 + mapping)):
            assert np.array_equal(observation[key], sensor[indices].astype("f4").astype("f8"))
        assert np.array_equal(observation["previous_action"], np.zeros(43) if i == 0 else commands[i-1])

    import mujoco
    assert mujoco.__version__ == "3.2.6"
    model = mujoco.MjModel.from_binary_path(str(trial / "MODEL.mjb"))
    frozen = np.load(root / "prepared/expert_adaptation_20261007/NATIVE_MODEL_ARRAYS_R2.npz")
    assert all(np.array_equal(getattr(model, key), value) for key, value in frozen.items())
    data = mujoco.MjData(model)
    options = mujoco.MjvOption()
    options.geomgroup[3] = 0
    options.sitegroup[:] = 0
    options.flags[mujoco.mjtVisFlag.mjVIS_RANGEFINDER] = False
    scene = mujoco.MjvScene(model, maxgeom=10000)
    camera = mujoco.MjvCamera()
    camera.type = mujoco.mjtCamera.mjCAMERA_FIXED
    pelvis = model.body("robot0_pelvis").id
    rows, rays, max_ray_error = (count + 1) // 2, 0, 0.
    with h5py.File(path, "r") as canonical:
        metadata = json.loads(canonical.attrs["metadata"])
        assert metadata["source_binding"] == source_files
        assert Path(metadata["source_trial"]).resolve() == trial.resolve()
        assert metadata["controller_plan_sha256"] == digest(trial.parent / "PHYSICAL_PLAN_R1.json")
        assert metadata["scope"] == "simulation_training"
        assert metadata["rows"] == rows == binding["rows"]
        assert metadata["image_frequency_hz"] == 25 and metadata["command_frequency_hz"] == 50
        assert metadata["action_chunk_length"] == 2
        assert set(canonical) == {"trajectory", "cameras"}
        assert set(canonical["trajectory"]) == TRAJECTORY
        assert set(canonical["cameras"]) == set(CAMERAS)
        for row in range(rows):
            i = row * 2
            sensor = before[max(0, 4*i - 1)]
            following = min(i+1, count-1)
            expected = dict(timestamp=sensor[0], command_timestamp=before[4*i, 0],
                joint_position=public[i]["q"], joint_velocity=public[i]["dq"],
                previous_command=public[i]["previous_action"],
                action_chunk=commands[[i, following]],
                action_timestamps=before[[4*i, 4*following], 0],
                action_valid=np.array([True, i+1 < count]), done=row == rows-1)
            for key, value in expected.items():
                saved = canonical["trajectory/"+key]
                assert len(saved) == rows and np.array_equal(saved[row], value), (key, row)
            data.time, data.qpos[:], data.qvel[:] = sensor[0], sensor[1:58], sensor[58:]
            mujoco.mj_forward(model, data)
            base_rotation = data.xmat[pelvis].reshape(3, 3)
            for name in CAMERAS:
                stored = canonical["cameras/"+name]
                assert set(stored) == CAMERA_FIELDS
                rgb, depth, valid = stored["rgb"][row], stored["depth_m"][row], stored["valid"][row]
                assert rgb.shape == (256, 256, 3) and rgb.dtype == np.dtype("u1")
                assert depth.shape == valid.shape == (256, 256)
                assert depth.dtype == np.dtype("f4") and valid.dtype == np.dtype("?")
                assert np.isfinite(depth).all() and np.all(depth[~valid] == 0)
                assert np.all(depth[valid] > 0) and valid.sum() >= 4
                cid = model.camera(name).id
                rotation = data.cam_xmat[cid].reshape(3, 3) @ np.diag([1., -1., -1.])
                pose = np.eye(4)
                pose[:3, :3] = base_rotation.T @ rotation
                pose[:3, 3] = base_rotation.T @ (data.cam_xpos[cid] - data.xpos[pelvis])
                assert np.allclose(stored["optical_to_base"][row], pose, rtol=0, atol=1e-12)
                camera.fixedcamid = cid
                mujoco.mjv_updateScene(model, data, options, None, camera,
                                      mujoco.mjtCatBit.mjCAT_ALL, scene)
                view = mujoco.mjv_averageCamera(scene.camera[0], scene.camera[1])
                scale = 256 / (view.frustum_top - view.frustum_bottom)
                focal = view.frustum_near * scale
                calibration = np.array([[focal, 0., 127.5-view.frustum_center*scale],
                    [0., focal, view.frustum_top*scale-.5], [0., 0., 1.]])
                assert np.allclose(stored["K"][row], calibration, rtol=0, atol=1e-12)
                if row in (0, rows//2, rows-1):
                    ys, xs = np.nonzero(valid)
                    for index in np.linspace(0, len(xs)-1, 4, dtype=int):
                        x, y = int(xs[index]), int(ys[index])
                        optical = np.linalg.solve(calibration, np.array([x, y, 1.]))
                        norm = np.linalg.norm(optical)
                        direction = rotation @ optical / norm
                        near = view.frustum_near * norm
                        distance = mujoco.mj_ray(model, data, data.cam_xpos[cid]+near*direction,
                            direction, options.geomgroup, 1, -1, np.array([-1], dtype="i4"))
                        error = abs((distance+near)/norm-float(depth[y, x]))
                        assert distance >= 0 and error < .002, (row, name, error)
                        rays += 1
                        max_ray_error = max(max_ray_error, error)
        cursor, charged_render = 0, 0
        for folder in map(Path, binding["chunks"]):
            receipt = json.loads((folder/"RESULT.json").read_text())
            assert receipt["passed"] and receipt["source_binding"] == source_files
            assert receipt["physics_steps"] == receipt["policy_forwards"] == 0
            assert receipt["start"] == cursor and cursor < receipt["stop"] <= rows
            assert receipt["rows"] == receipt["stop"]-cursor
            assert receipt["render_passes"] == 4*receipt["rows"]
            assert receipt["render_charged"] >= receipt["render_passes"]
            assert receipt["chunk_sha256"] == digest(folder/"chunk.h5")
            with h5py.File(folder/"chunk.h5", "r") as chunk:
                assert json.loads(chunk.attrs["metadata"]) == metadata
                for group, keys in [("trajectory", TRAJECTORY)]+[("cameras/"+name, CAMERA_FIELDS) for name in CAMERAS]:
                    for key in keys:
                        saved, original = canonical[group+"/"+key], chunk[group+"/"+key]
                        assert saved.dtype == original.dtype
                        for j in range(receipt["rows"]):
                            assert np.array_equal(saved[cursor+j], original[j])
            cursor = receipt["stop"]
            charged_render += receipt["render_charged"]
        assert cursor == rows
    assert all(np.array_equal(getattr(model, key), value) for key, value in frozen.items())
    assert digest(path) == binding["sha256"]
    return dict(passed=True, scope="independent canonical source/time/action/calibration/chunk audit",
        canonical_path=str(path), canonical_sha256=binding["sha256"], source_trial=str(trial),
        source_binding=source_files, all_rows=rows, all_public_source_rows=count,
        full_task_passed=physics_audit["full_task_passed"], ray_checks=rays,
        max_ray_depth_error_m=max_ray_error, original_chunk_render_charged=charged_render,
        all_canonical_pixels_equal_bound_capture_chunks=True,
        calibration_and_time_audited=True, physics_steps=0, policy_forwards=0, render_passes=0)
