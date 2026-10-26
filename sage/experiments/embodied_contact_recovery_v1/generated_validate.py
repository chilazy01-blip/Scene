"""Compile generated environment, prove unchanged robot and inspect RGB-D without stepping."""
import os
from pathlib import Path
import h5py
import numpy as np
import mujoco
from PIL import Image
from .work import R,E,finish,c
out=E/'generated/development_02/package'
m=mujoco.MjModel.from_xml_path(str(out/'MODEL.xml'));d=mujoco.MjData(m)
old=mujoco.MjModel.from_xml_path(str(R/'shared/target/MODEL.xml'))
fields={}
for field in ['body_mass','body_inertia','body_ipos','body_iquat']:
 errors=[]
 for i in range(1,old.nbody):
  name=old.body(i).name
  if name in ['table','table_white','red_block']:continue
  j=m.body(name).id;errors.append(np.max(np.abs(getattr(old,field)[i]-getattr(m,field)[j])))
 fields[field]=float(max(errors,default=0))
for field in ['actuator_trntype','actuator_dyntype','actuator_gaintype','actuator_biastype','actuator_dynprm','actuator_gainprm','actuator_biasprm','actuator_ctrlrange','actuator_forcerange','jnt_range','dof_damping','dof_armature']:
 assert np.shape(getattr(old,field))==np.shape(getattr(m,field)),field
 fields[field]=float(np.max(abs(getattr(old,field)-getattr(m,field)),initial=0))
assert all(v==0 for v in fields.values()),fields
assert m.nu==43 and not m.neq and not m.nmocap
# Saved standing pose used only for an explicit static visual/geometry inspection.
with h5py.File(E/'jobs/C_development_01r/episode/TRACE.h5','r') as f:
 d.qpos[:]=f['substep/qpos'][1599];d.qvel[:]=f['substep/qvel'][1599]
# Move the inspected target with its generated pick table, before any integration.
adr=m.jnt_qposadr[m.joint('red_block_joint').id];d.qpos[adr+2]-=.003
mujoco.mj_forward(m,d)
contacts=[{'geoms':[m.geom(ct.geom1).name,m.geom(ct.geom2).name],'distance_m':float(ct.dist)} for ct in d.contact]
mujoco.mj_saveModel(m,str(out/'MODEL.mjb'))
usage={'render_passes':0};renderer=mujoco.Renderer(m,256,256)
try:
 for cam in ['overhead','wrist_cam','side_view']:
  renderer.disable_depth_rendering();renderer.update_scene(d,camera=cam);usage['render_passes']+=1
  Image.fromarray(renderer.render()).save(out/(cam+'.png'))
  renderer.enable_depth_rendering();usage['render_passes']+=1;depth=renderer.render().astype('f4');assert np.isfinite(depth).all() and (depth>0).all()
  np.save(out/(cam+'_depth_m.npy'),depth)
  c.write(Path(os.environ['CONTINUOUS_JOB_DIR'])/'USAGE.json',usage)
finally:renderer.close()
report={'passed':True,'new_physics_steps':0,'new_render_passes':usage['render_passes'],'robot_parameter_max_differences':fields,
        'native_ngeom':old.ngeom,'generated_ngeom':m.ngeom,'actuators':m.nu,'static_contacts':contacts,
        'scene_model_sha256':c.sha(out/'MODEL.mjb'),'initial_inspection_only':True,'dynamic_admission':False,
        'source_binding_sha256':c.sha(out/'BINDING.json'),'production_accepted':False}
c.write(out/'COMPILE_AND_STATIC_CHECK.json',report);finish(report,usage)
