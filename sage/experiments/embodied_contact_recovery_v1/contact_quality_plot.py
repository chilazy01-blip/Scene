"""Saved-evidence research figure; no physics or camera rendering."""
import os
from pathlib import Path
import numpy as np
import h5py
import mujoco
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from .work import E, c, finish

work = Path(os.environ['CONTINUOUS_JOB_DIR'])
source = E / 'jobs/C_development_03/episode'
m = mujoco.MjModel.from_binary_path(str(source / 'MODEL.mjb'))
oa = int(m.jnt_qposadr[m.joint('red_block_joint').id])
with h5py.File(source / 'TRACE.h5', 'r') as f:
    time = f['substep/time_before'][:]
    q = f['substep/qpos'][:]
with h5py.File(E / 'jobs/C3_contact_quality_frame_index_01/contact_quality_index.h5', 'r') as f:
    penetration = f['physics/max_penetration_m'][:]
    forbidden = f['physics/forbidden_contact'][:].astype(bool)
d = mujoco.MjData(m)
d.qpos[:] = q[0]
mujoco.mj_kinematics(m, d)
tilt = np.degrees(np.arccos(np.clip(1 - 2 * (q[:, oa + 4]**2 + q[:, oa + 5]**2), -1., 1.)))
plt.rcParams.update({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False})
fig, axes = plt.subplots(2, 2, figsize=(13, 8), constrained_layout=True)
ax = axes[0, 0]
ax.plot(time, penetration * 1000, lw=.8, color='#264653')
ax.axhline(10., color='#b42318', ls='--', label='10mm quality limit')
ax.scatter(time[forbidden], np.full(np.count_nonzero(forbidden), -.4), s=2, color='#d97706', label='Forbidden contact')
ax.set(xlabel='Simulation time (s)', ylabel='Maximum penetration (mm)', title='Contact quality over every physics step')
ax.legend(fontsize=8)
ax = axes[0, 1]
ax.plot(time + m.opt.timestep, tilt, color='#9c4221', lw=1.)
ax.axvspan(time[-1] + m.opt.timestep - 1., time[-1] + m.opt.timestep, color='#dbeafe', label='Final1s acceptance window')
ax.set(xlabel='Simulation time (s)', ylabel='Object tilt (degrees)', title='Object orientation; final placement failed')
ax.legend(fontsize=8)
ax = axes[1, 0]
ax.plot(time + m.opt.timestep, q[:, oa + 2], lw=1., color='#2563eb', label='Object centre')
for name, color in [('table_top', '#92400e'), ('table_white_top', '#0284c7')]:
    geom = m.geom(name).id
    # All bound task tables are static and axis-aligned; use actual transforms.
    top = float(d.geom_xpos[geom, 2] + m.geom_size[geom, 2])
    ax.axhline(top, ls='--', color=color, label=name + ' surface')
ax.set(xlabel='Simulation time (s)', ylabel='World height (m)', title='Lift, carry and loss of upright support')
ax.legend(fontsize=8)
ax = axes[1, 1]
ax.plot(q[:, 0], q[:, 1], color='#475569', lw=1., label='Robot base')
ax.plot(q[:, oa], q[:, oa + 1], color='#dc2626', lw=1., label='Object centre')
for name, color in [('table_top', '#d6a56a'), ('table_white_top', '#93c5fd')]:
    geom = m.geom(name).id
    center = d.geom_xpos[geom, :2]; half = m.geom_size[geom, :2]
    ax.add_patch(plt.Rectangle(center - half, 2 * half[0], 2 * half[1], color=color, alpha=.3))
ax.set(xlabel='World x (m)', ylabel='World y (m)', title='Recorded task path')
ax.set_aspect('equal', adjustable='box'); ax.legend(fontsize=8)
fig.suptitle('C3 full-body research failure —48,237steps; independent replay exact; production acceptance false', fontsize=13)
fig.savefig(work / 'C3_research_quality.png', dpi=160)
fig.savefig(work / 'C3_research_quality.pdf')
plt.close(fig)
report = {'passed': True, 'source_physics_rows': len(time), 'new_physics_steps': 0,
          'new_camera_render_passes': 0, 'production_accepted': False,
          'figure_png': str(work / 'C3_research_quality.png'),
          'figure_pdf': str(work / 'C3_research_quality.pdf'),
          'source_trace_sha256': c.sha(source / 'TRACE.h5'),
          'scope': 'Visualization of retained failed research evidence, with unchanged quality threshold.'}
finish(report)
