"""Finite, registered object-only physics. Every started attempt has a durable record."""
from pathlib import Path
import time
import traceback
import numpy as np

from .contracts import bound, read, reference, require, write_new, fingerprint
from .geometry import pose_metrics


def quat_matrix(q):
    q = np.asarray(q, dtype=float); q = q/np.linalg.norm(q)
    w, x, y, z = q
    return np.array([[1-2*(y*y+z*z), 2*(x*y-w*z), 2*(x*z+w*y)],
                     [2*(x*y+w*z), 1-2*(x*x+z*z), 2*(y*z-w*x)],
                     [2*(x*z-w*y), 2*(y*z+w*x), 1-2*(x*x+y*y)]])


def model_description(model, task, bottom_names):
    import mujoco
    target = model.body(task['target_body']).id
    joint = int(model.body_jntadr[target])
    require(model.body_jntnum[target] == 1 and model.jnt_type[joint] == mujoco.mjtJoint.mjJNT_FREE,
            'unsupported_target_joint')
    require(model.nq == 7 and model.nv == 6 and model.nu == 0, 'unsupported_isolated_model_layout')
    qi, vi = int(model.jnt_qposadr[joint]), int(model.jnt_dofadr[joint])
    bottom = [model.geom(n).id for n in bottom_names]
    walls = [model.geom(n).id for n in task['cavity']['wall_geoms']]
    support = model.body(task['support_body']).id
    targets = [i for i in range(model.ngeom) if model.geom_bodyid[i] == target]
    desk = [i for i in range(model.ngeom) if model.geom_bodyid[i] == support]
    spec = int(mujoco.mjtState.mjSTATE_INTEGRATION)
    qoffset = mujoco.mj_stateSize(model, int(mujoco.mjtState.mjSTATE_TIME))
    voffset = mujoco.mj_stateSize(model, int(mujoco.mjtState.mjSTATE_TIME | mujoco.mjtState.mjSTATE_QPOS))
    return dict(target_body_id=target, target_qpos_address=qi, target_dof_address=vi,
        target_geom_ids=targets, bottom_geom_ids=bottom, wall_geom_ids=walls, desk_geom_ids=desk,
        state_spec=spec, state_size=mujoco.mj_stateSize(model, spec),
        state_target_qpos_slice=[qoffset+qi, qoffset+qi+7], state_target_qvel_slice=[voffset+vi, voffset+vi+6],
        model_ngeom=int(model.ngeom), mass_kg=float(model.body_mass[target]),
        gravity_m_s2=model.opt.gravity.tolist(), mujoco_version=mujoco.__version__,
        target_inertia=model.body_inertia[target].tolist(), target_ipos=model.body_ipos[target].tolist(),
        target_iquat=model.body_iquat[target].tolist(),
        solver=dict(timestep_s=float(model.opt.timestep), integrator=int(model.opt.integrator),
            solver=int(model.opt.solver), iterations=int(model.opt.iterations), tolerance=float(model.opt.tolerance),
            cone=int(model.opt.cone), impratio=float(model.opt.impratio)),
        contact_settings=[list(row) for row in sorted({tuple(np.r_[model.geom_friction[i], model.geom_solref[i],
                                              model.geom_solimp[i], model.geom_condim[i], model.geom_priority[i]])
                                 for i in range(model.ngeom)})])


def get_state(model, data, description):
    import mujoco
    state = np.empty(description['state_size'])
    mujoco.mj_getState(model, data, state, description['state_spec'])
    return state


