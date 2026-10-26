"""Versioned numerical diagnostics; no candidate selection or real-world truth."""
from pathlib import Path
import hashlib

import mujoco
import numpy as np


# Resolution targets for this experiment, not physical validity/industry limits.
# Freeze before running the new comparison; changing these requires a new version.
RESOLUTION_TARGETS = {"position_m": .001, "velocity_m_s": .01,
                      "floor_gap_m": .0005, "stopping_time_s": .005}


def diagnostic_frames(dense, ids, simulation, floor_z):
    action = np.flatnonzero(dense["action_time_s"] >= 0)
    velocity = np.asarray(simulation["initial_velocity_m_s"][:2])
    direction = velocity / np.linalg.norm(velocity)
    events = {}

    def add(index, reason):
        events.setdefault(int(index), []).append(reason)

    for i, identifier in enumerate(ids):
        along = dense["linear_velocity_m_s"][action, i, :2] @ direction
        backwards = np.flatnonzero(along < -.01)
        if len(backwards):
            for k, label in ((backwards[0], "reverse_onset"), (np.argmin(along), "reverse_peak"),
                             (backwards[-1], "reverse_end")):
                add(action[k], identifier + ":" + label)
        gap = dense["world_bounds_z_up"][action, i, 0, 2] - floor_z
        add(action[np.argmax(gap)], identifier + ":maximum_floor_gap")
        spin = np.linalg.norm(dense["angular_velocity_rad_s"][action, i], axis=1)
        add(action[np.argmax(spin)], identifier + ":maximum_angular_speed")
    frames = []
    for index in sorted(events):
        frames.append({"phase": "diagnostic", "time_s": float(dense["time_s"][index]),
            "action_time_s": float(dense["action_time_s"][index]), "dense_sample_index": index,
            "events": events[index], "bodies": {identifier: {
                "matrix_world_z_up": dense["matrix_world_z_up"][index, i].tolist(),
                "linear_velocity_m_s": dense["linear_velocity_m_s"][index, i].tolist(),
                "angular_velocity_rad_s": dense["angular_velocity_rad_s"][index, i].tolist()}
                for i, identifier in enumerate(ids)}})
    count = round(simulation["action_s"] / simulation["sample_interval_s"])
    return frames, {"schema": "p021-render-sampling/v2",
        "base_action_times_s": (np.arange(count + 1) * simulation["sample_interval_s"]).tolist(),
        "diagnostic_times_s": [frame["action_time_s"] for frame in frames],
        "policy": "all dense steps scanned; per object reverse onset/peak/end below -0.01 m/s, max gap and angular speed",
        "maximum_diagnostic_frames": 5 * len(ids), "threshold_origin": "existing stopped-speed convention"}


