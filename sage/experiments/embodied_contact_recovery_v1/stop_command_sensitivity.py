"""Conditional one-command policy/dynamics response to source stopping; no integration."""
import os
import sys
from pathlib import Path
import numpy as np
import h5py
import mujoco
from .work import E, R, c, finish
from .leg_interpolation import LegInterpolation
from .saved_walk_to_control import MeasuredWalkTo

work = Path(os.environ['CONTINUOUS_JOB_DIR'])
source = R / 'branches/A/source'
folder = E / 'jobs/C_development_03/episode'
os.environ.update(NP_ROOT=str(R), NP_JOB=str(work))
sys.path.insert(0, str(R / 'tools')); sys.path.insert(0, str(source))
from . import trace_r4
sys.modules['instrument'] = trace_r4
from .target_adapter_r4 import install
install('A', 'gain_translation', work / 'interface')
import run
m = mujoco.MjModel.from_binary_path(str(folder / 'MODEL.mjb')); d = mujoco.MjData(m)
policies = [run.ONNXPolicy(str(source / (name + '.onnx'))) for name in ['walker', 'croucher', 'rotator']]
ctrl = run.G1Controller(m, d, *policies, c.read(source / 'model_config.json'))
legs = [i for i, name in enumerate(ctrl.joint_names) if any(x in name for x in ['hip', 'knee', 'ankle'])]
hands = [i for i in range(m.nu) if 'hand' in m.actuator(i).name]
geoms = [m.geom(name).id for name in ['g6_col', 'g7_col', 'g8_col', 'g9_col']]
navigation = MeasuredWalkTo([-.4, .1], .35)
mujoco.mj_step = lambda *a, **kw: (_ for _ in ()).throw(AssertionError('no_integration'))
records, calls = [], 0
with h5py.File(folder / 'TRACE.h5', 'r') as f:
    policy = f['policy/walker_onnx']; rows = policy['physics_row'][:]
    input_key = next(iter(policy['input']))
    for row in [6816, 6824, 6832, 6840, 6848]:
        idx = int(np.searchsorted(rows, row)); assert rows[idx] == row
        obs = policy['input'][input_key][idx].reshape(-1)
        state = f['substep/integration_before'][row]
        mujoco.mj_setState(m, d, state, mujoco.mjtState.mjSTATE_INTEGRATION)
        hypothetical = navigation.command(d)
        variants = {}
        for label, command in [('actual_stop', obs[-3:]), ('continue_goal_command', hypothetical),
                               ('half_continue_goal_command', .5 * hypothetical)]:
            mujoco.mj_setState(m, d, state, mujoco.mjtState.mjSTATE_INTEGRATION); mujoco.mj_forward(m, d)
            ctrl.last_action = obs[-32:-3].copy()
            ctrl.lin_vel_x, ctrl.lin_vel_y, ctrl.ang_vel_z = map(float, command)
            target = ctrl.step(); calls += 1
            target[ctrl.right_arm_indices] = f['interpolation/requested'][row][ctrl.right_arm_indices]
            interpolation = LegInterpolation(legs, 8); interpolation.apply(f['interpolation/applied'][row - 1])
            ctrl.apply_pd_control(interpolation.apply(target))
            d.ctrl[hands] = f['substep/ctrl'][row - 1][hands]
            if label == 'actual_stop':
                assert np.max(abs(d.ctrl - f['substep/ctrl'][row])) < 1e-7
            mujoco.mj_forward(m, d)
            points = []
            for geom in geoms:
                body = int(m.geom_bodyid[geom]); point = d.geom_xpos[geom]
                J = np.zeros((3, m.nv)); Jr = np.zeros_like(J)
                Jd = np.zeros_like(J); Jdr = np.zeros_like(J)
                mujoco.mj_jac(m, d, J, Jr, point, body); mujoco.mj_jacDot(m, d, Jd, Jdr, point, body)
                points.append({'geom': m.geom(geom).name, 'height_m': float(point[2] - m.geom_size[geom, 0]),
                               'vz_mps': float(J[2] @ d.qvel),
                               'az_mps2': float(J[2] @ d.qacc + Jd[2] @ d.qvel)})
            variants[label] = {'high_level_command': np.asarray(command).tolist(),
                               'leg_target_rad': target[legs].tolist(), 'actual_motor_command': d.ctrl.tolist(),
                               'base_acceleration': d.qacc[:6].tolist(), 'sole_points': points}
        records.append({'row': row, 'time': float(d.time), 'variants': variants})
report = {'physics_steps': 0, 'policy_calls': calls, 'records': records,
          'actual_source_nominal_command_reconstruction_passed': True,
          'scope': 'Conditional one-policy-tick intervention on velocity-command input at identical saved physical state and previous action. Motor translation/interpolation and plant are retained. Future state or landing outcome is not predicted.',
          'dynamic_admission': False, 'production_accepted': False}
c.write(E / 'C3_STOP_COMMAND_SENSITIVITY.json', report); finish(report, {'wbc_forwards': calls})
