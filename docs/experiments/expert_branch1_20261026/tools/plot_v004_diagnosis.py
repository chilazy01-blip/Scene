from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from sage.experiments.embodied_expert_branch1_v1.common import ROOT,read_bound_json,safe_save,_file_binding
p=ROOT/'FINAL_V004_FAILURE_DIAGNOSIS.json';d=read_bound_json(p);rows=d['release_reference_observations'];x=np.array([r['release_age_ticks']*.02 for r in rows]);weight=rows[0]['weight_n']
fig,ax=plt.subplots(3,1,figsize=(9,8),sharex=True,layout='constrained')
ax[0].plot(x,[r['table_vertical_n'] for r in rows],label='Table upward force');ax[0].plot(x,[r['hand_vertical_n'] for r in rows],label='Hand upward force');ax[0].axhline(weight,color='k',ls='--',label='Weight');ax[0].axhline(.8*weight,color='gray',ls=':',label='Expert opening-load criterion');ax[0].set_ylabel('Force (N)');ax[0].legend(fontsize=8,ncol=2)
ax[1].plot(x,[r['object_speed_m_s'] for r in rows],label='Actual object speed');ax[1].axhline(.08,color='r',ls='--',label='Expert recovery limit');ax[1].set_ylabel('Speed (m/s)');ax[1].legend(fontsize=8)
actual=np.array([r['actual_wrist_m'][2] for r in rows]);requested=np.array([r['requested_wrist_m'][2] for r in rows]);ax[2].plot(x,1000*(actual-actual[0]),label='Actual wrist Z change');ax[2].plot(x,1000*(requested-requested[0]),label='Requested wrist Z change');ax[2].set_ylabel('Z change (mm)');ax[2].set_xlabel('Physical release age (s)');ax[2].legend(fontsize=8)
for a in ax:a.grid(alpha=.25)
fig.suptitle('S02 bottle V004: recorded active handoff failed\nSingle development trial; no completed opening/release')
out=ROOT/'V004_RELEASE_DIAGNOSIS.png';assert not out.exists();fig.savefig(out,dpi=170);plt.close(fig)
safe_save(ROOT/'V004_RELEASE_PLOT.json',dict(new_physics_steps=0,image=_file_binding(out),source=_file_binding(p),implementation=_file_binding(Path(__file__)),scope='Recorded policy-time forces, speed and time-aligned wrist command/actual pose. Expert-added criteria are not new native task acceptance thresholds.'))
print(out)