def timestep_diagnostics(model_path: Path, initial_state, binding, spec, output_dir=None):
    """Three grids from one full initial state, including settlement and impulse.

    Coarse comparison samples are synchronized in physical time. Every internal
    step is checked for warnings, reverse speed, contact gap and sustained stop.
    The base grid must agree with BOTH finer grids; finest-only agreement cannot
    certify the requested base step. Exceptions remain execution failures.
    """
    sim = spec["simulation"]
    base_dt = float(sim["dt"])
    ids = list(binding["objects"])
    direction = np.asarray(sim["initial_velocity_m_s"][:2], dtype=float)
    direction /= np.linalg.norm(direction)
    hulls = []
    for identifier in ids:
        with np.load(binding["objects"][identifier]["collider"]["artifact"]["path"]) as collider:
            hulls.append(collider["vertices"].copy())
    grids = []
    for divisor in (1, 2, 4):
        model = mujoco.MjModel.from_xml_path(str(model_path))
        model.opt.timestep = base_dt / divisor
        dt = float(model.opt.timestep)
        data = mujoco.MjData(model)
        mujoco.mj_setState(model, data, initial_state, mujoco.mjtState.mjSTATE_INTEGRATION)
        warnings = set()

        def step():
            mujoco.mj_step(model, data)
            mujoco.mj_forward(model, data)
            warnings.update(i for i, warning in enumerate(data.warning) if warning.number)
            if not np.isfinite(data.qpos).all() or not np.isfinite(data.qvel).all():
                raise ValueError("Nonfinite timestep diagnostic state")

        for _ in range(round(sim["settle_s"] / dt)):
            step()
        for obj in binding["objects"].values():
            dof = obj["simulator"]["dof_adr"]
            data.qvel[dof:dof+2] = sim["initial_velocity_m_s"][:2]
        mujoco.mj_forward(model, data)
        samples, max_reverse = [], np.zeros(len(ids))
        max_gap, last_moving = np.full(len(ids), -np.inf), np.full(len(ids), -1.)
        action_steps = round(sim["action_s"] / dt)
        for k in range(action_steps + 1):
            if k:
                step()
            rows = []
            for i, identifier in enumerate(ids):
                bid = binding["objects"][identifier]["simulator"]["body_id"]
                velocity = np.empty(6)
                mujoco.mj_objectVelocity(model, data, mujoco.mjtObj.mjOBJ_BODY, bid, velocity, 0)
                vertices = hulls[i] @ data.xmat[bid].reshape(3, 3).T + data.xpos[bid]
                gap = float(vertices[:, 2].min() - binding["floor"]["support_z_m"])
                max_gap[i] = max(max_gap[i], gap)
                max_reverse[i] = max(max_reverse[i], -float(velocity[3:5] @ direction))
                if np.linalg.norm(velocity[3:5]) > .01:
                    last_moving[i] = k * dt
                if k % divisor == 0:
                    rows.append(np.r_[data.xpos[bid], velocity[3:], gap])
            if k % divisor == 0:
                samples.append(rows)
        stopped = last_moving + dt
        stop = [float(max(0, value)) if sim["action_s"]-value >= .2 else None for value in stopped]
        grids.append({"dt_s": dt, "samples": np.asarray(samples), "warning_ids": sorted(warnings),
            "objects": {identifier: {"max_reverse_speed_m_s": float(max_reverse[i]),
                "max_action_floor_gap_m": float(max_gap[i]), "stopping_time_s": stop[i]}
                for i, identifier in enumerate(ids)}})
        if output_dir is not None:
            path = Path(output_dir)/f'numerical_grid_{divisor}.npz'
            np.savez_compressed(path, object_ids=np.asarray(ids), action_time_s=np.arange(len(samples))*base_dt,
                world_position_velocity_floor_gap=grids[-1]['samples'], integration_dt_s=dt)
            grids[-1]['artifact'] = {'path':str(path.resolve()), 'bytes':path.stat().st_size,
                'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    comparisons = []
    for left, right in ((0, 1), (0, 2), (1, 2)):
        a, b = grids[left], grids[right]
        difference = np.abs(a["samples"] - b["samples"])
        position = float(np.linalg.norm(difference[:, :, :3], axis=2).max())
        velocity = float(np.linalg.norm(difference[:, :, 3:6], axis=2).max())
        gap = float(difference[:, :, 6].max())
        stopping = [abs(a["objects"][i]["stopping_time_s"]-b["objects"][i]["stopping_time_s"])
                    if a["objects"][i]["stopping_time_s"] is not None and b["objects"][i]["stopping_time_s"] is not None
                    else None for i in ids]
        values = {"position_m": position, "velocity_m_s": velocity, "floor_gap_m": gap,
                  "stopping_time_s": max(stopping) if all(v is not None for v in stopping) else None}
        locations = {}
        for key, differences in [('position_m',np.linalg.norm(difference[:,:,:3],axis=2)),
                                 ('velocity_m_s',np.linalg.norm(difference[:,:,3:6],axis=2)),
                                 ('floor_gap_m',difference[:,:,6])]:
            sample, object_index = np.unravel_index(np.argmax(differences), differences.shape)
            locations[key] = {'action_time_s':float(sample*base_dt),'object_id':ids[object_index]}
        comparisons.append({"dt_s": [a["dt_s"], b["dt_s"]], "max_differences": values,
            "maximum_difference_locations":locations,
            "passed": not a["warning_ids"] and not b["warning_ids"] and
                all(value is not None and value <= RESOLUTION_TARGETS[key] for key, value in values.items())})
    return {"schema": "p021-numerical-sensitivity/v1", "mujoco_version": mujoco.__version__,
        "initial_state": "same mjSTATE_INTEGRATION before settlement; identical timed horizontal impulse",
        "resolution_targets": RESOLUTION_TARGETS, "target_origin": "declared engineering resolution targets, not industry standards",
        "grids": [{k: v for k, v in grid.items() if k != "samples"} for grid in grids],
        "comparisons": comparisons, "base_step_resolved": all(c["passed"] for c in comparisons[:2]),
        "finer_grids_agree": comparisons[-1]["passed"], "external_physics_validated": False}
