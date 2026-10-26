"""Select a fixed-input local impact window, separating solver error from feedback divergence."""
import numpy as np,h5py,mujoco
from .work import E,c,finish
folder=E/'jobs/walk_stop_03/episode';other=E/'jobs/walk_stop_halfstep_01/episode'
with h5py.File(folder/'TRACE.h5','r') as f,h5py.File(other/'TRACE.h5','r') as g:
 contacts=f['contacts/rows'][:];row=contacts[np.argmin(contacts[:,3])];peak=int(row[0]);start=max(0,peak-80);count=min(160,len(f['substep/qpos'])-start)
 q=f['substep/qpos'][:];q2=g['substep/qpos'][1::2];deltas=np.linalg.norm(q[:,:3]-q2[:,:3],axis=1)
 row2=g['contacts/rows'][:];worst2=row2[np.argmin(row2[:,3])]
 report={'physics_steps':0,'source':str(folder),'source_trace_sha256':c.sha(folder/'TRACE.h5'),'start_row':start,'saved_steps':count,'peak_row':peak,'peak_before_time':float(f['substep/time_before'][peak]),'nominal_peak_penetration_m':float(-row[3]),'halfstep_peak_before_time':float(g['substep/time_before'][int(worst2[0])]),'halfstep_peak_penetration_m':float(-worst2[3]),'online_same_time_base_max_error_m':float(deltas.max()),'online_endpoint_base_error_m':float(deltas[-1]),'purpose':'Same exact initial integration state and recorded400Hz actual torque/position commands. Numerical substeps hold commands across the original2.5ms command interval, removing online-policy phase divergence.'}
 for factor in [1,2,4]:
  c.write(E/'cases'/f'local_impact_factor{factor}.json',{'source_folder':str(folder),'start_row':start,'saved_steps':count,'subdivisions':factor,'finger_preload_rad':None,'allocation_group':'numerical_sensitivity_24000','fixed_actual_commands':True})
c.write(E/'LOCAL_IMPACT_NUMERICAL_DESIGN.json',report);finish(report)
