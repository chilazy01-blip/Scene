"""Prepared shared-quality window with measured navigation, policy and bounded motor guard."""
import os
import sys
import traceback
from pathlib import Path
import numpy as np
import h5py
import mujoco
from .work import E, R, c, finish


def main(config_path, mode='preflight'):
    cfg = c.read(config_path)
    work = Path(os.environ['CONTINUOUS_JOB_DIR'])
    folder = Path(cfg['source_folder'])
    start, steps = int(cfg['start_row']), int(cfg['saved_steps'])
    assert start % 8 == 0 and 0 < steps <= 4000
    if mode == 'window':
        receipt = c.read(E / 'DIAGNOSTIC_WINDOW_REPLAN_APPROVAL.json')
        assert receipt['approved'] and receipt['proposal_sha256'] == c.sha(E / 'DIAGNOSTIC_WINDOW_REPLAN_PROPOSAL.json')
        assert c.read(E / 'C3_SAVED_WALKER_INTERFACE_PREFLIGHT.json')['passed']
    else:
        assert mode == 'preflight'
    with h5py.File(folder / 'TRACE.h5', 'r') as f:
        policy = f['policy/walker_onnx']
        rows = policy['physics_row'][:]
        positions = np.searchsorted(rows, np.arange(start, start + steps, 8))
        assert np.array_equal(rows[positions], np.arange(start, start + steps, 8))
        inputs = policy['input'][next(iter(policy['input']))][positions].reshape(len(positions), -1)
        commands = inputs[:, -3:]
        arm_requests = f['interpolation/requested'][start:start + steps]
        previous = f['interpolation/applied'][start - 1]
        initial = f['substep/integration_before'][start]
        initial_hand_ctrl = f['substep/ctrl'][start - 1]
        expected_endpoint = f['substep/qpos'][start + steps - 1]
        expected_first_command = f['substep/ctrl'][start]
        initial_arm_indices = c.read(R / 'branches/A/source/model_config.json')['joint_names']
        right = [i for i, name in enumerate(initial_arm_indices)
                 if name.startswith('right_') and any(x in name for x in ['shoulder', 'elbow', 'wrist'])]
        command_variation = float(np.max(abs(commands - commands[0])))
        arm_variation = float(np.max(abs(arm_requests[:, right] - arm_requests[0, right])))
        preflight = {'source_row': start, 'rows': steps, 'seconds': steps * .0025,
                     'constant_high_level_velocity_command': commands[0].tolist(),
                     'high_level_command_max_variation': command_variation,
                     'current_arm_request_max_variation': arm_variation,
                     'source_high_level_schedule_constant': command_variation == 0. and arm_variation == 0.,
                     'scope': 'Measured-state source walk-to-position law with original70mm stop condition; initial arm request and previous policy action restored. No future physical commands replayed.',
                     'physics_steps': 0, 'policy_calls': 0, 'production_accepted': False}
    reconstruction = c.read(E / 'C3_WALK_STOP_COMMAND_RECONSTRUCTION.json')
    assert reconstruction['command_reconstruction_passed']
    preflight['source_navigation_goal'] = reconstruction['assumed_source_goal_xy']
    preflight['source_navigation_yaw'] = reconstruction['assumed_source_goal_yaw']
    preflight['source_navigation_tolerance_m'] = reconstruction['source_position_tolerance_m']
    preflight['measured_navigation_and_fixed_arm_admitted'] = arm_variation == 0.
    if mode == 'preflight':
        c.write(work / 'SAVED_WINDOW_PREFLIGHT.json', preflight)
        finish(preflight)
        return
    assert preflight['measured_navigation_and_fixed_arm_admitted']
    from .leg_interpolation import LegInterpolation
    from . import trace_r4
    source = R / 'branches/A/source'
    os.environ.update(NP_ROOT=str(R), NP_JOB=str(work))
    sys.path.insert(0, str(R / 'tools')); sys.path.insert(0, str(source))
    sys.modules['instrument'] = trace_r4
    c.write(work / 'USAGE.json', {key: 0 for key in c.read(work / 'REQUEST.json')['reservation']})
    trace = trace_r4.Trace(work / 'episode', 'diagnostic'); trace.install()
    error = None; first_error = None; guard_records = []
    try:
        from .target_adapter_r4 import install
        install('A', 'gain_translation', work / 'episode')
        import run
        m = mujoco.MjModel.from_binary_path(str(folder / 'MODEL.mjb'))
        d = mujoco.MjData(m)
        mujoco.mj_setState(m, d, initial, mujoco.mjtState.mjSTATE_INTEGRATION)
        mujoco.mj_forward(m, d)
        policies = [run.ONNXPolicy(str(source / (name + '.onnx')))
                    for name in ['walker', 'croucher', 'rotator']]
        ctrl = run.G1Controller(m, d, *policies, c.read(source / 'model_config.json'))
        ctrl.last_action = inputs[0, -32:-3].copy()
        ctrl.lin_vel_x, ctrl.lin_vel_y, ctrl.ang_vel_z = map(float, commands[0])
        leg_indices = [i for i, name in enumerate(ctrl.joint_names)
                       if any(part in name for part in ['hip', 'knee', 'ankle'])]
        interpolation = LegInterpolation(leg_indices, 8); interpolation.apply(previous)
        hands = [i for i in range(m.nu) if 'hand' in m.actuator(i).name]
        guard = None
        if cfg['all_sole_guard']:
            from .all_sole_guard import AllSoleGuard
            guard = AllSoleGuard(m)
        c.write(work / 'SAVED_INTERFACE_STATE.json', {**preflight, 'initial_integration_sha256': __import__('hashlib').sha256(initial.tobytes()).hexdigest(),
                                                    'last_action': ctrl.last_action.tolist()})
        from .saved_walk_to_control import MeasuredWalkTo
        navigation = MeasuredWalkTo(preflight['source_navigation_goal'], preflight['source_navigation_yaw'], preflight['source_navigation_tolerance_m'])
        for k in range(steps):
            if k % 8 == 0:
                ctrl.lin_vel_x, ctrl.lin_vel_y, ctrl.ang_vel_z = map(float, navigation.command(d))
                requested = ctrl.step()
                requested[ctrl.right_arm_indices] = arm_requests[0, ctrl.right_arm_indices]
            applied = interpolation.apply(requested)
            trace.append('interpolation/requested', requested); trace.append('interpolation/applied', applied)
            ctrl.apply_pd_control(applied)
            d.ctrl[hands] = initial_hand_ctrl[hands]
            if first_error is None:
                first_error = float(np.max(abs(d.ctrl - expected_first_command)))
                assert first_error < 1e-7
            if guard is not None:
                record = guard.apply(d)
                record['local_physics_row'] = k
                guard_records.append(record)
                trace.append('sole_guard/physics_row', trace.n)
                trace.append('sole_guard/motor_delta_Nm', record['motor_delta_Nm'])
                trace.append('sole_guard/barriers', record['issued_barrier'])
            mujoco.mj_step(m, d)
            navigation.after_step(d)
    except BaseException:
        error = traceback.format_exc(); print(error, flush=True)
    finally:
        summary = trace.close()
    c.write(work / 'SOLE_GUARD_TELEMETRY.json', guard_records)
    report = {'outcome': 'engineering_failure' if error else 'success', 'summary': summary,
              'engineering_error': error, 'first_nominal_command_max_error': first_error,
              'bounded_saved_state_window': True, 'online_unchanged_body_policy': True,
              'actual_motor_commands_only': True, 'full_task': False, 'production_accepted': False,
              'new_complete_task_attempts': 0, 'source_high_level_schedule_constant': False,
              'measured_source_navigation_feedback': True,
              'endpoint_qpos_max_difference_to_source': float(np.max(abs(d.qpos - expected_endpoint))) if 'd' in locals() else None}
    c.write(work / 'DIAGNOSTIC.json', report); finish(report, trace.usage)


if __name__ == '__main__':
    main(*sys.argv[1:])
