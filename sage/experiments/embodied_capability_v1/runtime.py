"""Bounded effective Stretch model and internal force-limited servo.

All deviations from native source are serializable. Assumed capacities stay
separate from the strict hardware registry in embodied_actuator_v1.
"""
from pathlib import Path
import xml.etree.ElementTree as ET
from functools import lru_cache
import numpy as np
import mujoco
from sage.experiments.embodied_actuator_v1 import CHANNELS, StretchTransmission, AffineServo


def make_model(source, output, level, protocol, mass=.25, shape='box', size=(.02,.04,.04)):
    source=Path(source)
    root=ET.parse(source/'stretch.xml').getroot()
    root.find('compiler').set('assetdir',str(source/'assets'))
    root.find('option').set('timestep',str(protocol['phase_budget']['dt']))
    world=root.find('worldbody')
    ET.SubElement(world,'geom',name='floor',type='plane',size='0 0 .05',rgba='.3 .3 .3 1')
    table=ET.SubElement(world,'body',name='task_table',pos='0 -1 .24')
    ET.SubElement(table,'geom',name='task_table_geom',type='box',size='.6 .5 .24',rgba='.5 .3 .1 1')
    obj=ET.SubElement(world,'body',name='task_object',pos='-.02 -.64 '+str(.48+size[2]+.0002))
    ET.SubElement(obj,'freejoint',name='task_object_free')
    ET.SubElement(obj,'geom',name='task_object_geom',type=shape,size=' '.join(map(str,size)),mass=str(mass),rgba='.1 .3 .8 1',friction='.5 .005 .0001')
    ET.indent(root)
    Path(output).write_text(ET.tostring(root,encoding='unicode'))
    m=mujoco.MjModel.from_xml_path(str(output))
    m.body_gravcomp[:]=0
    for name in ['joint_left_wheel','joint_right_wheel']:
        m.dof_frictionloss[m.joint(name).dofadr[0]]=level['wheel_friction_Nm']
    c=protocol['parameters']['other_effort_caps']
    caps=np.array([level['wheel_actuator_Nm']]*2+[c['lift_N'],c['arm_N'],c['wrist_yaw_Nm'],c['wrist_pitch_Nm'],c['wrist_roll_Nm'],level['gripper_slider_N'],c['head_pan_Nm'],c['head_tilt_Nm']])
    assert np.isfinite(caps).all() and np.all(caps>0)
    m.actuator_forcelimited[:]=1;m.actuator_forcerange[:]=np.column_stack((-caps,caps))
    return m, dict(scope='simulation_only',level=level,effort_caps=caps.tolist(),native_wheel_friction_Nm=35,source_gains_retained=True,source_ctrl_ranges_retained=True,external_support=False,mass_kg=mass,shape=shape,size_m=list(size),native_model_xml=str(source/'stretch.xml'),derived_scene_xml=str(output))


def initialize(m,base_x=0,gripper=.03):
    d=mujoco.MjData(m);tr=StretchTransmission(m)
    ref=m.keyframe('home').ctrl.copy();ref[7]=gripper
    for i,name in enumerate(CHANNELS):
        if name.endswith('_vel'):continue
        for j,factor in tr.joints[name]: d.qpos[m.joint(j).qposadr[0]]=ref[i]*factor
    base=m.body('base_link').jntadr[0];d.qpos[m.jnt_qposadr[base]]=base_x
    d.ctrl[:]=ref;mujoco.mj_forward(m,d)
    return d,ref


class ConditionalServo:
    def __init__(self,m):
        self.m=m;self.tr=StretchTransmission(m);self.affine=AffineServo(m)
        self.g=mujoco.MjData(m);self.limited=m.actuator_ctrllimited.astype(bool)
        self.caps=m.actuator_forcerange.copy();self.last={}
    def apply(self,d,reference):
        ref=np.asarray(reference,dtype=float)
        if ref.shape!=(10,) or not np.isfinite(ref).all():raise ValueError('invalid_named_reference')
        if np.any(ref[self.limited]<self.m.actuator_ctrlrange[self.limited,0]) or np.any(ref[self.limited]>self.m.actuator_ctrlrange[self.limited,1]):raise ValueError('reference_out_of_source_range')
        if np.any(self.m.body_gravcomp) or np.any(d.qfrc_applied) or np.any(d.xfrc_applied):raise ValueError('external_support')
        self.g.qpos[:]=d.qpos;self.g.qvel[:]=0;self.g.ctrl[:]=0;mujoco.mj_forward(self.m,self.g)
        gravity=self.tr.gravity(self.g);ctrl,force=self.affine.diagnostic(d,ref,gravity)
        actual=ctrl.copy();actual[self.limited]=np.clip(actual[self.limited],self.m.actuator_ctrlrange[self.limited,0],self.m.actuator_ctrlrange[self.limited,1])
        d.ctrl[:]=actual
        self.last=dict(reference=ref.copy(),ctrl=actual.copy(),gravity=gravity.copy(),ctrl_clipped=actual!=ctrl,requested_force=force.copy())
        return self.last


@lru_cache(maxsize=8)
def model_indices(m):
    names=tuple(m.body(i).name for i in range(m.nbody))
    geom_names=tuple(names[int(m.geom_bodyid[g])] for g in range(m.ngeom))
    tips=tuple(next(g for g in range(m.ngeom) if geom_names[g]==name and m.geom_contype[g]) for name in ('rubber_tip_left','rubber_tip_right'))
    return names,geom_names,tips,m.body('base_link').id,m.body('task_object').id


def tip_center(m,d):
    left,right=model_indices(m)[2]
    return (d.geom_xpos[left]+d.geom_xpos[right])*.5


def base_pose(m,d):
    b=model_indices(m)[3];rot=d.xmat[b].reshape(3,3)
    return d.xpos[b].copy(),float(np.arctan2(rot[1,0],rot[0,0])),float(np.arccos(np.clip(rot[2,2],-1,1)))


def drive_reference(m,d,target_x,target_yaw=0):
    pos,yaw,_=base_pose(m,d)
    v=np.clip(1.0*(target_x-pos[0]),-.07,.07)
    w=np.clip(2*((target_yaw-yaw+np.pi)%(2*np.pi)-np.pi),-.2,.2)
    return np.clip(3*np.array([v-.15785*w,v+.15785*w])/.05,-6,6)


def inspect_state(m,d,protocol,initial_z,stage):
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
        if 'world' in bodies:
            other=next((b for b in bodies if b!='world'),'world')
            allowed=other in ('link_left_wheel','link_right_wheel')
            if other=='base_link':
                bg=next(g for g in c.geom if model_indices(m)[1][g]=='base_link')
                allowed=int(m.geom_type[bg])==int(mujoco.mjtGeom.mjGEOM_SPHERE)
        if set(bodies)=={'task_table','task_object'}:allowed=True;support=True
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


def smooth(s):
    s=float(np.clip(s,0,1));return s*s*s*(10+s*(-15+6*s))
