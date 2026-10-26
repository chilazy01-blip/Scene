"""Select a fixed-input local impact window, separating solver error from feedback divergence."""
import numpy as np,h5py,mujoco
from .work import E,c,finish
folder=E/'jobs/pipeline_initial_window_01/episode'
with h5py.File(folder/'TRACE.h5','r') as f:
 contacts=f['contacts/rows'][:];row=contacts[np.argmin(contacts[:,3])];peak=int(row[0]);start=max(0,peak-80);count=min(160,len(f['substep/qpos'])-start)
 report={'physics_steps':0,'source':str(folder),'source_trace_sha256':c.sha(folder/'TRACE.h5'),'start_row':start,'saved_steps':count,'peak_row':peak,'peak_before_time':float(f['substep/time_before'][peak]),'nominal_peak_penetration_m':float(-row[3]),'purpose':'Same exact initial integration state and recorded400Hz actual torque/position commands. Numerical substeps hold commands across the original2.5ms command interval, removing online-policy phase divergence.'}
 for factor in [2,4]:
  c.write(E/'cases'/f'pipeline_impact_factor{factor}.json',{'source_folder':str(folder),'start_row':start,'saved_steps':count,'subdivisions':factor,'finger_preload_rad':None,'allocation_group':'numerical_sensitivity_24000','fixed_actual_commands':True})
c.write(E/'PIPELINE_IMPACT_NUMERICAL_DESIGN.json',report);finish(report)