def contact_rows(model, data, description, step):
    import mujoco
    target = set(description['target_geom_ids']); bottom = set(description['bottom_geom_ids'])
    wall = set(description['wall_geom_ids']); desk = set(description['desk_geom_ids'])
    rows = []
    for index, contact in enumerate(data.contact):
        g1, g2 = int(contact.geom1), int(contact.geom2)
        if (g1 in target) == (g2 in target):
            continue
        other = g2 if g1 in target else g1
        kind = 0 if other in bottom else 1 if other in wall else 2 if other in desk else 3
        normal_z = float(contact.frame[2]) * (-1 if g1 in target else 1)
        wrench = np.empty(6); mujoco.mj_contactForce(model, data, index, wrench)
        rows.append([step, g1, g2, kind, float(contact.dist), *contact.pos.tolist(), normal_z, *wrench.tolist()])
    return rows


def run_attempt(directory, model, description, case, initial_state, protocol, binding_sha, variant, purpose):
    import mujoco
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=False)
    dt = float(model.opt.timestep); steps = int(round(protocol['physics']['duration_s']/dt))
    started = time.monotonic()
    attempt = dict(schema='scene-primitive-attempt/v2', case=case['key'], variant=variant, purpose=purpose,
        expected_response=case['expected_response'], binding_sha256=binding_sha,
        dt_s=dt, maximum_steps=steps, initial_state_sha256=fingerprint(initial_state),
        status='started', new_physics_steps=0, started_at=time.time(), robot_present=False,
        solver_history='complete frozen mjSTATE_INTEGRATION; fresh MjData; no previous rollout history')
    write_new(directory/'STARTED.json', attempt)
    data = mujoco.MjData(model)
    mujoco.mj_setState(model, data, np.asarray(initial_state), description['state_spec'])
    mujoco.mj_forward(model, data)
    mujoco.mj_setState(model, data, np.asarray(initial_state), description['state_spec'])
    initial_pen = max([0.] + [-float(c.dist) for c in data.contact])
    attempt['initial_max_penetration_m'] = initial_pen
    rows, positions, velocities, states, times = [], [], [], [get_state(model, data, description)], []
    qi, vi = description['target_qpos_address'], description['target_dof_address']
    write_new(directory/'INITIAL.json', dict(qpos=data.qpos[qi:qi+7].tolist(),
        qvel=data.qvel[vi:vi+6].tolist(), complete_state=states[0].tolist(), penetration_m=initial_pen))
    hard_error = None
    try:
        if initial_pen > protocol['physics']['initial_penetration_m_max']:
            attempt['status'] = 'initial_state_rejected'
        else:
            for step in range(steps):
                mujoco.mj_step(model, data); attempt['new_physics_steps'] += 1
                q = data.qpos[qi:qi+7].copy(); v = data.qvel[vi:vi+6].copy()
                positions.append(q); velocities.append(v); times.append(float(data.time))
                states.append(get_state(model, data, description))
                rows_now = contact_rows(model, data, description, step); rows.extend(rows_now)
                require(np.isfinite(states[-1]).all() and np.isfinite(q).all() and np.isfinite(v).all(),
                        'nonfinite_simulation_state')
                require(not any(w.number for w in data.warning), 'simulator_warning')
                penetration = max([0.] + [-r[4] for r in rows_now])
                if penetration > protocol['physics']['max_target_penetration_m']:
                    attempt['status'] = 'physical_engineering_rejection:penetration'
                    break
            else:
                attempt['status'] = 'completed'
    except BaseException as exc:
        attempt.update(status='engineering_error', error=repr(exc), traceback=traceback.format_exc())
        hard_error = exc
    finally:
        raw = dict(time=np.asarray(times), qpos=np.asarray(positions).reshape(-1, 7),
                   qvel=np.asarray(velocities).reshape(-1, 6), full_state=np.asarray(states),
                   contacts=np.asarray(rows).reshape(-1, 15), warnings=np.array([w.number for w in data.warning]))
        np.savez_compressed(directory/'RAW.npz', **raw)
        attempt.update(raw=reference(directory/'RAW.npz'), initial=reference(directory/'INITIAL.json'),
                       wall_seconds=time.monotonic()-started, finished_at=time.time(),
                       native_contact_records=len(rows), force_state_timing='native step solver contacts; qpos/qvel post integration')
        write_new(directory/'ATTEMPT.json', attempt)
    if hard_error is not None:
        raise hard_error
    return attempt


