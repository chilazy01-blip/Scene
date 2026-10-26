"""Export source-bound diagnostic contact continuity; each panel is a separate window."""
import os
from pathlib import Path
import numpy as np
import h5py
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from .work import E,c,finish
work=Path(os.environ['CONTINUOUS_JOB_DIR'])
names=['D_tripod_window_01','D_carry_window_01','D_carry_recontact_window_02','D_carry_recontact_preload_03','D_retained_grasp_walk_01','D_retained_grasp_walk_guard_02']
titles=['Acquire tripod and lift','Move arm toward torso','Recontact, same preload','Recontact, larger command preload','Keep arm pose, retreat','Retreat with sole motor guard']
fig,axes=plt.subplots(3,2,figsize=(13,10),layout='constrained');sources=[]
for ax,name,title in zip(axes.ravel(),names,titles):
 folder=E/'jobs'/name;model=c.read(folder/'episode/MODEL.json');report=c.read(folder/'RESULT.json')
 with h5py.File(folder/'episode/TRACE.h5','r') as f:
  times=f['substep/time_before'][:];times-=times[0];contacts=f['contacts/rows'][:];steps=len(times);depth=np.zeros(steps);digits=[set() for _ in range(steps)]
  for row in contacts:
   k=int(row[0]);depth[k]=max(depth[k],-row[3]*1000);g=[model['geom_names'][int(row[i])] or '' for i in [1,2]]
   if any('red' in x for x in g):
    for digit in ['index','middle','thumb']:
     if any(digit in x and 'right' in x for x in g):digits[k].add(digit)
  ax.plot(times,depth,color='#bd4b22',lw=1,label='All-contact penetration (mm)');ax.axhline(10,color='#bd4b22',ls='--',lw=.8);ax.set_ylim(0,13);ax.set_ylabel('Penetration (mm)');ax.set_xlabel('Time since saved window start (s)')
  twin=ax.twinx();twin.step(times,[len(x) for x in digits],where='post',color='#136fa1',lw=1,label='Contacting digits');twin.set_ylim(-.1,3.4);twin.set_yticks([0,1,2,3]);twin.set_ylabel('Contacting digits',color='#136fa1');ax.set_title(title,loc='left',fontsize=11);ax.grid(alpha=.15)
  sources.append({'job':name,'steps':steps,'trace_sha256':c.sha(folder/'episode/TRACE.h5'),'result_sha256':c.sha(folder/'RESULT.json'),'abort':report.get('scientific_window_abort'),'maximum_penetration_mm':float(max(depth))})
fig.suptitle('D contact recovery diagnostics — separate research windows, no full-task success',fontsize=13)
for ext in ['png','pdf']:fig.savefig(work/('D_contact_research_windows.'+ext),dpi=170)
plt.close(fig)
report={'physics_steps':0,'render_passes':0,'sources':sources,'plot_scope':'Saved actual contacts, all-contact maximum depth and distinct contacted digits. Contact count alone is not a force-closure or empirical material certificate. Independent windows are not concatenated into a full episode.','production_accepted':False}
c.write(work/'PLOT_BINDING.json',report);finish(report)
