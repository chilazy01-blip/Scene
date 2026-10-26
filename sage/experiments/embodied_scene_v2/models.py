"""Compose a v1 source model, then resolve every v2 input before compilation."""
from pathlib import Path
from xml.etree import ElementTree as ET
import json
import numpy as np
from scipy.spatial.transform import Rotation
from sage.experiments.embodied_scene_v1.models import make_task as source_task
from sage.experiments.embodied_scene_v1.package import vec, set_pose, bound
from .config import PACKAGE, validate, write_json, digest, ROOT

def quat(yaw):return vec([np.cos(yaw/2),0,0,np.sin(yaw/2)])

def make_task(config, output):
    c=validate(config);out=Path(output)
    source_task(PACKAGE,out,c['task'],c['scene_variant'],False,c['physics_only'])
    write_json(out/'request.json',config)
    root=ET.parse(out/'model.xml').getroot();world=root.find('worldbody')
    objects=json.loads((PACKAGE/'objects.json').read_text())
    for name,pose in c['object_poses'].items():
        if name not in objects:raise ValueError('Unknown scene object: '+name)
        set_pose(world.find(f"body[@name='{name}']"),pose);objects[name]['pose_z_up']=pose
    root.find('option').set('timestep',str(c['dt_s']))
    root.find('visual/global').set('offwidth','1440');root.find('visual/global').set('offheight','1080')
    if c['task']=='navigate':
        base=world.find("body[@name='base_link']");base.set('pos',vec(c['start']));base.set('quat',quat(c['start_yaw_rad']))
        if c['explicit_contact_pairs']:
            for side in ['left','right']:
                wheel=world.find(f".//body[@name='link_{side}_wheel']/geom[@class='collision']")
                if wheel is None:raise ValueError('Missing native wheel collider')
                wheel.set('name',f'sensitivity_{side}_wheel_collision')
    else:
        base=world.find("body[@name='base']");base.set('pos',vec(c['arm_base']));base.set('quat',quat(c['arm_yaw_rad']))
        mount=world.find("geom[@name='robot_mount']");mount.set('pos',vec([*c['arm_base'][:2],c['arm_base'][2]-.01]));mount.set('quat',quat(c['arm_yaw_rad']))
        book=world.find("body[@name='task_book']");book.set('pos',vec(c['start']));book.set('quat',quat(c['start_yaw_rad']))
        inertia=book.find('inertial');inertia.set('mass',str(float(inertia.get('mass'))*c['mass_multiplier']))
        inertia.set('diaginertia',vec(np.fromstring(inertia.get('diaginertia'),sep=' ')*c['mass_multiplier']))
    if c.get('collider_override'):
        # Only source-derived collision replacements are accepted here.
        for name,row in c['collider_override'].items():
            artifact=bound(row['path'])
            if artifact['sha256']!=row['sha256']:raise ValueError('Collider binding mismatch')
            data=np.load(row['path']);body=world.find(f"body[@name='{name}']")
            for geom in list(body.findall('geom')):
                if geom.get('name','').startswith('col_'):body.remove(geom)
            for i,(center,size) in enumerate(zip(data['centers'],data['half_sizes'])):
                ET.SubElement(body,'geom',name=f'col_{name}_{i}',type='box',pos=vec(center),size=vec(size),mass='0',group='3')
    ET.indent(root);ET.ElementTree(root).write(out/'model.xml',encoding='unicode')
    write_json(out/'objects.json',objects)
    c.update(reset_only_initialization=True,pose_writes_during_episode=False,target_welds=False,
        source_package=str(PACKAGE),request_digest=digest(config))
    write_json(out/'task.json',c)
    return c

def model_semantics(m):
    import mujoco
    geom_ids=[i for i in range(m.ngeom) if m.geom_contype[i] or m.geom_conaffinity[i]]
    names=lambda obj,n:[mujoco.mj_id2name(m,obj,i) for i in range(n)]
    physics={k:np.asarray(getattr(m,k)).tolist() for k in ('body_mass','body_inertia','body_ipos','body_iquat','body_pos','body_quat','body_parentid','jnt_type','jnt_qposadr','jnt_dofadr','jnt_pos','jnt_axis','jnt_range','dof_damping','dof_armature','actuator_gainprm','actuator_biasprm','actuator_ctrlrange','actuator_trnid','qpos0')}
    physics['geoms']=[dict(name=mujoco.mj_id2name(m,mujoco.mjtObj.mjOBJ_GEOM,i),**{k:np.asarray(getattr(m,k)[i]).tolist() for k in ('geom_bodyid','geom_type','geom_pos','geom_quat','geom_size','geom_friction','geom_solref','geom_solimp','geom_contype','geom_conaffinity','geom_condim','geom_priority')}) for i in geom_ids]
    physics.update(joint_names=names(mujoco.mjtObj.mjOBJ_JOINT,m.njnt),body_names=names(mujoco.mjtObj.mjOBJ_BODY,m.nbody),actuator_names=names(mujoco.mjtObj.mjOBJ_ACTUATOR,m.nu),counts=[m.nq,m.nv,m.nu],solver=dict(dt=m.opt.timestep,integrator=int(m.opt.integrator),solver=int(m.opt.solver),iterations=m.opt.iterations,tolerance=m.opt.tolerance))
    return physics