def evaluate_trace(raw, initial, attempt, description, task, protocol):
    """Reconstruct qualification from measurements, never from an attempt pass flag."""
    dt = attempt['dt_s']; n = len(raw['time']); t = protocol['physics']['stable_thresholds']
    q, v, states, contacts = [raw[k] for k in ('qpos', 'qvel', 'full_state', 'contacts')]
    require(n == attempt['new_physics_steps'] and q.shape == (n, 7) and v.shape == (n, 6), 'trace_shape')
    require(states.shape == (n+1, description['state_size']) and contacts.ndim == 2 and contacts.shape[1] == 15,
            'state_or_contact_shape')
    require(all(np.isfinite(raw[k]).all() for k in raw), 'nonfinite_raw_evidence')
    require(np.allclose(raw['time'], np.arange(1, n+1)*dt, rtol=0, atol=1e-10), 'trace_clock_mismatch')
    require(np.array_equal(states[0], initial['complete_state']), 'initial_state_trace_mismatch')
    qa, qb = description['state_target_qpos_slice']; va, vb = description['state_target_qvel_slice']
    require(np.array_equal(states[1:, qa:qb], q) and np.array_equal(states[1:, va:vb], v), 'state_pose_velocity_mismatch')
    support, wall_force, penetration, forbidden_pen = [np.zeros(n) for _ in range(4)]
    if len(contacts):
        step, g1, g2, kind = contacts[:, :4].astype(int).T
        require(np.array_equal(contacts[:, :4], contacts[:, :4].astype(int))
                and (step >= 0).all() and (step < n).all(), 'contact_index_invalid')
        first_target = np.isin(g1, description['target_geom_ids'])
        second_target = np.isin(g2, description['target_geom_ids'])
        require(np.all(first_target != second_target), 'contact_target_identity')
        other = np.where(first_target, g2, g1)
        actual_kind = np.where(np.isin(other, description['bottom_geom_ids']), 0,
            np.where(np.isin(other, description['wall_geom_ids']), 1,
            np.where(np.isin(other, description['desk_geom_ids']), 2, 3)))
        require(np.array_equal(kind, actual_kind), 'contact_category_mismatch')
        np.maximum.at(penetration, step, np.maximum(0., -contacts[:, 4]))
        support_mask = (kind == 0) & (contacts[:, 8] > .5)
        np.add.at(support, step[support_mask], np.maximum(0., contacts[support_mask, 9]*contacts[support_mask, 8]))
        np.add.at(wall_force, step[kind == 1], np.maximum(0., contacts[kind == 1, 9]))
        forbidden = (kind != 0) & (kind != 2)
        np.maximum.at(forbidden_pen, step[forbidden], np.maximum(0., -contacts[forbidden, 4]))
    speed = np.linalg.norm(v[:, :3], axis=1); angular = np.linalg.norm(v[:, 3:], axis=1)
    xy_error = np.linalg.norm(q[:, :2]-np.asarray(task['goal'])[:2], axis=1)
    drift = np.linalg.norm(q[:, :2]-np.asarray(initial['qpos'])[:2], axis=1)
    roi = np.asarray(protocol['geometry']['roi_xy_m'])
    import itertools
    quats = q[:, 3:]/np.linalg.norm(q[:, 3:], axis=1, keepdims=True)
    w, x, y, z = quats.T
    rotations = np.stack([1-2*(y*y+z*z), 2*(x*y-w*z), 2*(x*z+w*y),
                         2*(x*y+w*z), 1-2*(x*x+z*z), 2*(y*z-w*x),
                         2*(x*z-w*y), 2*(y*z+w*x), 1-2*(x*x+y*y)], axis=1).reshape(n, 3, 3)
    corners = np.array(list(itertools.product((-1., 1.), repeat=3))) * np.asarray(task['target_dimensions_m'])/2
    world = np.einsum('nij,kj->nki', rotations, corners) + q[:, None, :3]
    pose = np.asarray(task['cavity']['pose_z_up']); bounds = np.asarray(task['cavity']['inner_bounds_local_m'])
    local = (world-pose[:3, 3]) @ pose[:3, :3]
    low, high = local.min(1), local.max(1)
    side = np.minimum((low[:, :2]-bounds[0, :2]).min(1), (bounds[1, :2]-high[:, :2]).min(1))
    within = (low[:, :2] >= roi[0]-1e-9).all(1) & (high[:, :2] <= roi[1]+1e-9).all(1)
    geom = np.c_[side, bounds[1, 2]-high[:, 2], low[:, 2]-bounds[0, 2], within]
    tilts = np.degrees(np.arccos(np.clip(rotations[:, 2, 2], -1, 1)))
    inside = (geom[:, :3] >= t['minimum_containment_margin_m']).all(1)
    good = (inside & (support > t['bottom_support_n_min_exclusive']) & (speed < t['max_speed_m_s'])
            & (angular < t['max_angular_speed_rad_s']) & (xy_error < t['goal_xy_tolerance_m'])
            & (tilts <= t['tilt_deg_max']) & (drift <= t['xy_drift_m_max']) & (geom[:, 3] == 1))
    count = maximum = 0
    for valid in good:
        count = count+1 if valid else 0; maximum = max(maximum, count)
    tail = int(round(t['stable_tail_s']/dt))
    mean_weight = float(support[-tail:].mean()/(description['mass_kg']*abs(description['gravity_m_s2'][2]))) if n >= tail else None
    full = n == int(round(protocol['physics']['duration_s']/dt))
    warning_free = not np.any(raw['warnings'])
    max_pen = max([initial['penetration_m'], float(penetration.max()) if n else 0.])
    engineering = full and warning_free and max_pen <= protocol['physics']['max_target_penetration_m']
    force_range = t['mean_tail_support_weight_ratio_range']
    stable = bool(engineering and count*dt+1e-10 >= t['stable_tail_s']
                  and mean_weight is not None and force_range[0] <= mean_weight <= force_range[1])
    hit = np.flatnonzero(support > 0)
    return dict(case=attempt['case'], status=attempt['status'], new_physics_steps=n,
        initial_admitted=initial['penetration_m'] <= protocol['physics']['initial_penetration_m_max'],
        engineering_passed=bool(engineering), placement_stable=stable,
        final_stable_s=count*dt, maximum_stable_s=maximum*dt,
        mean_tail_support_weight_ratio=mean_weight, first_bottom_contact_time_s=float(raw['time'][hit[0]]) if len(hit) else None,
        terminal_position_m=q[-1, :3].tolist() if n else initial['qpos'][:3],
        terminal_quaternion_wxyz=q[-1, 3:].tolist() if n else initial['qpos'][3:],
        terminal_tilt_deg=float(tilts[-1]) if n else None, terminal_speed_m_s=float(speed[-1]) if n else None,
        terminal_angular_speed_rad_s=float(angular[-1]) if n else None,
        terminal_inside=bool(inside[-1]) if n else False,
        maximum_target_penetration_m=max_pen, maximum_xy_drift_m=float(drift.max()) if n else None,
        maximum_forbidden_penetration_m=float(forbidden_pen.max()) if n else None,
        wall_contact_observed=bool(np.any(wall_force > 0)), all_footprints_within_ROI=bool((geom[:, 3] == 1).all()) if n else False,
        warning_free=warning_free, native_contact_records=len(contacts))


def read_raw(reference_value):
    with np.load(bound(reference_value['path'], reference_value['sha256']), allow_pickle=False) as arrays:
        return {key: arrays[key] for key in arrays.files}
