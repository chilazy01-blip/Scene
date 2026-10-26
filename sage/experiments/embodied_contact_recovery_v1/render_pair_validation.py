"""Bounded new-frame renderer regression; compare same-passdepth to officialdepth."""
import os,time
from pathlib import Path
import numpy as np
import h5py,mujoco
from .work import E,finish,c
from .paired_renderer import rgbd
work=Path(os.environ['CONTINUOUS_JOB_DIR']);source=E/'jobs/C_development_01r/episode'
m=mujoco.MjModel.from_binary_path(str(source/'MODEL.mjb'));d=mujoco.MjData(m)
started=time.monotonic();renderer=mujoco.Renderer(m,256,256);init=time.monotonic()-started
usage={'render_passes':0};paired_seconds=[];reference_seconds=[];errors=[];translucent=[]
try:
 with h5py.File(source/'TRACE.h5','r') as f,h5py.File(work/'renderer_validation.h5','w') as h:
  for cam in ['overhead','wrist_cam']:
   for key,shape,dtype in [('rgb',(64,256,256,3),'u1'),('depth_m',(64,256,256),'f4'),('official_depth_m',(64,256,256),'f4')]:h.create_dataset(cam+'/'+key,shape=shape,dtype=dtype,chunks=True,compression='lzf')
  for i,k in enumerate(4000+np.arange(64)*16):
   mujoco.mj_setState(m,d,f['substep/integration_before'][k],mujoco.mjtState.mjSTATE_INTEGRATION);mujoco.mj_forward(m,d)
   for cam in ['overhead','wrist_cam']:
    renderer.disable_depth_rendering();renderer.update_scene(d,camera=cam)
    if i==0:translucent.append({'camera':cam,'active_translucent_geom_ids':[int(g.objid) for g in renderer.scene.geoms[:renderer.scene.ngeom] if 0<g.rgba[3]<1]})
    began=time.monotonic();usage['render_passes']+=1;rgb,depth=rgbd(renderer,m);paired_seconds.append(time.monotonic()-began)
    began=time.monotonic();renderer.enable_depth_rendering();usage['render_passes']+=1;reference=renderer.render().copy();reference_seconds.append(time.monotonic()-began)
    error=float(np.max(abs(depth.astype(float)-reference.astype(float))));errors.append(error)
    for key,value in [('rgb',rgb),('depth_m',depth),('official_depth_m',reference)]:h[cam+'/'+key][i]=value
   c.write(work/'USAGE.json',usage)
finally:renderer.close()
report={'passed':max(errors)<1e-6,'frames':64,'actual_render_passes':usage['render_passes'],'new_physics_steps':0,'training_updates':0,
        'max_official_depth_difference_m':max(errors),'paired_seconds_total':sum(paired_seconds),'official_depth_seconds_total':sum(reference_seconds),'context_init_seconds':init,
        'paired_median_seconds_per_camera':float(np.median(paired_seconds[4:])),'previous_two_pass_median_seconds_per_camera':float(np.median(np.array(paired_seconds[4:])+np.array(reference_seconds[4:]))),
        'projection':'Original renderer RGB pass; read existing OpenGL depth buffer, same pinned reversed-Z conversion and image flip','translucent_geometries':translucent,
        'scope':'New saved-state render diagnostics; original32-frame export not rerendered or modified','production_accepted':False}
c.write(E/'PAIRED_RENDERER_VALIDATION.json',report);finish(report,usage)
