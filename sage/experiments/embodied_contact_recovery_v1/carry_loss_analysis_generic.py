"""Locate the first missing digit and test constrained static recontact geometry."""
import sys
import numpy as np
import h5py
import mujoco
from .work import E, c, finish
from .planned_tripod_r2 import contact_geometry
from .tripod_recontact import plan_recontact


def main(config_path):
    cfg=c.read(config_path)
    folder = __import__('pathlib').Path(cfg['source_episode'])
    m = mujoco.MjModel.from_binary_path(str(folder / 'MODEL.mjb')); d = mujoco.MjData(m)
    obj = m.body('red_block').id; site = m.site('right_palm').id
    with h5py.File(folder / 'TRACE.h5', 'r') as f:
        contacts = f['contacts/rows'][:]; n = len(f['substep/qpos'])
        digits = [set() for _ in range(n)]
        for ct in contacts:
            bodies = [int(m.geom_bodyid[int(g)]) for g in ct[1:3]]
            if obj not in bodies or ct[3] > 0: continue
            for body in bodies:
                name = m.body(body).name
                if name.startswith('right_hand'): digits[int(ct[0])].add(name.split('_')[2])
        lost = next(i for i, row in enumerate(digits) if row != {'index', 'middle', 'thumb'})
        rows = sorted(set([0, max(0, lost - 40), max(0, lost - 8), lost, n - 1]))
        measurements = []; reference = None
        for k in rows:
            mujoco.mj_setState(m, d, f['substep/integration_before'][k], mujoco.mjtState.mjSTATE_INTEGRATION)
            mujoco.mj_forward(m, d)
            wrist = d.site_xmat[site].reshape(3, 3); relative = wrist.T @ (d.xpos[obj] - d.site_xpos[site])
            if reference is None: reference = relative.copy()
            item = {'row': k, 'time': float(d.time), 'grasp': contact_geometry(m, d, obj),
                    'relative_object_palm_translation_m': relative.tolist(),
                    'relative_translation_change_m': float(np.linalg.norm(relative - reference)),
                    'object_xyz': d.xpos[obj].tolist(), 'palm_xyz': d.site_xpos[site].tolist(),
                    'finger_controller': f['finger_governor/control'][k].tolist()}
            if k >= lost: item['recontact_plan'] = plan_recontact(m, d, obj)
            measurements.append(item)
    report = {'physics_steps': 0, 'first_missing_digit_row': lost, 'states': measurements,
              'source_trace_sha256': c.sha(folder / 'TRACE.h5'),
              'interpretation': 'The fixed initial contact references cannot close further when the measured object moves away from a digit. A bounded scratch recontact search tests whether the lost contact remains reachable; dynamic effectiveness remains unproven.',
              'production_accepted': False}
    c.write(E / cfg['output'], report); finish(report)


if __name__ == '__main__': main(sys.argv[1])
