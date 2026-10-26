"""Attach the existing generated household without deleting its objects."""
from copy import deepcopy
from pathlib import Path
import xml.etree.ElementTree as ET
import hashlib,json


def attach_generated_room(robot_xml,scene_package,output,origin=(2.1,3.0)):
    package=Path(scene_package);source=package/'model.xml';root=ET.parse(robot_xml).getroot();scene=ET.parse(source).getroot()
    world=root.find('worldbody')
    for node in list(world):
        if node.get('name') in ('floor','task_table'):world.remove(node)
    default=ET.SubElement(root.find('default'),'default',{'class':'generated_scene'})
    for node in scene.find('default'):default.append(deepcopy(node))
    assets=root.find('asset');existing={(a.tag,a.get('name')) for a in assets if a.get('name')}
    for node in scene.find('asset'):
        item=deepcopy(node)
        if (item.tag,item.get('name')) in existing:raise ValueError('asset_name_collision')
        if item.get('file'):item.set('file',str((package/item.get('file')).resolve()))
        assets.append(item)
    # Keep massless architecture geoms in the world. A new fixed wrapper would
    # require a centre of mass for those deliberately massless world geoms.
    for node in scene.find('worldbody'):
        item=deepcopy(node)
        if item.tag not in ('body','geom','site','camera','light'):raise ValueError('unsupported_world_node')
        if any(item.get(k) for k in ('euler','axisangle','zaxis')):raise ValueError('explicit_source_rotation_required')
        pos=[float(v) for v in item.get('pos','0 0 0').split()]
        item.set('pos',f'{origin[0]-pos[0]} {origin[1]-pos[1]} {pos[2]}')
        if item.tag=='light':
            dx,dy,dz=[float(v) for v in item.get('dir','0 0 -1').split()];item.set('dir',f'{-dx} {-dy} {dz}');world.append(item);continue
        if item.get('xyaxes'):
            a,b,c,d,e,f=[float(v) for v in item.get('xyaxes').split()];item.set('xyaxes',f'{-a} {-b} {c} {-d} {-e} {f}');world.append(item);continue
        w,x,y,z=[float(v) for v in item.get('quat','1 0 0 0').split()]
        item.set('quat',f'{-z} {-y} {x} {w}')
        world.append(item)
        for geom in item.iter('geom'):
            if not geom.get('class'):geom.set('class','generated_scene')
    task=world.find("body[@name='task_object']");task.set('pos','-.02 -.64 .7902')
    ET.indent(root);Path(output).write_text(ET.tostring(root,encoding='unicode'))
    return dict(scene_package=str(package),source_model_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),source_task_sha256=hashlib.sha256((package/'task.json').read_bytes()).hexdigest(),all_source_bodies_retained=[b.get('name') for b in scene.find('worldbody').findall('body')],source_static_geoms_retained=len(list(scene.iter('geom'))),new_task_object='task_object',old_book_retained_as_free_distractor=True,transform='robot_local = Rz(pi) * (generated_world - [origin_x,origin_y,0])',origin=list(origin),task_scope='new 250g calibration box on generated desk, not reopening old book grasp')


import numpy as np
import mujoco
from .runtime import model_indices,base_pose

def inspect_generated_state(m,d,protocol,initial_z,stage):
    q=protocol['quality'];bad=[]
    if not all(np.isfinite(x).all() for x in (d.qpos,d.qvel,d.qacc,d.actuator_force)):bad.append('nonfinite')
    if np.any(d.warning.number):bad.append('mujoco_warning')
    pos,yaw,tilt=base_pose(m,d)
    if tilt>q['max_base_tilt_rad']:bad.append('base_tilt')
    if abs(pos[2]-initial_z)>q['max_base_height_change_m']:bad.append('base_height')
    if np.linalg.norm(d.qvel[:3])>q['max_base_linear_speed_m_s']:bad.append('base_speed')
    if np.max(abs(d.qvel))>q['max_qvel_abs']:bad.append('qvel')
    if np.any(abs(d.actuator_force)>m.actuator_forcerange[:,1]+1e-7):bad.append('effort_bound')
    if np.any(m.body_gravcomp) or np.any(d.qfrc_applied) or np.any(d.xfrc_applied):bad.append('external_force')
    object_id=model_indices(m)[4]
    object_dof=m.jnt_dofadr[m.body_jntadr[object_id]]
    if np.linalg.norm(d.qvel[object_dof:object_dof+3])>q['max_object_speed_m_s']:bad.append('object_speed')
    force=np.zeros(6);contacts=[];max_pen=0.;max_unintended=0.;tips=set();support=False
    for i,c in enumerate(d.contact):
        penetration=max(0.,-float(c.dist));max_pen=max(max_pen,penetration)
        mujoco.mj_contactForce(m,d,i,force);normal=float(force[0])
        if normal<=1e-7:continue
        bodies=[model_indices(m)[1][g] for g in c.geom]
        allowed=False
        if 'world' in bodies and any(m.geom(int(g)).name=='floor' for g in c.geom):
            other=next((b for b in bodies if b!='world'),'world')
            allowed=other in ('link_left_wheel','link_right_wheel')
            if other=='base_link':
                bg=next(g for g in c.geom if model_indices(m)[1][g]=='base_link')
                allowed=int(m.geom_type[bg])==int(mujoco.mjtGeom.mjGEOM_SPHERE)
        if set(bodies)=={'support','task_object'}:allowed=True;support=True
        if set(bodies)=={'support','target'}:allowed=True
        if 'task_object' in bodies:
            other=next((b for b in bodies if b!='task_object'),'task_object')
            if other in ('rubber_tip_left','rubber_tip_right'):
                allowed=stage in ('close','test_lift','hold','carry','place','release')
                if normal>.02:tips.add(other)
        if not allowed:max_unintended=max(max_unintended,normal)
        contacts.append(dict(bodies=bodies,geom=c.geom.tolist(),normal_N=normal,distance_m=float(c.dist),allowed=allowed))
    if max_pen>q['max_penetration_m']:bad.append('penetration')
    if max_unintended>q['max_unintended_contact_force_N']:bad.append('unintended_contact')
    return dict(failures=bad,base_pos=pos.tolist(),yaw=yaw,tilt=tilt,max_penetration=max_pen,max_unintended_N=max_unintended,contacts=contacts,bilateral=len(tips)==2,object_supported=support,object_pos=d.xpos[object_id].tolist())


