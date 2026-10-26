"""D compact-arm measured approach and stop from an actual saved walk state."""
import os
import sys
import traceback
from pathlib import Path
import numpy as np
import h5py
import mujoco
from .work import E, R, c, finish
from .leg_interpolation import LegInterpolation
from .saved_walk_to_control import MeasuredWalkTo
from . import trace_r4


def main(config_file):
    cfg = c.read(config_file)
    approval = c.read(E / 'DIAGNOSTIC_WINDOW_REPLAN_APPROVAL.json')
    assert approval['approved'] and approval['proposal_sha256'] == c.sha(E / 'DIAGNOSTIC_WINDOW_REPLAN_PROPOSAL.json')
    work = Path(os.environ['CONTINUOUS_JOB_DIR'])
    source = R / 'branches/A/source'
    folder = Path(cfg['source_folder'])
    start, steps = cfg['start_row'], cfg['saved_steps']
    assert start % 8 == 0 and 0 < steps <= 4000
    with h5py.File(folder / 'TRACE.h5', 'r') as f:
        policy = f['policy/walker_onnx']
        idx = int(np.searchsorted(policy['physics_row'][:], start))
        assert int(policy['physics_row'][idx]) == start
        observation = policy['input'][next(iter(policy['input']))][idx].reshape(-1)
        initial = f['substep/integration_before'][start]
        previous = f['interpolation/applied'][start - 1]
        arm_request = f['interpolation/requested'][start]
        expected_first = f['substep/ctrl'][start]
        hand_command = f['substep/ctrl'][start - 1]
    os.environ.update(NP_ROOT=str(R), NP_JOB=str(work))
    sys.path.insert(0, str(R / 'tools')); sys.path.insert(0, str(source))
    sys.modules['instrument'] = trace_r4
    c.write(work / 'USAGE.json', {k: 0 for k in c.read(work / 'REQUEST.json')['reservation']})
    trace = trace_r4.Trace(work / 'episode', 'diagnostic'); trace.install()
    error = None; reached = None; first_error = None
    try:
        from .target_adapter_r4 import install
        install('A', 'gain_translation', work / 'episode')
        import run
        m = mujoco.MjModel.from_binary_path(str(folder / 'MODEL.mjb'))
        d = mujoco.MjData(m)
        mujoco.mj_setState(m, d, initial, mujoco.mjtState.mjSTATE_INTEGRATION)
        mujoco.mj_forward(m, d)
        policies = [run.ONNXPolicy(str(source / (name + '.onnx'))) for name in ['walker', 'croucher', 'rotator']]
        ctrl = run.G1Controller(m, d, *policies, c.read(source / 'model_config.json'))
        ctrl.last_action = observation[-32:-3].copy()
        legs = [i for i, name in enumerate(ctrl.joint_names) if any(x in name for x in ['hip', 'knee', 'ankle'])]
        arms = [i for i, name in enumerate(ctrl.joint_names) if any(x in name for x in ['shoulder', 'elbow', 'wrist'])]
        hands = [i for i in range(m.nu) if 'hand' in m.actuator(i).name]
        interpolation = LegInterpolation(legs, 8); interpolation.apply(previous)
        navigation = MeasuredWalkTo(cfg['goal_xy'], cfg['goal_yaw'], .07)
        assert np.max(abs(navigation.command(d) - observation[-3:])) < 1e-7
        guard = None
        if cfg.get('sole_guard_options') is not None:
            from .all_sole_guard import AllSoleGuard
            guard = AllSoleGuard(m, **cfg['sole_guard_options'])
        for k in range(steps):
            if k % 8 == 0:
                ctrl.lin_vel_x, ctrl.lin_vel_y, ctrl.ang_vel_z = map(float, navigation.command(d))
                requested = ctrl.step()
                requested[arms] = arm_request[arms]
            applied = interpolation.apply(requested)
            trace.append('interpolation/requested', requested); trace.append('interpolation/applied', applied)
            ctrl.apply_pd_control(applied)
            d.ctrl[hands] = hand_command[hands]
            if first_error is None:
                first_error = float(np.max(abs(d.ctrl - expected_first)))
                assert first_error < 1e-7
            if guard:
                row = guard.apply(d)
                trace.append('sole_guard/physics_row', trace.n)
                trace.append('sole_guard/motor_delta_Nm', row['motor_delta_Nm'])
                trace.append('sole_guard/barriers', row['issued_barrier'])
            mujoco.mj_step(m, d)
            navigation.after_step(d)
            if reached is None and navigation.stopped:
                reached = float(d.time)
    except BaseException:
        error = traceback.format_exc(); print(error, flush=True)
    finally:
        summary = trace.close()
    report = {'outcome': 'engineering_failure' if error else 'success',
              'engineering_error': error, 'summary': summary,
              'source_row': start, 'first_nominal_command_error': first_error,
              'goal_entered_tolerance_time': reached,
              'final_goal_distance_m': float(np.linalg.norm(d.qpos[:2] - cfg['goal_xy'])) if 'd' in locals() else None,
              'fixed_actual_compact_arm_requests': True,
              'full_task': False, 'production_accepted': False, 'new_complete_task_attempts': 0}
    c.write(work / 'DIAGNOSTIC.json', report); finish(report, trace.usage)


if __name__ == '__main__':
    main(sys.argv[1])
