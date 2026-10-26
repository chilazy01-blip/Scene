"""Independent saved-command equations and native zero-time action consumption."""
from copy import deepcopy
import gzip
import json
from pathlib import Path
import numpy as np
import mujoco

from .control import ClosureContract, ClosureController
from .task import NativeTaskConsumer
from .verification import obs
from sage.experiments.embodied_grasp_validation_v1.native import Stretch, NAMES


def audit_trace(path, source, cid, c):
    trace = json.loads(Path(path).read_text())
    with gzip.open(Path(source) / 'combinations' / cid / 'CLOSURE_DECISIONS.json.gz', 'rt') as f:
        original = [x for x in json.load(f) if x['phase'] == 'close']
    count = 0
    max_error = max_delta = 0.
    for i, row in enumerate(trace['rows']):
        o, d = row['observation'], row['decision']
        assert o == original[i]['observation']
        if i:
            assert abs(o['time'] - trace['rows'][i-1]['observation']['time'] - c.dt) < 1e-9
            assert row['previous_reference'] == trace['rows'][i-1]['decision']['command']
        if d['command'] is None:
            assert d['state'] == 'failed' and not d['ready']
            continue
        count += 1
        u, q, v = d['command'], o['position'], o['velocity']
        force = c.kp * u - c.kp * q - c.kd * v
        max_error = max(max_error, abs(force - d['predicted_native_force']))
        assert abs(force) <= c.effort_limit + 1e-9
        assert c.ctrl_min <= u <= c.ctrl_max and abs(u - q) <= c.max_target_deflection + 1e-12
        delta = u - row['previous_reference']
        if d['switched']:
            assert delta == 0. and d['force_change_from_reference_only'] == 0.
        elif d['state'] in ('confirming', 'holding'):
            assert abs(delta) <= c.max_command_step + 1e-12
            max_delta = max(max_delta, abs(c.kp * delta))
        if d['ready']:
            assert d['state'] == 'holding' and d['ready_steps'] >= round(c.confirm_seconds / c.dt)
            assert abs(u - (q - c.nominal_preload / c.kp)) <= c.command_tolerance
            assert min(o['left_force'], o['right_force']) >= c.contact_force_min
            assert min(o['left_pad_fraction'], o['right_pad_fraction']) >= c.min_pad_fraction
            assert o['com_offset'] <= c.max_com_offset
    assert max_error < 1e-10
    return dict(status='pass', saved_observations_bound_to_original=True, commands=count,
                independent_affine_max_error_N=max_error, max_reference_only_force_increment_N=max_delta,
                scope='independent equations, observation identity, continuity and limits; no physics replay')


def restore(m, d, a, index, previous):
    d.qpos[:] = a['qpos'][index]
    d.qvel[:] = a['qvel'][index]
    d.ctrl[:] = previous
    d.time = float(a['time'][index])
    mujoco.mj_forward(m, d)


