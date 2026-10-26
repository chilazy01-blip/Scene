"""Check whether4Mesa threads improve throughput while preserving exact pixels."""
import os,time
from pathlib import Path
import numpy as np,h5py,mujoco
from .work import E,c,finish
work=Path(os.environ['CONTINUOUS_JOB_DIR']);source=E/'jobs/grasp_friction_01/episode';canonical=E/'jobs/grasp_rgbd_export_01/data/canonical.h5'
assert os.environ['LP_NUM_THREADS']=='4' and len(os.sched_getaffinity(0))<=4
m=mujoco.MjModel.from_binary_path(str(source/'MODEL.mjb'));d=mujoco.MjData(m);renderer=mujoco.Renderer(m,256,256);usage={'render_passes':0};rows=[]
try:
 with h5py.File(source/'TRACE.h5','r') as f,h5py.File(canonical,'r') as base:
  for frame in np.linspace(0,249,12,dtype=int):
   k=int(base['source_substep_indices'][frame]);mujoco.mj_setState(m,d,f['substep/integration_before'][k],mujoco.mjtState.mjSTATE_INTEGRATION);mujoco.mj_forward(m,d)
   for cam in ['overhead','wrist_cam']:
    renderer.disable_depth_rendering();renderer.update_scene(d,camera=cam);start=time.monotonic();usage['render_passes']+=1;rgb=renderer.render().copy();rgb_time=time.monotonic()-start
    renderer.enable_depth_rendering();start=time.monotonic();usage['render_passes']+=1;depth=renderer.render().copy();depth_time=time.monotonic()-start
    rows.append({'frame':int(frame),'camera':cam,'rgb_seconds':rgb_time,'depth_seconds':depth_time,'rgb_max_byte_error':int(np.max(abs(rgb.astype(int)-base['cameras/'+cam+'/rgb'][frame].astype(int)))),'depth_max_error_m':float(np.max(abs(depth-base['cameras/'+cam+'/depth_m'][frame])))})
    c.write(work/'USAGE.json',usage)
finally:renderer.close()
report={'physics_steps':0,'render_passes':usage['render_passes'],'candidate_Mesa_threads':4,'CPU_affinity':sorted(os.sched_getaffinity(0)),'specification_unchanged':{'resolution':[256,256],'camera_count':2,'RGBD_hz':25,'shadow_map':int(m.vis.quality.shadowsize),'samples':int(m.vis.quality.offsamples),'two_render_passes_per_camera':True},'rows':rows,'pixels_identical':all(r['rgb_max_byte_error']==0 and r['depth_max_error_m']==0 for r in rows),'mean_seconds_per_pass':float(np.mean([(r['rgb_seconds']+r['depth_seconds'])/2 for r in rows[2:]])),'production_accepted':False}
c.write(E/'RENDER_THREAD_VALIDATION.json',report);finish(report,usage)
