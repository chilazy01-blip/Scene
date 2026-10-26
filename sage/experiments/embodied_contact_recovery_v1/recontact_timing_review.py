"""Measured contact persistence and actuator/friction terms during recontact."""
import numpy as np
import h5py
import mujoco
from .work import E, c, finish


def main():
    folder = E / 'jobs/D_carry_recontact_window_02/episode'
    m = mujoco.MjModel.from_binary_path(str(folder / 'MODEL.mjb')); d = mujoco.MjData(m)
    obj = m.body('red_block').id
    with h5py.File(folder / 'TRACE.h5', 'r') as f:
        contacts = f['contacts/rows'][:]; n = len(f['substep/qpos'])
        digits = [set() for _ in range(n)]; normal = np.zeros((n, 3)); keys = ['index', 'middle', 'thumb']
        for ct in contacts:
            bodies = [int(m.geom_bodyid[int(g)]) for g in ct[1:3]]
            if obj not in bodies or ct[3] > 0: continue
            for body in bodies:
                name = m.body(body).name
                if name.startswith('right_hand'):
                    digit = name.split('_')[2]; digits[int(ct[0])].add(digit)
                    normal[int(ct[0]), keys.index(digit)] += max(0., ct[7])
        good = np.array([x == set(keys) for x in digits])
        starts = np.flatnonzero(good & ~np.r_[False, good[:-1]])
        stops = np.flatnonzero(good & ~np.r_[good[1:], False]) + 1
        intervals = [{'first_row': int(a), 'stop_row': int(b), 'seconds': float((b - a) * m.opt.timestep),
                      'minimum_index_normal_N': float(normal[a:b, 0].min())} for a, b in zip(starts, stops)]
        samples = []
        for k in sorted(set([0, n - 1, *range(40, n, 40)])):
            mujoco.mj_setState(m, d, f['substep/integration_before'][k], mujoco.mjtState.mjSTATE_INTEGRATION)
            mujoco.mj_forward(m, d)
            values = []
            for part in ['index_0', 'index_1']:
                aid = m.actuator('right_hand_' + part + '_joint').id
                jid = int(m.actuator_trnid[aid, 0]); qa, va = int(m.jnt_qposadr[jid]), int(m.jnt_dofadr[jid])
                values.append({'joint': part, 'q': float(d.qpos[qa]), 'velocity_rps': float(d.qvel[va]),
                               'command': float(f['substep/ctrl'][k, aid]),
                               'actual_actuator_force_Nm': float(f['substep/actuator_force'][k, aid]),
                               'frictionloss_Nm': float(m.dof_frictionloss[va]),
                               'gravity_bias_Nm': float(d.qfrc_bias[va]),
                               'contact_and_friction_constraint_Nm': float(f['substep/qfrc_constraint'][k, va])})
            samples.append({'row': k, 'time': float(d.time), 'digits': sorted(digits[k]),
                            'normal_force_by_digit_N': normal[k].tolist(), 'index': values})
    report = {'physics_steps': 0, 'three_digit_contact_intervals': intervals, 'samples': samples,
              'terminal_contact_interval_seconds': intervals[-1]['seconds'] if intervals and intervals[-1]['stop_row'] == n else 0.,
              'longest_three_digit_interval_seconds': max([x['seconds'] for x in intervals], default=0.),
              'required_existing_stable_interval_seconds': .1, 'existing_recontact_timeout_seconds': .8,
              'production_accepted': False}
    c.write(E / 'D_RECONTACT_TIMING_AND_FORCE.json', report); finish(report)


if __name__ == '__main__': main()
