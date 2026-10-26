"""Analyze completed diagnostics without new policy or physics execution."""
import numpy as np
import h5py
import mujoco
from .work import E,finish,c
s=c.read(E/'STATE.json');rows=[]
for key,record in s['jobs'].items():
 p=E/'jobs'/key/'episode'
 if not (p/'TRACE.h5').exists() or not (p/'MODEL.mjb').exists() or not key.startswith(('foot_','walking_','grip_')):continue
 m=mujoco.MjModel.from_binary_path(str(p/'MODEL.mjb'))
 with h5py.File(p/'TRACE.h5','r') as f:
  q=f['substep/qpos'];contacts=f['contacts/rows'][:];pen=-contacts[:,3]
  bad=contacts[pen>.01];worst=contacts[int(np.argmax(pen))]
  desc=lambda ct:{'step':int(ct[0]),'time':float(f['substep/time_before'][int(ct[0])]),'geom_pair':[m.geom(int(g)).name for g in ct[1:3]],'penetration_m':float(-ct[3]),'force_N':float(np.linalg.norm(ct[7:10]))}
  item={'job':key,'saved_steps':len(q),'charged_steps':record.get('usage',{}).get('diagnostic_physics_steps'),
        'maximum':desc(worst),'first_over_10mm':desc(bad[0]) if len(bad) else None,
        'base_displacement_m':(q[-1,:3]-q[0,:3]).tolist(),'source_model_sha256':c.sha(p/'MODEL.mjb'),'trace_sha256':c.sha(p/'TRACE.h5')}
  if 'landing/row' in f:
   a=f['landing/row'][:];item['landing_corrections']={'count':len(a),'first_rows':a[:4].tolist(),'last_rows':a[-4:].tolist()}
  rows.append(item)
report={'physics_steps':0,'diagnostic_budget_exhausted':True,'new_complete_tasks':1,'qualified_locomotion_correction':False,'results':rows,'interpretation':'Small penetration with near-zero forward displacement does not qualify walking. Direct damping and acceleration correction failed online contact quality. No new complete task admitted on these variants.'}
c.write(E/'DIAGNOSTIC_REVIEW.json',report);finish(report)
