"""Charged rendered closeups of saved grasp failure states; no new physics."""
import os
from pathlib import Path
import numpy as np
import h5py
import mujoco
from PIL import Image
from .work import E,c,finish

work=Path(os.environ['CONTINUOUS_JOB_DIR']);folder=E/'jobs/C_development_03/episode'
m=mujoco.MjModel.from_binary_path(str(folder/'MODEL.mjb'));d=mujoco.MjData(m)
renderer=mujoco.Renderer(m,512,512);obj=m.body('red_block').id;views=[];usage={'render_passes':0}
with h5py.File(folder/'TRACE.h5','r') as f:
 times=f['substep/time_before'][:]
 for seconds in [43.,63.2475,78.2475]:
  k=int(np.argmin(abs(times-seconds)));mujoco.mj_setState(m,d,f['substep/integration_before'][k],mujoco.mjtState.mjSTATE_INTEGRATION);mujoco.mj_forward(m,d)
  for azimuth in [60,240]:
   camera=mujoco.MjvCamera();camera.lookat[:]=d.xpos[obj];camera.distance=.30;camera.azimuth=azimuth;camera.elevation=-15
   renderer.update_scene(d,camera=camera);rgb=renderer.render().copy();usage['render_passes']+=1
   path=work/f'grasp_{seconds:g}_az{azimuth}.png';Image.fromarray(rgb).save(path)
   views.append({'source_row':k,'time':float(times[k]),'image':str(path),'azimuth':azimuth,'elevation':-15,'distance':.3})
   c.write(work/'USAGE.json',usage)
renderer.close();report={'physics_steps':0,'policy_calls':0,'scope':'Saved-state failure closeups for visual geometry inspection, not dataset cameras.','views':views,'production_accepted':False}
c.write(E/'C3_GRASP_VISUAL_EVIDENCE.json',report);finish(report,usage)
