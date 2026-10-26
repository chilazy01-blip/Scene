"""Attach full400Hz contact failures to25Hz data intervals without observation leakage."""
import os
from pathlib import Path
import numpy as np
import h5py
import mujoco
from .work import E, c, finish

work = Path(os.environ['CONTINUOUS_JOB_DIR'])
folder = E / 'jobs/C_development_03/episode'
reference = c.read(E / 'jobs/C_development_03/RECORDED_QUALITY.json')
m = mujoco.MjModel.from_binary_path(str(folder / 'MODEL.mjb'))
obj = m.body('red_block').id
feet = {m.body(side + '_ankle_roll_link').id for side in ['left', 'right']}
roles = []
for g in range(m.ngeom):
    body = int(m.geom_bodyid[g]); ancestor = body; names = []
    while ancestor:
        names.append(m.body(ancestor).name); ancestor = int(m.body_parentid[ancestor])
    if body == obj: role = 'object'
    elif m.geom(g).name == 'ground': role = 'floor'
    elif body in feet and m.geom_contype[g]: role = 'foot'
    elif any('hand' in name for name in names): role = 'hand'
    elif 'base' in names: role = 'robot'
    else: role = 'environment'
    roles.append(role)
with h5py.File(folder / 'TRACE.h5', 'r') as f:
    times = f['substep/time_before'][:]
    contacts = f['contacts/rows'][:]
count = len(times)
penetration = np.zeros(count)
forbidden = np.zeros(count, dtype='u1')
pair_summary = {}
for row in contacts:
    k, a, b = map(int, row[:3])
    penetration[k] = max(penetration[k], -float(row[3]))
    pair = {roles[a], roles[b]}
    loaded = np.linalg.norm(row[7:10]) > 1e-4 or row[3] < -1e-6
    allowed = pair in ({'foot', 'floor'}, {'hand', 'object'}) or not bool(pair & {'foot', 'hand', 'robot'})
    if loaded and not allowed:
        forbidden[k] = 1
        key = '|'.join([m.geom(a).name or str(a), m.geom(b).name or str(b)])
        entry = pair_summary.setdefault(key, {'first_step': k, 'first_time': float(times[k]),
                                              'contact_rows': 0, 'max_penetration_m': 0., 'max_force_N': 0.})
        entry['contact_rows'] += 1
        entry['max_penetration_m'] = max(entry['max_penetration_m'], -float(row[3]))
        entry['max_force_N'] = max(entry['max_force_N'], float(np.linalg.norm(row[7:10])))
assert pair_summary == reference['forbidden_pairs'], 'contact_roles_or_gate_mismatch'
assert max(penetration) == reference['metrics']['max_penetration_m']
starts = np.arange(0, count, 16)
stops = np.minimum(starts + 16, count)
frame_pen = np.array([max(penetration[a:b]) for a, b in zip(starts, stops)])
frame_forbidden = np.array([bool(forbidden[a:b].any()) for a, b in zip(starts, stops)], dtype='u1')
frame_bits = (frame_pen > .01).astype('u1') | (frame_forbidden << 1)
with h5py.File(work / 'contact_quality_index.h5', 'w') as out:
    out.attrs['privileged_quality_only'] = True
    out.attrs['not_policy_observation_or_action'] = True
    out.attrs['not_a_complete_production_quality_gate'] = True
    out.attrs['source_task_success'] = False
    out.create_dataset('physics/time_before', data=times, compression='lzf')
    out.create_dataset('physics/max_penetration_m', data=penetration, compression='lzf')
    out.create_dataset('physics/forbidden_contact', data=forbidden, compression='lzf')
    out.create_dataset('frames/first_substep', data=starts)
    out.create_dataset('frames/stop_substep_exclusive', data=stops)
    out.create_dataset('frames/max_penetration_m', data=frame_pen)
    out.create_dataset('frames/forbidden_contact', data=frame_forbidden)
    out.create_dataset('frames/contact_failure_bits', data=frame_bits)
bad = np.flatnonzero(frame_bits)
result = {'passed': True, 'source_physics_rows': count, 'RGBD_frames': len(starts),
          'intervals_cover_all_physics_exactly_once': bool(starts[0] == 0 and stops[-1] == count
                                                        and np.array_equal(stops[:-1], starts[1:])),
          'final_interval_physics_rows': int(stops[-1] - starts[-1]),
          'frames_with_penetration_failure': int(np.count_nonzero(frame_bits & 1)),
          'frames_with_forbidden_contact': int(np.count_nonzero(frame_bits & 2)),
          'first_flagged_RGBD_frame': int(bad[0]), 'first_flagged_interval_s': [float(times[starts[bad[0]]]), float(times[stops[bad[0]] - 1] + m.opt.timestep)],
          'exact_existing_full_quality_contact_summary': True, 'contact_failure_bits': {'1': 'any_substep_penetration_over10mm', '2': 'any_loaded_forbidden_contact'},
          'quality_index_sha256': c.sha(work / 'contact_quality_index.h5'),
          'source_trace_sha256': c.sha(folder / 'TRACE.h5'), 'production_accepted': False,
          'new_physics_steps': 0, 'new_render_passes': 0, 'training_updates': 0,
          'scope': 'Privileged quality metadata across complete40ms RGBD intervals, including failures between sensor timestamps. A clear interval is not a successful task or a complete production-quality pass.'}
c.write(E / 'C3_CONTACT_QUALITY_FRAME_INDEX.json', result); finish(result)
