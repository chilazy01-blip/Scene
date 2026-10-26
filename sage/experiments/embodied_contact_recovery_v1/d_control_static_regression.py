"""Exercise D segments and physical joint-hold commands on saved C3 states."""
import os, sys
from pathlib import Path
import numpy as np
import h5py
import mujoco
from .work import E, R, c, finish

work = Path(os.environ['CONTINUOUS_JOB_DIR'])
os.environ.update(NP_ROOT=str(R), NP_JOB=str(work))
sys.path.insert(0, str(R / 'tools'))
sys.path.insert(0, str(R / 'branches/A/source'))
from .target_adapter_r4 import install
install('A', 'gain_translation', work / 'static_interface')
import run
from ik.sim import ArmIK6
from .object_pose_receding import segment_clear, relative_pose, relative_error
from .contact_finger_hold import MeasuredFingerHold

folder = E / 'jobs/C_development_03/episode'
m = mujoco.MjModel.from_binary_path(str(folder / 'MODEL.mjb'))
d = mujoco.MjData(m)
ctrl = run.G1Controller(m, d, None, None, None, c.read(R / 'branches/A/source/model_config.json'))
ik = ArmIK6(m, ctrl)
class Runner:
    model, data, cyl_bid = m, d, m.body('red_block').id
    def __init__(self): self.ik = ik
    def palm_pose(self): return d.site_xpos[ik.site_id].copy(), d.site_xmat[ik.site_id].reshape(3, 3).copy()
    def cyl_pos(self): return d.xpos[self.cyl_bid].copy()
runner = Runner()
plans = c.read(E / 'D_C3_PREPLACE_STATIC_REGRESSION.json')['saved_pre_place_cases']
results = []
with h5py.File(folder / 'TRACE.h5', 'r') as f:
    for item in plans:
        k = item['source_row']
        mujoco.mj_setState(m, d, f['substep/integration_before'][k], mujoco.mjtState.mjSTATE_INTEGRATION)
        mujoco.mj_forward(m, d)
        initial_q, initial_v = d.qpos.copy(), d.qvel.copy()
        target = np.asarray(item['result']['variables'][:-2])
        delta = target - d.qpos[ik.qpos_idx]
        next_q = d.qpos[ik.qpos_idx] + delta * min(1., .045 / max(abs(delta)))
        check = segment_clear(runner, next_q)
        assert check['passed'] and np.array_equal(d.qpos, initial_q) and np.array_equal(d.qvel, initial_v)
        assert max(relative_error(relative_pose(runner), relative_pose(runner))) < 1e-10
        governor = MeasuredFingerHold(m)
        d.ctrl[:] = f['substep/ctrl'][k]
        governor.apply(m, d)
        governor.hold(m, d)
        references = dict(governor.reference)
        # Perturb only the scratch data's finger encoders: a fixed reference
        # should oppose overshoot instead of moving further with the encoder.
        qa = governor.qa
        directions = np.array([-1. if ('thumb_1' in m.actuator(a).name or 'thumb_2' in m.actuator(a).name) else 1. for a in governor.aids])
        d.qpos[qa] += .06 * directions
        governed = governor.apply(m, d)
        held = [i for i, a in enumerate(governor.aids) if int(a) in references]
        assert held and all(governor.reference[int(governor.aids[i])] == references[int(governor.aids[i])] for i in held)
        errors = d.ctrl[governor.aids] - d.qpos[qa]
        assert max(abs(errors[held])) <= .03 + 1e-12
        assert all(errors[i] * directions[i] <= 1e-12 for i in held)
        governor.release()
        assert not governor.holding and not governor.reference
        results.append({'source_row': k, 'segment': check, 'held_actuators': [m.actuator(governor.aids[i]).name for i in held],
                        'fixed_reference_unchanged': True, 'overshoot_command_returns_toward_reference': True,
                        'maximum_hold_command_error_rad': float(max(abs(errors[held]))), 'release_clears_hold': True})
report = {'physics_steps': 0, 'policy_calls': 0, 'saved_state_cases': results, 'passed': True,
          'scope': 'Real-model scratch kinematics and position-actuator command semantics; no dynamics or grip stability proven.',
          'dynamic_admission': False, 'production_accepted': False}
c.write(E / 'D_CONTROL_STATIC_REGRESSION.json', report)
finish(report)
