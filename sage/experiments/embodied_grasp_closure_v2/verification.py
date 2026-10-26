"""Finite software fixtures and saved-data regressions, never physics attempts."""
from copy import deepcopy
import gzip
import json
from pathlib import Path
import numpy as np

from .control import ClosureContract, ClosureController
from .task import TrialGate
from sage.experiments.embodied_grasp_closure_v1.control import ClosureController as V1Controller
from sage.experiments.embodied_grasp_closure_v1.control import ClosureContract as V1Contract
from sage.experiments.embodied_grasp_closure_v1.execution import target_at


def write(path, value):
    path = Path(path)
    with path.open('x') as f:
        json.dump(value, f, indent=2, allow_nan=False)
        f.write('\n')


def obs(c, **changes):
    result = dict(time=0., position=.02, velocity=0., native_force=0.,
                  left_force=c.contact_force_min * 1.01, right_force=c.contact_force_min * 1.01,
                  left_pad_fraction=1., right_pad_fraction=1., com_offset=.01, passive_speed=0.)
    result.update(changes)
    return result


def first(c, **changes):
    controller = ClosureController(c)
    o = obs(c, **changes)
    applied = o['position'] - c.nominal_preload / c.kp - .001
    decision = controller.update(0., o, applied)
    assert decision['switched'] and decision['command'] == applied
    return controller, decision


def advance(controller, **changes):
    o = obs(controller.c, time=controller.last_time + controller.c.dt, **changes)
    return controller.update(0., o, controller.last_command)


def holding(c):
    controller, decision = first(c)
    for _ in range(250):
        if decision['ready']:
            break
        decision = advance(controller)
        assert decision['state'] != 'failed'
    assert decision['state'] == 'holding' and decision['ready']
    return controller, decision


