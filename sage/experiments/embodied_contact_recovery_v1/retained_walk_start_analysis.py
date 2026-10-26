"""Saved command and contact evidence for abrupt held-object retreat startup."""
import h5py
import numpy as np
from .work import E,c,finish
rows=[]
for name in ['D_retained_grasp_walk_01','D_retained_grasp_walk_guard_02']:
 folder=E/'jobs'/name/'episode';model=c.read(folder/'MODEL.json')
 with h5py.File(folder/'TRACE.h5','r') as f:
  policy=f['policy/walker_onnx'];obs=policy['input'][next(iter(policy['input']))][:].reshape(len(policy['physics_row']),-1)
  bad=f['contacts/rows'][:];bad=bad[bad[:,3]<-.01]
  first=bad[0];row={'job':name,'source_sha256':c.sha(folder/'TRACE.h5'),'policy_rows':policy['physics_row'][:].tolist(),'velocity_commands':obs[:,-3:].tolist(),'first_over_limit':{'row':int(first[0]),'geoms':[model['geom_names'][int(first[i])] for i in [1,2]],'depth_m':float(-first[3])}}
  if 'sole_guard' in f:
   status=f['sole_guard/status'][:];row['guard']={'optimized_steps':int(status[:,0].sum()),'accepted_steps':int(status[:,1].sum()),'first_infeasible_row':int(np.flatnonzero((status[:,0]==1)&(status[:,1]==0))[0]),'maximum_motor_delta_Nm':float(np.max(abs(f['sole_guard/motor_delta_Nm'][:]))) }
  rows.append(row)
report={'physics_steps':0,'windows':rows,'candidate_reason':'Source measured walk-to switches from zero to clipped retreat velocity in one policy period. Retain upright grasp and use causal acceleration-limited command transition before unchanged body policy; no plant change. Motor barrier candidate did not qualify.','candidate':{'maximum_velocity':[.2,.15,.3],'maximum_acceleration':[.25,.25,.5],'policy_period_seconds':.02,'maximum_diagnostic_steps':1200},'production_accepted':False}
c.write(E/'D_RETAINED_WALK_START_ANALYSIS.json',report);finish(report)
