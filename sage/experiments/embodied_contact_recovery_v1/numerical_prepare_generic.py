"""Declare fixed-input impact windows from the measured maximum penetration."""
import sys
import h5py
import numpy as np
from .work import E, c, finish


def main(names):
    windows = []
    for name in names:
        folder = E / 'jobs' / name / 'episode'
        with h5py.File(folder / 'TRACE.h5', 'r') as f:
            contacts = f['contacts/rows'][:]
            worst = contacts[int(np.argmin(contacts[:, 3]))]
            peak = int(worst[0]); total = len(f['substep/qpos'])
            start = max(0, min(peak - 80, total - 160)); count = min(160, total - start)
            assert start <= peak < start + count
        cases = []
        for factor, solver in [(1, 1), (2, 1), (4, 1), (1, 2)]:
            label = name + f'_impact_f{factor}_s{solver}'
            path = E / 'cases' / (label + '.json')
            assert not path.exists()
            c.write(path, {'source_folder': str(folder), 'start_row': start, 'saved_steps': count,
                           'subdivisions': factor, 'solver_iteration_factor': solver,
                           'fixed_actual_commands': True})
            cases.append(str(path))
        windows.append({'source_job': name, 'source_trace_sha256': c.sha(folder / 'TRACE.h5'),
                        'peak_row': peak, 'start_row': start, 'saved_steps': count,
                        'nominal_peak_penetration_m': float(-worst[3]), 'cases': cases})
    report = {'physics_steps': 0, 'windows': windows, 'production_accepted': False,
              'scope': 'Maximum-penetration-centered400ms saved-state windows, actual motor commands held400Hz. No online feedback or full-task convergence claim.'}
    c.write(E / 'D_COMPACT_TRIPOD_NUMERICAL_DESIGN.json', report); finish(report)


if __name__ == '__main__':
    main(sys.argv[1:])