from functools import lru_cache


@lru_cache(maxsize=4)
def _contact_roles(m):
    if m.opt.cone != mujoco.mjtCone.mjCONE_ELLIPTIC:
        raise ValueError('vector contact reader requires elliptic cones')
    return {name:m.body(name).id for name in ['base_link','link_left_wheel','link_right_wheel','task_object','support','target','rubber_tip_left','rubber_tip_right']},m.geom('floor').id


def inspect_generated_state_fast(m,d,protocol,initial_z,stage,details=False):
    """Same gates as inspect_generated_state, with vectorized contact roles.

    For elliptic cones, mj_contactForce's normal component is efc_force at
    contact.efc_address. This is checked against the native API before use.
    Detailed contacts are materialized only for failures or an audit request.
    """
    q=protocol['quality'];bad=[]
    if not all(np.isfinite(x).all() for x in (d.qpos,d.qvel,d.qacc,d.actuator_force)):bad.append('nonfinite')
    if np.any(d.warning.number):bad.append('mujoco_warning')
    pos,yaw,tilt=base_pose(m,d)
    if tilt>q['max_base_tilt_rad']:bad.append('base_tilt')
    if abs(pos[2]-initial_z)>q['max_base_height_change_m']:bad.append('base_height')
    if np.linalg.norm(d.qvel[:3])>q['max_base_linear_speed_m_s']:bad.append('base_speed')
    if np.max(abs(d.qvel))>q['max_qvel_abs']:bad.append('qvel')
    if np.any(abs(d.actuator_force)>m.actuator_forcerange[:,1]+1e-7):bad.append('effort_bound')
    if np.any(m.body_gravcomp) or np.any(d.qfrc_applied) or np.any(d.xfrc_applied):bad.append('external_force')
    ids,floor=_contact_roles(m);obj=ids['task_object'];dof=m.jnt_dofadr[m.body_jntadr[obj]]
    if np.linalg.norm(d.qvel[dof:dof+3])>q['max_object_speed_m_s']:bad.append('object_speed')
    geoms=d.contact.geom;bodies=m.geom_bodyid[geoms];address=d.contact.efc_address
    normal=np.zeros(d.ncon);active=address>=0;normal[active]=d.efc_force[address[active]];loaded=normal>1e-7
    def pair(a,b):return ((bodies[:,0]==a)&(bodies[:,1]==b))|((bodies[:,0]==b)&(bodies[:,1]==a))
    primary_support=pair(ids['support'],obj)
    allowed=primary_support|pair(ids['support'],ids['target'])
    ground=(geoms[:,0]==floor)|(geoms[:,1]==floor)
    other=np.where(geoms[:,0]==floor,geoms[:,1],geoms[:,0]);other_body=m.geom_bodyid[other]
    feet=(other_body==ids['link_left_wheel'])|(other_body==ids['link_right_wheel'])|((other_body==ids['base_link'])&(m.geom_type[other]==mujoco.mjtGeom.mjGEOM_SPHERE))
    allowed|=ground&feet
    left=pair(ids['rubber_tip_left'],obj);right=pair(ids['rubber_tip_right'],obj)
    if stage in ('close','test_lift','hold','carry','place','release'):allowed|=left|right
    max_pen=float(max(0.,np.max(-d.contact.dist))) if d.ncon else 0.
    wrong=loaded&~allowed;max_unintended=float(np.max(normal[wrong])) if np.any(wrong) else 0.
    if max_pen>q['max_penetration_m']:bad.append('penetration')
    if max_unintended>q['max_unintended_contact_force_N']:bad.append('unintended_contact')
    contacts=[]
    if details or bad:
        names=model_indices(m)[0]
        for i in np.flatnonzero(loaded):contacts.append(dict(bodies=[names[b] for b in bodies[i]],geom=geoms[i].tolist(),normal_N=float(normal[i]),distance_m=float(d.contact.dist[i]),allowed=bool(allowed[i])))
    return dict(failures=bad,base_pos=pos.tolist(),yaw=yaw,tilt=tilt,max_penetration=max_pen,max_unintended_N=max_unintended,contacts=contacts,bilateral=bool(np.any(left&(normal>.02)) and np.any(right&(normal>.02))),object_supported=bool(np.any(primary_support&loaded)),object_pos=d.xpos[obj].tolist(),active_contact_count=int(np.count_nonzero(loaded)),contact_details_saved=bool(details or bad))
