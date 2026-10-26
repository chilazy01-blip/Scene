"""Measure CPU shadow-map cost while retaining RGB-D dimensions and sampling."""
import os,time
from pathlib import Path
import numpy as np
import h5py,mujoco
from PIL import Image
from .work import E,finish,c
work=Path(os.environ['CONTINUOUS_JOB_DIR']);source=E/'jobs/C_development_01r/episode'
m=mujoco.MjModel.from_binary_path(str(source/'MODEL.mjb'));d=mujoco.MjData(m)
original_shadow=int(m.vis.quality.shadowsize);m.vis.quality.shadowsize=2048
renderer=mujoco.Renderer(m,256,256);usage={'render_passes':0};rows=[]
try:
 with h5py.File(source/'TRACE.h5','r') as f,h5py.File(E/'jobs/paired_RGBD_renderer_01/renderer_validation.h5','r') as baseline,h5py.File(work/'candidate.h5','w') as out:
  for i in range(0,64,8):
   k=4000+i*16;mujoco.mj_setState(m,d,f['substep/integration_before'][k],mujoco.mjtState.mjSTATE_INTEGRATION);mujoco.mj_forward(m,d)
   for cam in ['overhead','wrist_cam']:
    renderer.disable_depth_rendering();renderer.update_scene(d,camera=cam);start=time.monotonic();usage['render_passes']+=1;rgb=renderer.render().copy();seconds=time.monotonic()-start
    renderer.enable_depth_rendering();usage['render_passes']+=1;depth=renderer.render().copy()
    delta=abs(rgb.astype(float)-baseline[cam+'/rgb'][i].astype(float));depth_error=float(np.max(abs(depth-baseline[cam+'/official_depth_m'][i])))
    rows.append({'frame':i,'camera':cam,'RGB_seconds':seconds,'RGB_mean_absolute_byte_difference':float(delta.mean()),'RGB_p99_byte_difference':float(np.percentile(delta,99)),
                 'pixel_fraction_any_channel_over8':float(np.mean(np.max(delta,axis=2)>8)),'depth_max_difference_m':depth_error})
    out.create_dataset(f'{cam}/{i}/rgb',data=rgb,compression='lzf');out.create_dataset(f'{cam}/{i}/depth',data=depth,compression='lzf')
    if i==0:Image.fromarray(rgb).save(work/(cam+'_shadow2048.png'));Image.fromarray(baseline[cam+'/rgb'][i]).save(work/(cam+'_shadow_original.png'))
   c.write(work/'USAGE.json',usage)
finally:renderer.close()
report={'new_physics_steps':0,'render_passes':usage['render_passes'],'original_shadow_size':original_shadow,'candidate_shadow_size':2048,'image_size':[256,256],'RGBD_Hz':25,
        'geometry_materials_cameras_samples_unchanged':True,'candidate_shadow_resolution_eight_times_image_width':True,'quality_not_assumed':True,'rows':rows,
        'median_RGB_seconds':float(np.median([r['RGB_seconds'] for r in rows[2:]])),'depth_identical':all(r['depth_max_difference_m']==0 for r in rows),'production_accepted':False}
c.write(E/'SHADOW_RENDER_PROFILE_DIAGNOSTIC.json',report);finish(report,usage)