def check_contract(c, limits):
    checks = []
    for v in (-.025, 0., .025):
        q = .02
        applied = q - c.nominal_preload / c.kp
        # A known feasible velocity-dependent prior reference, not kd cancellation
        # in the holding controller. This probes the switch at all speed signs.
        applied += c.kd * v / c.kp
        new = ClosureController(c).update(0., obs(c, velocity=v), applied)
        assert new['command'] == applied and new['force_change_from_reference_only'] == 0.
        assert abs(new['predicted_native_force'] + c.nominal_preload) < 1e-10
        checks.append('exact_switch_velocity_' + str(v))

    for velocity in (-.01, 0., .01):
        controller = ClosureController(c)
        target = .02 - c.nominal_preload / c.kp
        decision = controller.update(0., obs(c, velocity=velocity), target)
        for _ in range(49):
            decision = advance(controller, velocity=velocity)
        assert decision['ready'] and decision['command'] == target
        assert abs(decision['predicted_native_force'] + c.nominal_preload + c.kd * velocity) < 1e-10
        checks.append('steady_target_retains_native_damping_' + str(velocity))

    controller, decision = first(c)
    previous = decision['command']
    for _ in range(250):
        decision = advance(controller)
        assert abs(decision['command'] - previous) <= c.max_command_step + 1e-12
        assert abs(decision['predicted_native_force']) <= c.effort_limit + 1e-9
        previous = decision['command']
        if decision['ready']:
            break
    assert decision['ready'] and decision['ready_steps'] == round(c.confirm_seconds / c.dt)
    checks.append('bounded_transition_then_sustained_readiness')

    controller, _ = first(c)
    for _ in range(40):
        decision = advance(controller, left_force=.2, right_force=.2)
        assert decision['state'] == 'confirming' and not decision['ready']
        assert decision['contact_present'] and not decision['nominal_load_ready']
    for _ in range(250):
        decision = advance(controller)
        if decision['ready']:
            break
    assert decision['ready']
    checks.append('confirmation_underload_distinct_from_presence_then_recovery')

    controller, _ = first(c)
    for i in range(20):
        decision = advance(controller, left_force=0., right_force=0., com_offset=None)
        assert (decision['state'] == 'failed') == (i == 19)
    assert decision['reason'] == 'contact_missing'
    assert advance(controller)['reason'] == 'contact_missing'
    checks.append('true_contact_loss_20ms_terminal')

    for changes, reason in [({'left_pad_fraction': .79}, 'contact_part_or_COM_invalid'),
                            ({'com_offset': .031}, 'contact_part_or_COM_invalid'),
                            ({'native_force': c.effort_limit + .1}, 'measured_native_effort'),
                            ({'passive_speed': 20.1}, 'passive_speed'),
                            ({'position': .0179}, 'extra_compression'),
                            ({'position': .04}, 'no_feasible_continuous_command'),
                            ({'velocity': .08}, 'no_feasible_continuous_command')]:
        controller, _ = first(c)
        decision = advance(controller, **changes)
        assert decision['state'] == 'failed' and decision['reason'] == reason, decision
        checks.append('immediate_' + reason + '_' + next(iter(changes)))

    controller, _ = holding(c)
    for i in range(20):
        decision = advance(controller, left_force=.2, right_force=.2)
        assert not decision['ready']
        assert (decision['state'] == 'failed') == (i == 19)
    assert decision['reason'] == 'holding_load_insufficient'
    checks.append('holding_underload_blocks_immediately_then_fails_20ms')
    controller, _ = holding(c)
    assert not advance(controller, left_force=.2)['ready']
    for i in range(50):
        decision = advance(controller)
        assert decision['ready'] == (i == 49)
    checks.append('holding_requalification_full_50ms')

    controller, _ = first(c)
    for _ in range(round(c.timeout_seconds / c.dt) - 1):
        decision = advance(controller, left_force=.2, right_force=.2)
    assert decision['reason'] == 'closure_timeout'
    checks.append('confirmation_original_2s_deadline')

    for change, applied_delta in [({'time': 1.}, 0.), ({'velocity': float('nan')}, 0.),
                                  ({'left_force': -1.}, 0.), ({'left_pad_fraction': 1.1}, 0.),
                                  ({'com_offset': -1.}, 0.), ({}, .001)]:
        controller, _ = first(c)
        before = deepcopy(vars(controller))
        o = obs(c, time=.001); o.update(change)
        try:
            controller.update(0., o, controller.last_command + applied_delta)
        except ValueError:
            assert vars(controller) == before
        else:
            raise AssertionError('invalid observation was accepted')
        checks.append('atomic_validation_' + str(len(checks)))

    # Cross-product of native-range edges, velocities and prior references.
    accepted = rejected = 0
    for q in (-.006, -.005, 0., .02, .04, .046):
        for v in (-.2, -.025, 0., .025, .2):
            for applied in (-.005, 0., .02, .04):
                decision = ClosureController(c).update(0., obs(c, position=q, velocity=v), applied)
                feasible = (abs(applied - q) <= c.max_target_deflection
                            and abs(c.kp * (applied - q) - c.kd * v) <= c.effort_limit)
                assert (decision['state'] != 'failed') == feasible, (q, v, applied, decision)
                if feasible:
                    assert decision['command'] == applied
                    accepted += 1
                else:
                    assert decision['command'] is None and decision['reason'] == 'switch_reference_infeasible'
                    rejected += 1
    checks.append('independent_switch_feasibility_grid')

    ready = holding(c)[1]
    gate = TrialGate(limits, c)
    assert not gate.admit('test_lift', ready)
    assert not gate.admit('test_hold', ready)
    quality = dict(left=dict(force_N=c.contact_force_min, pad_fraction=1.),
                   right=dict(force_N=c.contact_force_min, pad_fraction=1.), contact_com_offset_m=.01)
    for i in range(500):
        gate.record(dict(time=i * c.dt, contact_quality=quality, relative_slip_m=0.,
                         relative_rotation_rad=0., object_lift_m=.02, support_clearance_m=.02, support_force_N=0.))
    assert not gate.finish() and not gate.admit('lift', ready) and not gate.admit('transport', ready)
    checks.append('synthetic_trial_window_positive_not_a_physics_sample')
    for kind in ('short', 'support', 'underload', 'slip', 'gap'):
        test = deepcopy(gate); test.phase = 'test_hold'; test.passed = False
        if kind == 'short':
            test.samples.pop()
        elif kind == 'support':
            test.samples[-1]['support_force_N'] = .02
        elif kind == 'underload':
            test.samples[-1]['contact_quality']['left']['force_N'] = .2
        elif kind == 'slip':
            test.samples[-1]['relative_slip_m'] = .009
        else:
            sample = deepcopy(test.samples[-1]); sample['time'] += .002
            try:
                test.record(sample)
            except ValueError:
                checks.append('trial_timestamp_gap_rejected'); continue
            raise AssertionError('trial gap accepted')
        assert test.finish() and test.admit('lift', ready)
        checks.append('trial_reject_' + kind)
    no_load = dict(ready, ready=False)
    assert TrialGate(limits, c).admit('test_lift', no_load)
    checks.append('trial_requires_current_readiness')
    return dict(status='pass', assertions=checks, switch_grid=dict(accepted=accepted, rejected=rejected))


