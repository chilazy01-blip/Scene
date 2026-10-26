"""Restore measured controller memory and test commands without integrating."""
import os
import sys
from pathlib import Path
import numpy as np
import h5py
import mujoco
from .work import E, R, c, finish
from .leg_interpolation import LegInterpolation


def main():
    work = Path(os.environ['CONTINUOUS_JOB_DIR'])
    source = R / 'branches/A/source'
    folder = E / 'jobs/C_development_03/episode'
    os.environ.update(NP_ROOT=str(R), NP_JOB=str(work))
    sys.path.insert(0, str(R / 'tools'))
    sys.path.insert(0, str(source))
    from . import trace_r4
    sys.modules['instrument'] = trace_r4
    from .target_adapter_r4 import install
    install('A', 'gain_translation', work / 'interface')
    import run
    m = mujoco.MjModel.from_binary_path(str(folder / 'MODEL.mjb'))
    d = mujoco.MjData(m)
    policies = [run.ONNXPolicy(str(source / (name + '.onnx')))
                for name in ['walker', 'croucher', 'rotator']]
    ctrl = run.G1Controller(m, d, *policies, c.read(source / 'model_config.json'))
    ids = [i for i, name in enumerate(ctrl.joint_names)
           if any(x in name for x in ['hip', 'knee', 'ankle'])]
    hands = [i for i in range(m.nu) if 'hand' in m.actuator(i).name]
    calls = []
    def policy(obs):
        action = policies[0](obs)
        calls.append((obs.copy(), action.copy()))
        return action
    ctrl.walker_policy = policy
    mujoco.mj_step = lambda *a, **kw: (_ for _ in ()).throw(AssertionError('no_integration'))
    rows = list(range(6752, 6881, 8))
    results = []
    with h5py.File(folder / 'TRACE.h5', 'r') as f:
        policy_group = f['policy/walker_onnx']
        policy_rows = policy_group['physics_row'][:]
        input_key = next(iter(policy_group['input']))
        output_key = next(iter(policy_group['output']))
        for row in rows:
            idx = int(np.searchsorted(policy_rows, row))
            assert policy_rows[idx] == row
            obs = policy_group['input'][input_key][idx].reshape(-1)
            action = policy_group['output'][output_key][idx].reshape(-1)
            mujoco.mj_setState(m, d, f['substep/integration_before'][row],
                              mujoco.mjtState.mjSTATE_INTEGRATION)
            mujoco.mj_forward(m, d)
            ctrl.last_action = obs[-32:-3].copy()
            ctrl.lin_vel_x, ctrl.lin_vel_y, ctrl.ang_vel_z = map(float, obs[-3:])
            target = ctrl.step()
            # The planner's current arm request is separately recorded. Restore
            # it as controller memory, never as a simulator pose write.
            target[ctrl.right_arm_indices] = f['interpolation/requested'][row][ctrl.right_arm_indices]
            interp = LegInterpolation(ids, 8)
            interp.apply(f['interpolation/applied'][row - 1])
            applied = interp.apply(target)
            ctrl.apply_pd_control(applied)
            # This source window is before closure. Verify that the previous
            # physical hand reference, rather than a future command, suffices.
            d.ctrl[hands] = f['substep/ctrl'][row - 1][hands]
            errors = {
                'policy_input': float(np.max(abs(calls[-1][0] - obs))),
                'policy_output': float(np.max(abs(calls[-1][1] - action))),
                'requested_target': float(np.max(abs(target - f['interpolation/requested'][row]))),
                'interpolated_target': float(np.max(abs(applied - f['interpolation/applied'][row]))),
                'actual_actuator_command': float(np.max(abs(d.ctrl - f['substep/ctrl'][row]))),
            }
            results.append({'row': row, 'time': float(d.time), 'maximum_errors': errors})
    report = {'passed': all(max(x['maximum_errors'].values()) < 1e-7 for x in results),
              'physics_steps': 0, 'policy_calls': len(calls), 'rows': results,
              'source': str(folder), 'production_accepted': False,
              'scope': 'Independent one-command restoration at each saved policy boundary; does not claim closed-loop dynamics equivalence or source coroutine restoration.'}
    c.write(E / 'C3_SAVED_WALKER_INTERFACE_PREFLIGHT.json', report)
    finish(report, {'wbc_forwards': len(calls)})
    assert report['passed'], results


if __name__ == '__main__':
    main()