def native_checks(protocol, cid, c):
    source = Path(protocol['source_stage']) / 'combinations' / cid
    task = json.loads((source / 'TASK.json').read_text())
    binding = json.loads(Path(protocol['binding']).read_text())
    with gzip.open(source / 'CLOSURE_DECISIONS.json.gz', 'rt') as f:
        row = next(x for x in json.load(f) if x['decision']['state'] == 'confirming')
    index = row['before_step'] - 1
    with np.load(source / 'close/RAW.npz') as z:
        a = {k: z[k] for k in z.files}
    m = mujoco.MjModel.from_xml_path(task['model'])
    d = mujoco.MjData(m)
    native = Stretch(m, binding)
    previous = a['ctrl'][index-1].copy()
    restore(m, d, a, index, previous)
    consumer = NativeTaskConsumer(native, task, c, protocol['quality'])
    qpos, qvel, t = d.qpos.copy(), d.qvel.copy(), d.time
    action = previous.copy()
    action[5] = 0.
    accepted = consumer.consume(d, action)
    assert accepted['applied'] and accepted['decision']['switched']
    assert d.ctrl[5] == previous[5]
    assert np.array_equal(qpos, d.qpos) and np.array_equal(qvel, d.qvel) and d.time == t
    native_observation_errors = {k: abs(accepted['observation'][k] - row['observation'][k])
                                 for k in row['observation'] if row['observation'][k] is not None}
    rejection_checks = []
    for kind in ('units', 'names', 'shape', 'nan', 'other_actuator_range', 'phase_order', 'time_gap'):
        restore(m, d, a, index, previous)
        trial = NativeTaskConsumer(native, task, c, protocol['quality'])
        command, kwargs = action.copy(), {}
        if kind == 'units': kwargs['units'] = 'degrees'
        elif kind == 'names': kwargs['names'] = tuple(reversed(NAMES))
        elif kind == 'shape': command = command[:-1]
        elif kind == 'nan': command[2] = np.nan
        elif kind == 'other_actuator_range': command[2] = m.actuator_ctrlrange[2, 1] + 1.
        elif kind == 'phase_order': kwargs['phase'] = 'transport'
        else:
            assert trial.consume(d, action)['applied']
        before = deepcopy(vars(trial.controller)), deepcopy(vars(trial.gate)), d.ctrl.copy()
        try:
            trial.consume(d, command, **kwargs)
        except ValueError:
            assert vars(trial.controller) == before[0] and vars(trial.gate) == before[1]
            assert np.array_equal(d.ctrl, before[2])
        else:
            raise AssertionError('native invalid input accepted: ' + kind)
        rejection_checks.append(kind)

    restore(m, d, a, index, previous)
    trial = NativeTaskConsumer(native, task, c, protocol['quality'])
    before = d.ctrl.copy()
    rejected = trial.consume(d, action, 'test_lift')
    assert not rejected['applied'] and np.array_equal(before, d.ctrl)
    assert rejected['failures'] == ['load_and_reference_not_ready'] and trial.gate.failed
    rejection_checks.append('trial_before_ready_no_ctrl_write')

    # Native drive equation tested at both signs and zero velocity. Saved scene
    # snapshots are disposable static fixtures, never written back to RAW.
    force_checks = []
    for v in (-.025, 0., .025):
        restore(m, d, a, index, previous)
        dof = int(m.jnt_dofadr[m.joint('joint_gripper_slide').id])
        d.qvel[dof] = v
        mujoco.mj_forward(m, d)
        q = float(d.actuator_length[5])
        old_u = q - c.nominal_preload / c.kp + c.kd * v / c.kp
        decision = ClosureController(c).update(0., obs(c, position=q, velocity=v), old_u)
        action = previous.copy(); action[5] = decision['command']
        native.command(d, action)
        frozen_qpos, frozen_qvel, time = d.qpos.copy(), d.qvel.copy(), d.time
        mujoco.mj_forward(m, d)
        error = abs(float(d.actuator_force[5]) - decision['predicted_native_force'])
        assert error < 1e-9 and d.time == time
        assert np.array_equal(d.qpos, frozen_qpos) and np.array_equal(d.qvel, frozen_qvel)
        force_checks.append(dict(velocity=v, error_N=error, effort_N=float(d.actuator_force[5])))
    return dict(status='pass', actual_saved_snapshot_consumed=True,
                native_observation_difference_from_saved=native_observation_errors,
                atomic_rejections=rejection_checks, zero_time_drive_checks=force_checks,
                new_physics_steps=0)