def saved_regression(stage, cid, c, evidence):
    source = Path(stage) / 'combinations' / cid
    with gzip.open(source / 'CLOSURE_DECISIONS.json.gz', 'rt') as f:
        rows = [x for x in json.load(f) if x['phase'] == 'close']
    with np.load(source / 'close/RAW.npz') as a:
        controls = a['ctrl'].copy()
    with np.load(source / 'lower/RAW.npz') as a:
        initial = float(a['ctrl'][-1, 5])
    phases = json.loads((source / 'REALIZED_PHASES.json').read_text())
    phase = next(x for x in phases if x['id'] == 'close')
    first_switch = next(x for x in rows if x['decision']['state'] == 'confirming')
    index = first_switch['before_step'] - 1
    old_contract = V1Contract(**{k: v for k, v in vars(c).items() if k in V1Contract.__dataclass_fields__})
    old = V1Controller(old_contract).update(float(target_at(phase, index + 1, c.dt)[5]), first_switch['observation'])
    applied = float(controls[index - 1, 5])
    new = ClosureController(c).update(float(target_at(phase, index + 1, c.dt)[5]), first_switch['observation'], applied)
    assert new['command'] == applied and new['force_change_from_reference_only'] == 0.
    assert abs(old['command'] - applied) > .001
    old_jump = c.kp * (old['command'] - applied)
    assert old_jump > 4.

    controller = ClosureController(c)
    decisions = []
    divergence = None
    rejected_saved_ack = False
    for i, row in enumerate(rows):
        actual_previous = initial if i == 0 else float(controls[i - 1, 5])
        nominal = float(target_at(phase, i + 1, c.dt)[5])
        previous = initial if i == 0 else controller.last_command
        # After divergence, the stream is explicitly noncausal: saved states do
        # not reflect our new command. Only interface logic is being exercised.
        if divergence is not None and not rejected_saved_ack:
            test = deepcopy(controller)
            try:
                test.update(nominal, row['observation'], actual_previous)
            except ValueError as e:
                assert str(e) == 'previous_command_not_applied'; rejected_saved_ack = True
        decision = controller.update(nominal, row['observation'], previous)
        decisions.append(dict(before_step=i + 1, observation=row['observation'],
                              nominal=nominal, previous_reference=previous,
                              actual_saved_previous=actual_previous, decision=decision))
        if decision['command'] is None:
            break
        if i < len(controls) and abs(decision['command'] - controls[i, 5]) > 1e-12 and divergence is None:
            divergence = i + 1
    assert divergence == index + 1 and rejected_saved_ack
    write(evidence / (cid + '_SAVED_INTERFACE_TRACE.json'), dict(
        scope='saved observations with virtual applied-reference acknowledgements after first divergence; NOT closed-loop rollout',
        first_divergence_before_step=divergence, rows=decisions))
    tail = [x for x in rows[index:] if not x['decision'].get('switched', False)]
    return dict(id=cid, prior_dynamic_failure_unchanged=True, saved_switch_before_step=index + 1,
                velocity_mps=first_switch['observation']['velocity'], old_extra_force_jump_from_last_applied_N=old_jump,
                new_extra_force_jump_N=new['force_change_from_reference_only'],
                previous_reference_force_N=new['previous_reference_force_at_current_state'],
                v1_requested_force_N=old['predicted_native_force'],
                historical_switch_matches=True, saved_actual_ack_after_divergence_rejected=rejected_saved_ack,
                offline_final_state=controller.state, offline_ready=controller.ready, offline_rows=len(decisions),
                actual_later_contact_presence_all=all(min(x['observation']['left_force'], x['observation']['right_force']) >= .1 for x in tail),
                causal_dynamic_inference=False)
