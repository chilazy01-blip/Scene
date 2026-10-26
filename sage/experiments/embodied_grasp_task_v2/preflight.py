"""Offline task wiring probes. Synthetic observations never count as dynamics."""
from copy import deepcopy
import gzip
import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import mujoco

from .task import CompleteTaskConsumer
from .execution import phases, target_at
from sage.experiments.embodied_grasp_closure_v2.control import ClosureContract
from sage.experiments.embodied_grasp_closure_v2.task import NativeTaskConsumer
from sage.experiments.embodied_grasp_validation_v1.native import Stretch
from sage.experiments.embodied_grasp_validation_v1.quality import relative_pose


def check(config, task, binding, selected):
    c = ClosureContract(**config['closure_contracts'][task['id']])
    sequence = phases(config, selected)
    assert sum(p['steps'] for p in sequence) == 33000
    assert [(p['id'], p['seconds']) for p in sequence] == [tuple(p) for p in config['phase_seconds']]
    source = Path(config['intervention']['previous_dynamic_stage']) / 'combinations' / task['id']
    with gzip.open(source / 'CLOSURE_DECISIONS.json.gz', 'rt') as f:
        event = next(x for x in json.load(f) if x['decision']['state'] == 'confirming')
    index = event['before_step'] - 1
    m = mujoco.MjModel.from_xml_path(task['model'])
    d = mujoco.MjData(m)
    with np.load(source / 'close/RAW.npz') as a:
        d.qpos[:] = a['qpos'][index]; d.qvel[:] = a['qvel'][index]
        d.ctrl[:] = a['ctrl'][index-1]; d.time = a['time'][index]
    mujoco.mj_forward(m, d)
    native = Stretch(m, binding)
    full = CompleteTaskConsumer(native, task, c, config['quality'], sequence)
    nominal = d.ctrl.copy(); nominal[5] = 0.
    qpos, qvel, time, grip = d.qpos.copy(), d.qvel.copy(), d.time, float(d.ctrl[5])
    result = full.consume(d, nominal, 'close')
    assert result['applied'] and result['decision']['switched'] and d.ctrl[5] == grip
    assert np.array_equal(qpos, d.qpos) and np.array_equal(qvel, d.qvel) and d.time == time
    checks = ['real_saved_switch_consumed_without_integration']
    try:
        full.begin_release(d)
    except ValueError:
        assert full.release_handoff is None
    else:
        raise AssertionError('early release accepted')
    checks.append('release_before_trial_or_place_rejected')

    # Seed ONLY software history/reference for a sample-extraction probe. The
    # saved native contact forces remain real readbacks, but this is not a
    # physically obtained holding state or a successful trial lift.
    sampler = NativeTaskConsumer(native, task, c, config['quality'])
    sampler.controller.state = 'holding'
    sampler.controller.ready_steps = 50
    sampler.controller.anchor = float(d.actuator_length[5])
    sampler.controller.last_time = float(d.time) - c.dt
    d.ctrl[5] = float(d.actuator_length[5]) - c.nominal_preload / c.kp
    sampler.controller.last_command = float(d.ctrl[5])
    sampler.gate.phase = 'test_lift'
    sampler.reference = relative_pose(d.xpos[native.hand], d.xmat[native.hand], d.xipos[native.target], d.xmat[native.target])
    sampler.com_height = float(d.xipos[native.target, 2])
    sampled = sampler.consume(d, nominal, 'test_hold')
    assert sampled['applied'] and len(sampler.gate.samples) == 1
    sample = sampler.gate.samples[0]
    independent_support = 0.
    for i, contact in enumerate(d.contact):
        if set(map(int, m.geom_bodyid[[contact.geom1, contact.geom2]])) == {native.target, native.support}:
            force = np.zeros(6); mujoco.mj_contactForce(m, d, i, force)
            independent_support += max(0., float(force[0]))
    independent_bottom = min(np.asarray(task['local_vertices']) @ d.xmat[native.target].reshape(3, 3)[2]) + d.xpos[native.target, 2]
    assert abs(sample['support_force_N'] - independent_support) < 1e-12
    assert abs(sample['support_clearance_m'] - (independent_bottom - task['support_top_z'])) < 1e-12
    assert sample['object_lift_m'] == 0.
    assert sampler.finish_trial() == ['incomplete_test_lift_window']
    checks += ['actual_native_trial_sample_support_and_clearance_extraction', 'incomplete_native_window_rejected']

    # Positive trial/release wiring uses a named, explicit observation fixture.
    # It calls the same native action writer; no mj_step and no causal claim.
    short = deepcopy(sequence)
    counts = dict(close=50, test_lift=1, test_hold=500, lift=1, transport=1, place=1)
    for phase in short:
        if phase['id'] in counts:
            phase['steps'] = counts[phase['id']]
            phase['seconds'] = phase['steps'] * c.dt
            phase['ramp_seconds'] = phase['seconds'] * 2 / 3
    def fixture():
        n = Stretch(m, binding)
        f = SimpleNamespace(ctrl=nominal.copy(), time=0., qvel=np.zeros(m.nv),
                            actuator_length=d.actuator_length.copy(), actuator_velocity=np.zeros(m.nu),
                            actuator_force=np.zeros(m.nu), xpos=d.xpos.copy(), xipos=d.xipos.copy(),
                            xmat=d.xmat.copy(), contact=[], fixture_force=c.contact_force_min * 1.1)
        f.actuator_length[5] = .02
        f.ctrl[5] = .02 - c.nominal_preload / c.kp
        f.actuator_force[5] = -c.nominal_preload
        n.contacts = lambda data: [dict(side=s, part='pad', normal_N=data.fixture_force,
                                       position=(data.xipos[n.target] + np.array([offset, 0., 0.])).tolist())
                                   for s, offset in [('left', -.03), ('right', .03)]]
        return CompleteTaskConsumer(n, task, c, config['quality'], short), f

    consumer, f = fixture()
    for name in ('close', 'test_lift', 'test_hold', 'lift', 'transport', 'place'):
        phase = consumer.sequence[name]
        if name == 'test_hold':
            f.xpos[consumer.native.hand, 2] += .03
            f.xpos[consumer.native.target, 2] += .03
            f.xipos[consumer.native.target, 2] += .03
        for i in range(phase['steps']):
            a = target_at(phase, i+1, c.dt)
            answer = consumer.consume(f, a, name)
            assert answer['applied'], answer
            f.time += c.dt
        assert not consumer.finish_phase(name)
    assert consumer.closed.gate.passed
    checks.append('synthetic_full_native_trial_window_and_carry_admission')
    positive_window = deepcopy(consumer.closed.gate.samples)
    for kind in ('support', 'slip', 'underload'):
        gate = deepcopy(consumer.closed.gate); gate.phase = 'test_hold'; gate.passed = False
        if kind == 'support': gate.samples[-1]['support_force_N'] = .02
        elif kind == 'slip': gate.samples[-1]['relative_slip_m'] = .009
        else: gate.samples[-1]['contact_quality']['left']['force_N'] = .2
        assert gate.finish()
        checks.append('synthetic_trial_reject_' + kind)
    initial_grip = float(f.ctrl[5])
    release = consumer.begin_release(f)
    assert release['initial'][5] == initial_grip and consumer.release_handoff['same_state_force_jump_N'] == 0.
    try:
        consumer.consume(f, target_at(consumer.sequence['retreat'], 1, c.dt), 'retreat')
    except ValueError as e:
        assert str(e) == 'previous_phase_not_complete'
    else:
        raise AssertionError('retreat before release accepted')
    checks.append('retreat_before_complete_release_rejected')
    invalid = target_at(release, 1, c.dt); invalid[5] = 0.
    before = f.ctrl.copy(), consumer.phase, consumer.count, consumer.last_time
    try:
        consumer.consume(f, invalid, 'release')
    except ValueError as e:
        assert str(e) == 'release_or_retreat_reference_mismatch'
        assert np.array_equal(before[0], f.ctrl) and before[1:] == (consumer.phase, consumer.count, consumer.last_time)
    else:
        raise AssertionError('nominal-zero release reset accepted')
    checks.append('release_nominal_zero_reset_atomically_rejected')
    release_first = None
    for name in ('release', 'retreat', 'settle'):
        phase = consumer.sequence[name]
        for i in range(phase['steps']):
            command = target_at(phase, i+1, c.dt)
            assert consumer.consume(f, command, name)['applied']
            if name == 'release' and i == 0:
                release_first = float(f.ctrl[5])
            f.time += c.dt
        assert not consumer.finish_phase(name)
    assert consumer.finished == set(consumer.order)
    assert abs(f.ctrl[5] - config['planning']['full_open']) < 1e-12
    checks.append('full_duration_release_retreat_settle_reference_consumption')

    rejected, f2 = fixture()
    close = rejected.sequence['close']
    for i in range(close['steps']):
        assert rejected.consume(f2, target_at(close, i+1, c.dt), 'close')['applied']; f2.time += c.dt
    assert not rejected.finish_phase('close')
    f2.fixture_force = .2
    before = f2.ctrl.copy()
    output = rejected.consume(f2, target_at(rejected.sequence['test_lift'], 1, c.dt), 'test_lift')
    assert not output['applied'] and output['failures'] == ['load_and_reference_not_ready']
    assert np.array_equal(before, f2.ctrl) and rejected.failed
    checks.append('lost_readiness_blocks_actual_action_writer')
    return dict(id=task['id'], status='pass', checks=checks, new_physics_steps=0,
                native_sample=dict(support_force_N=independent_support, support_clearance_m=sample['support_clearance_m'],
                                   scope='actual saved native contacts with explicit software-history seed; not a physical hold'),
                synthetic_trial_samples=len(positive_window), release_initial=initial_grip,
                release_first_command=release_first, release_first_regular_ramp_increment=release_first-initial_grip,
                release_handoff_force_jump_N=0., original_full_task_steps=33000)
