"""Saved transport contact geometry and the source navigator's clearance assumptions."""
import numpy as np
import h5py
import mujoco
from .work import E, c, finish

folder = E / 'jobs/C_development_03/episode'
m = mujoco.MjModel.from_binary_path(str(folder / 'MODEL.mjb'))
d = mujoco.MjData(m)
obj = m.body('red_block').id
oa = int(m.jnt_qposadr[m.joint('red_block_joint').id])
records, candidates = [], []
with h5py.File(folder / 'TRACE.h5', 'r') as f:
    times = f['substep/time_before'][:]
    contacts = f['contacts/rows'][:]
    bad = [r for r in contacts if any((m.geom(int(g)).name or '').startswith('table_leg') for g in r[1:3])
           and any((m.body(int(m.geom_bodyid[int(g)])).name or '').endswith('_knee_link') for g in r[1:3]) and r[3] < 0]
    assert bad
    first = int(bad[0][0])
    knee = next(int(g) for g in bad[0][1:3] if m.body(int(m.geom_bodyid[int(g)])).name.endswith('_knee_link'))
    leg = next(int(g) for g in bad[0][1:3] if (m.geom(int(g)).name or '').startswith('table_leg'))
    table = m.geom('table_top').id
    sample_rows = sorted(set([*range(max(0, first-240), first+161, 40), first, int(max(bad, key=lambda r: -r[3])[0])]))
    for k in sample_rows:
        mujoco.mj_setState(m, d, f['substep/integration_before'][k], mujoco.mjtState.mjSTATE_INTEGRATION)
        mujoco.mj_forward(m, d)
        table_center, half = d.geom_xpos[table, :2], m.geom_size[table, :2]
        base_delta = abs(d.qpos[:2] - table_center) - half
        close = [ct for ct in d.contact if {ct.geom1, ct.geom2} == {knee, leg}]
        records.append({'row': k, 'time': float(times[k]), 'base_xyz': d.qpos[:3].tolist(),
                        'base_clearance_to_table_rect_axes_m': base_delta.tolist(),
                        'base_inside_source_inflated_brown_box_0p20m': bool(np.all(base_delta < .20)),
                        'knee_geom_center': d.geom_xpos[knee].tolist(), 'table_leg_center': d.geom_xpos[leg].tolist(),
                        'knee_relative_to_base_xyz': (d.geom_xpos[knee]-d.qpos[:3]).tolist(),
                        'actual_pair_penetration_m': max([max(0.,-ct.dist) for ct in close], default=0.)})
    for shift in [0., -.02, -.04, -.08, -.12]:
        max_pen = 0.
        for row in bad:
            k = int(row[0])
            mujoco.mj_setState(m, d, f['substep/integration_before'][k], mujoco.mjtState.mjSTATE_INTEGRATION)
            d.qpos[0] += shift
            d.qpos[oa] += shift
            mujoco.mj_forward(m, d)
            for ct in d.contact:
                if {ct.geom1, ct.geom2} == {knee, leg}:
                    max_pen = max(max_pen, float(-ct.dist))
        candidates.append({'whole_robot_and_held_object_x_shift_m': shift, 'max_pair_penetration_m': max_pen,
                           'all_saved_violating_rows_examined': len(bad)})
report = {'physics_steps':0, 'policy_calls':0, 'source':str(folder),
          'first_pair_contact': {'row':first,'time':float(times[first]),'geoms':[m.geom(knee).name,m.geom(leg).name]},
          'records':records,'static_translation_counterfactuals':candidates,
          'navigation_source': {'table_box_inflation_m':.20,
                                'known_algorithm_behavior':'Source skips a table if start or goal is inside its inflated box and uses straight fallback when no graph route is found.'},
          'interpretation_limit':'Saved collision geometry and translation clearance only; changing navigation requires new measured path planning and dynamic qualification.',
          'production_accepted':False}
c.write(E/'C3_TRANSPORT_CONTACT_GEOMETRY.json',report)
finish(report)
