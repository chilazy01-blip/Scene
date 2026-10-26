"""Build actual task initialization on the own-generator model without advancing time."""
import os,sys
from pathlib import Path
import numpy as np,mujoco
from .work import E,R,c,finish
work=Path(os.environ['CONTINUOUS_JOB_DIR']);package=E/'generated/development_03/package';config=c.read(E/'cases/C_development_02.json')
os.environ.update(NP_ROOT=str(R),NP_JOB=str(work),CONTACT_MODEL_XML=str(package/'MODEL.xml'),CONTACT_NAMED_INITIAL='1',CONTACT_STOW_JOINT=config['stow_joint'],CONTACT_STOW_OFFSET=str(config['stow_offset_rad']))
sys.path.insert(0,str(R/'tools'));sys.path.insert(0,str(R/'branches/A/source'))
from .target_adapter_r3 import install
install('A','gain_translation',work/'static_interface')
from ik import pipeline as p
calls={'physics':0}
old=mujoco.mj_step
mujoco.mj_step=lambda *a,**k:(_ for _ in ()).throw(AssertionError('no_integration_allowed'))
kwargs=dict(config['kwargs']);spawn=kwargs.pop('spawn')
m,d,ctrl=p.ep.build_sim(spawn=spawn);geo=p.randomize_scene(m,d,**kwargs)
assert d.time==0 and m.nu==43 and not m.neq and not m.nmocap
mujoco.mj_forward(m,d)
qnames=[m.joint(i).name for i in range(m.njnt)];b=m.body('red_block').id;table=m.geom('table_top').id;top=float(d.geom_xpos[table,2]+m.geom_size[table,2]);bottom=float(d.xpos[b,2]-.037)
assert abs(bottom-top-.01)<1e-8, 'source10mm_initial_settling_gap'
cameras={m.camera(i).name:{'xyz':d.cam_xpos[i].tolist(),'rotation':d.cam_xmat[i].tolist(),'fovy':float(m.cam_fovy[i])} for i in range(m.ncam)}
report={'physics_steps':0,'policy_calls':0,'generated_package':str(package),'model_xml_sha256':c.sha(package/'MODEL.xml'),'initial_base_pose':d.qpos[:7].tolist(),'initial_cylinder_xyz':d.xpos[b].tolist(),'table_top_z':top,'object_bottom_z':bottom,'object_support_gap_m':bottom-top,'source_initial_settling_gap_m':.01,'source_geometry_initialization_matches':True,'task_geometry':{k:(v.tolist() if isinstance(v,np.ndarray) else v) for k,v in geo.items()},'cameras':cameras,'current_actuators':m.nu,'frozen_plant_invariants':'own_generator_static_02 previously verified all robot properties unchanged','task_dynamic_admission':False,'production_accepted':False}
c.write(E/'GENERATED_TASK_INITIALIZATION_PREFLIGHT.json',report);finish(report)
