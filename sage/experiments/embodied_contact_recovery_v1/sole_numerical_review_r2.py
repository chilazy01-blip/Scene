"""Read-only synchronized sole trajectories and contact impulse convergence."""
import os
import sys
from pathlib import Path
import numpy as np
import h5py
import mujoco
from .work import E, c, finish


def load(name):
    folder = E / 'jobs' / name / 'episode'
    m = mujoco.MjModel.from_binary_path(str(folder / 'MODEL.mjb'))
    d = mujoco.MjData(m)
    soles = [g for g in range(m.ngeom) if 'ankle_roll' in m.body(int(m.geom_bodyid[g])).name
             and m.geom_type[g] == mujoco.mjtGeom.mjGEOM_SPHERE and m.geom_contype[g]]
    assert len(soles) == 8
    with h5py.File(folder / 'TRACE.h5', 'r') as f:
        q, v = f['substep/qpos'][:], f['substep/qvel'][:]
        contacts = f['contacts/rows'][:]
        times = f['substep/time_before'][:] + m.opt.timestep
    factor = round(.0025 / m.opt.timestep)
    ids = np.arange(factor - 1, len(q), factor)
    points, velocities = [], []
    for k in ids:
        d.qpos[:] = q[k]
        mujoco.mj_kinematics(m, d)
        mujoco.mj_comPos(m, d)
        points.append(d.geom_xpos[soles].copy())
        speeds = []
        for g in soles:
            J = np.zeros((3, m.nv))
            mujoco.mj_jac(m, d, J, None, d.geom_xpos[g], int(m.geom_bodyid[g]))
            speeds.append(J @ v[k])
        velocities.append(speeds)
    stats = {}
    for side in ['left', 'right']:
        gs = [g for g in soles if m.body(int(m.geom_bodyid[g])).name.startswith(side)]
        selected = contacts[np.isin(contacts[:, 1], gs) | np.isin(contacts[:, 2], gs)]
        normal = np.maximum(selected[:, 7], 0.)
        stats[side] = {'normal_impulse_Ns': float(normal.sum() * m.opt.timestep),
                       'maximum_contact_force_N': float(np.max(np.linalg.norm(selected[:, 7:10], axis=1), initial=0.))}
    return {'times': times[ids], 'q': q[ids], 'v': v[ids], 'points': np.array(points),
            'velocities': np.array(velocities), 'stats': stats,
            'max_penetration_m': float(max(0., -contacts[:, 3].min()))}


def main(config_file):
    cfg = c.read(config_file)
    names = cfg['jobs']
    samples = {name: load(name) for name in names}
    comparisons = []
    for first, second in [(names[i], names[j]) for i, j in cfg['comparison_indices']]:
        a, b = samples[first], samples[second]
        assert np.max(abs(a['times'] - b['times'])) < 1e-9
        row = {'first': first, 'second': second,
               'sole_position_max_difference_m': float(np.max(np.linalg.norm(a['points'] - b['points'], axis=2))),
               'sole_velocity_max_difference_mps': float(np.max(np.linalg.norm(a['velocities'] - b['velocities'], axis=2))),
               'base_position_max_difference_m': float(np.max(np.linalg.norm(a['q'][:, :3] - b['q'][:, :3], axis=1))),
               'all_qpos_max_difference': float(np.max(abs(a['q'] - b['q']))),
               'per_foot': {}}
        for side in ['left', 'right']:
            row['per_foot'][side] = {key + '_relative_difference': abs(a['stats'][side][key] - b['stats'][side][key]) / max(abs(b['stats'][side][key]), 1e-12)
                                     for key in ['normal_impulse_Ns', 'maximum_contact_force_N']}
        row['gates'] = {'position_2mm': row['sole_position_max_difference_m'] <= .002,
                        'speed_005mps': row['sole_velocity_max_difference_mps'] <= .05,
                        'impulse_10percent': all(x['normal_impulse_Ns_relative_difference'] <= .1 for x in row['per_foot'].values()),
                        'peak_20percent': all(x['maximum_contact_force_N_relative_difference'] <= .2 for x in row['per_foot'].values())}
        row['passed'] = all(row['gates'].values())
        comparisons.append(row)
    exact = c.read(E / 'jobs' / names[0] / 'RESULT.json')['endpoint_max_abs_qpos_difference'] == 0.
    report = {'physics_steps': 0, 'nominal_replay_endpoint_exact': exact,
              'windows': {name: {k: val for k, val in sample.items() if k in ['stats', 'max_penetration_m']} for name, sample in samples.items()},
              'comparisons': comparisons, 'local_numerical_gates_passed': exact and all(x['passed'] for x in comparisons),
              'scope': 'Same saved state and actual400Hz motor commands held over finer substeps; synchronized post-step sole positions/velocities and per-foot impulse/peak. No closed-loop numerical qualification.',
              'production_accepted': False}
    c.write(E / cfg['output'], report)
    finish(report)


if __name__ == '__main__':
    main(sys.argv[1])