def transmission_diagnostic(protocol, cid):
    source = Path(protocol['source_stage']) / 'combinations' / cid
    task = json.loads((source / 'TASK.json').read_text())
    binding = json.loads(Path(protocol['binding']).read_text())
    with gzip.open(source / 'CLOSURE_DECISIONS.json.gz', 'rt') as f:
        decision = next(x for x in json.load(f) if x['decision']['state'] == 'confirming')
    with np.load(source / 'close/RAW.npz') as z:
        a = {k: z[k] for k in z.files}
    with gzip.open(source / 'close/METRICS.json.gz', 'rt') as f:
        metrics = json.load(f)
    with gzip.open(source / 'close/CONTACTS.jsonl.gz', 'rt') as f:
        contacts = [json.loads(line) for line in f]
    m = mujoco.MjModel.from_xml_path(task['model'])
    d = mujoco.MjData(m)
    native = Stretch(m, binding)
    joints = [('joint_gripper_slide', 1.), ('joint_gripper_finger_left_open', 10.),
              ('joint_gripper_finger_right_open', 10.)]
    tangent = np.zeros(m.nv)
    for name, value in joints: tangent[m.jnt_dofadr[m.joint(name).id]] = value
    passive = ('rubber_left_x', 'rubber_left_y', 'rubber_right_x', 'rubber_right_y')
    rows = []
    for index in (decision['before_step'] - 1, len(a['time']) - 1):
        original_qpos = a['qpos'][index].copy()
        def gap(delta, neutral):
            d.qpos[:] = original_qpos
            if neutral:
                for n in passive: d.qpos[m.jnt_qposadr[m.joint(n).id]] = 0.
            for n, gain in joints: d.qpos[m.jnt_qposadr[m.joint(n).id]] += gain * delta
            mujoco.mj_fwdPosition(m, d)
            return native.geometry(d)[2]
        derivatives = {}
        for neutral in (False, True):
            derivatives['passives_zeroed' if neutral else 'loaded_passives_held'] = [
                (gap(e, neutral) - gap(-e, neutral)) / (2 * e) for e in (1e-6, 5e-7)]
        d.qpos[:] = original_qpos
        mujoco.mj_fwdPosition(m, d)
        coefficients = {s: [] for s in ('left', 'right')}
        for saved in contacts[index - 1]:
            b1, b2 = saved['bodies']
            if native.target not in (b1, b2): continue
            other = b2 if b1 == native.target else b1
            if other not in native.hands: continue
            candidates = [x for x in d.contact if [int(x.geom1), int(x.geom2)] == saved['geoms']]
            assert candidates
            contact = min(candidates, key=lambda x: np.linalg.norm(x.pos - saved['position']))
            assert np.linalg.norm(contact.pos - saved['position']) < 1e-10
            normal_out = contact.frame[:3] * (1 if b1 == native.target else -1)
            jp, jr = np.zeros((3, m.nv)), np.zeros((3, m.nv))
            mujoco.mj_jac(m, d, jp, jr, np.array(saved['position']), other)
            coefficient = float(normal_out @ jp @ tangent)
            side, part = native.hands[other]
            coefficients[side].append(dict(normal_N=max(0., saved['force'][0]),
                                            normal_projection_m_per_m=coefficient, part=part))
        quality = metrics[index-1]['contact_quality']
        virtual_normal_effort = sum(x['normal_N'] * x['normal_projection_m_per_m']
                                    for values in coefficients.values() for x in values)
        side_coefficients = {side: sum(x['normal_N'] * x['normal_projection_m_per_m'] for x in values)
                            / max(sum(x['normal_N'] for x in values), 1e-15)
                             for side, values in coefficients.items()}
        sides = [quality[s]['force_N'] for s in ('left', 'right')]
        rows.append(dict(saved_state_index=index, time=float(a['time'][index]),
                         slider_effort_N=float(a['actuator_force'][index, 5]), side_normal_N=sides,
                         slider_effort_magnitude_per_mean_side_normal=abs(float(a['actuator_force'][index, 5])) / np.mean(sides),
                         coupled_aperture_derivative_m_per_m=derivatives,
                         contact_normal_virtual_coefficients_m_per_m=side_coefficients,
                         normal_contact_virtual_effort_N=virtual_normal_effort,
                         passive_angles_rad=[float(original_qpos[m.jnt_qposadr[m.joint(n).id]]) for n in passive],
                         finger_coupling_error_rad=[float(original_qpos[m.jnt_qposadr[m.joint('joint_gripper_finger_'+s+'_open').id]] - 10 * original_qpos[m.jnt_qposadr[m.joint('joint_gripper_slide').id]]) for s in ('left', 'right')]))
    c = protocol['contracts'][cid]
    return dict(id=cid, snapshots=rows,
                old_candidate_zero_passive_derivative=c['nominal_preload'] / (1.25 * c['contact_force_min']),
                scope='static geometry derivatives plus virtual normal work along assumed slider/finger tangent; excludes inertia, friction, passive dynamics and equality reaction work',
                interpretation='no calibrated conversion from native slider effort to side normal forces; preload remains a prior, no parameter fitted',
                zero_time_geometry_snapshots=True, new_physics_steps=0)
