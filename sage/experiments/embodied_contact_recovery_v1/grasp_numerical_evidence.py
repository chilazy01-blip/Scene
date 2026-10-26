"""Object/hand-specific numerical windows, separate from foot-only checks."""
import sys
from pathlib import Path
import numpy as np
import h5py
import mujoco
from .work import E, c, finish


def hand_rows(m, rows):
    obj = m.body('red_block').id
    mask = []
    for row in rows:
        bodies = [int(m.geom_bodyid[int(g)]) for g in row[1:3]]
        mask.append(obj in bodies and any(m.body(b).name.startswith('right_hand') for b in bodies))
    return rows[np.asarray(mask, bool)]


def prepare():
    folder = E / 'jobs/D_tripod_window_01/episode'
    m = mujoco.MjModel.from_binary_path(str(folder / 'MODEL.mjb'))
    with h5py.File(folder / 'TRACE.h5', 'r') as f:
        rows = hand_rows(m, f['contacts/rows'][:]); count = len(f['substep/qpos'])
        forces = np.zeros(count)
        np.add.at(forces, rows[:, 0].astype(int), np.maximum(rows[:, 7], 0.))
        peak_force = int(np.argmax(forces))
        peak_penetration = int(rows[np.argmin(rows[:, 3]), 0])
        first = int(rows[0, 0])
    windows = []
    for label, peak in [('peak_force', peak_force), ('peak_penetration', peak_penetration)]:
        start = max(0, min(peak - 40, count - 80)); cases = []
        for factor, solver in [(1, 1), (2, 1), (4, 1), (1, 2)]:
            path = E / 'cases' / f'D_tripod_hand_{label}_f{factor}_s{solver}.json'
            assert not path.exists()
            c.write(path, {'source_folder': str(folder), 'start_row': start, 'saved_steps': 80,
                           'subdivisions': factor, 'solver_iteration_factor': solver,
                           'fixed_actual_commands': True, 'selected_contact': 'object/right_hand'})
            cases.append(str(path))
        windows.append({'label': label, 'peak_row': peak, 'start_row': start, 'saved_steps': 80, 'cases': cases})
    report = {'physics_steps': 0, 'source_trace_sha256': c.sha(folder / 'TRACE.h5'),
              'first_hand_contact_row': first, 'peak_hand_normal_force_N': float(forces[peak_force]),
              'peak_hand_penetration_m': float(-rows[:, 3].min()), 'windows': windows,
              'scope': 'Two200ms hand/object contact transients selected by actual force and penetration. Total1280finer integrations; not a whole-grasp or force calibration proof.'}
    c.write(E / 'D_TRIPOD_HAND_NUMERICAL_DESIGN.json', report); finish(report)


def read_window(name):
    folder = E / 'jobs' / name / 'episode'
    m = mujoco.MjModel.from_binary_path(str(folder / 'MODEL.mjb'))
    obj_joint = m.joint('red_block_joint').id
    qa, va = int(m.jnt_qposadr[obj_joint]), int(m.jnt_dofadr[obj_joint])
    with h5py.File(folder / 'TRACE.h5', 'r') as f:
        q, v, rows = f['substep/qpos'][:], f['substep/qvel'][:], hand_rows(m, f['contacts/rows'][:])
        times = f['substep/time_before'][:] + m.opt.timestep
    assert len(rows), 'no_actual_hand_object_contact_in_numerical_window'
    normal = np.zeros(len(q)); np.add.at(normal, rows[:, 0].astype(int), np.maximum(rows[:, 7], 0.))
    factor = round(.0025 / m.opt.timestep); ids = np.arange(factor - 1, len(q), factor)
    return {'time': times[ids], 'base': q[ids, :3], 'object': q[ids, qa:qa + 3],
            'velocity': v[ids, va:va + 3], 'peak_normal_N': float(normal.max()),
            'impulse_Ns': float(normal.sum() * m.opt.timestep),
            'max_hand_penetration_m': float(-rows[:, 3].min())}


def review(config_file):
    cfg = c.read(config_file); names = cfg['jobs']; samples = [read_window(n) for n in names]
    comparisons = []
    for i, j in [(0, 1), (1, 2), (0, 2), (0, 3)]:
        a, b = samples[i], samples[j]
        assert np.max(abs(a['time'] - b['time'])) < 1e-9
        row = {'first': names[i], 'second': names[j]}
        for key in ['base', 'object', 'velocity']:
            row[key + '_max_difference'] = float(np.max(np.linalg.norm(a[key] - b[key], axis=1)))
        for key in ['peak_normal_N', 'impulse_Ns']:
            row[key + '_relative_difference'] = abs(a[key] - b[key]) / max(abs(b[key]), 1e-12)
        row['gates'] = {'base_2mm': row['base_max_difference'] <= .002,
                        'object_2mm': row['object_max_difference'] <= .002,
                        'object_speed_005mps': row['velocity_max_difference'] <= .05,
                        'hand_peak_20percent': row['peak_normal_N_relative_difference'] <= .2,
                        'hand_impulse_10percent': row['impulse_Ns_relative_difference'] <= .1}
        comparisons.append(row)
    exact = c.read(E / 'jobs' / names[0] / 'RESULT.json')['endpoint_max_abs_qpos_difference'] == 0.
    result = {'physics_steps': 0, 'nominal_replay_endpoint_exact': exact,
              'windows': {name: {k: v for k, v in sample.items() if k in ['peak_normal_N', 'impulse_Ns', 'max_hand_penetration_m']} for name, sample in zip(names, samples)},
              'comparisons': comparisons, 'local_hand_numerical_passed': exact and all(all(x['gates'].values()) for x in comparisons),
              'empirical_force_calibration': False, 'production_accepted': False}
    c.write(E / cfg['output'], result); finish(result)


if __name__ == '__main__':
    if sys.argv[1] == 'prepare': prepare()
    else: review(sys.argv[2])
