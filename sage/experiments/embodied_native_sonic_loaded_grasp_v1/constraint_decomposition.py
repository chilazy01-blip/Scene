"""Separate actual joint friction/limits/contact reactions in failed allocation."""
import argparse,os,resource
from pathlib import Path
import numpy as np
from sage.experiments.embodied_native_walk_motion_v2.engine import hand_ids
from sage.experiments.embodied_native_object_transport_v1.metrics import contact_pair
from sage.experiments.embodied_carry_v1.grasp import RIGHT_CLOSED,group
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding

def run(root):
    import mujoco
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    ep=root/'version_02/full';r=read_bound_json(ep/'REPORT.json');t=read_bound_json(ep/'TRACE.json');m=load_model(r['model']['path']);m.opt.timestep=.005;d=mujoco.MjData(m);h=hand_ids(m);ix=np.array([i for i,n in enumerate(h['names']) if n in RIGHT_CLOSED]);hd=h['dofs'][ix];rows=[]
    for tick in [1200,1220,1260,1280,1300]:
        s=t['records'][tick]['substeps'][0];d.qpos[:]=s['full_qpos_before'];d.qvel[:]=s['full_qvel_before'];d.qacc_warmstart[:]=s['qacc_warmstart_before'];d.ctrl[:]=s['all_ctrl'];d.time=s['time_before_s'];mujoco.mj_forward(m,d)
        parts={};total=np.zeros(m.nv)
        for name,v in mujoco.mjtConstraint.__members__.items():
            selected=np.where(np.asarray(d.efc_type)==int(v),d.efc_force,0.);q=np.zeros(m.nv);mujoco.mj_mulJacTVec(m,d,q,selected);parts[name]=q[hd].tolist();total+=q
        error=float(np.max(np.abs(total-d.qfrc_constraint)));assert error<1e-8
        cup=np.zeros(m.nv);extra=[]
        for i,c in enumerate(d.contact):
            pair=contact_pair(m,c);names=[a['name'] for a in pair];f=np.zeros(6);mujoco.mj_contactForce(m,d,i,f)
            if 'payload_surface' in names:
                side=names.index('payload_surface')
                if group(pair[1-side]['body']) not in ['thumb','index','middle']:continue
                sign=1 if side==1 else -1.;force=-sign*np.asarray(c.frame).reshape(3,3).T@f[:3];mujoco.mj_applyFT(m,d,force,np.zeros(3),c.pos,int(m.geom_bodyid[c.geom[1-side]]),cup)
            elif any('right_hand_' in a['body'] for a in pair) and f[0]>.01:extra.append(dict(pair=pair,normal_n=float(f[0])))
        contact=np.array(parts['mjCNSTR_CONTACT_PYRAMIDAL']);loss=np.array(parts['mjCNSTR_FRICTION_DOF']);rows.append(dict(tick=tick,time_s=s['time_before_s'],constraint_parts_nm=parts,cup_contact_joint_torque_nm=cup[hd].tolist(),other_contact_joint_torque_nm=(contact-cup[hd]).tolist(),extra_hand_contacts=extra,actual_motor_torque_nm=d.qfrc_actuator[hd].tolist(),actual_joint_velocity_rad_s=d.qvel[hd].tolist(),maximum_constraint_decomposition_error_nm=error));print(dict(tick=tick,loss_nm=loss.tolist(),cup_contact_nm=cup[hd].tolist(),other_contact_max=float(np.max(np.abs(contact-cup[hd]))),error=error),flush=True)
    safe_save(root/'ACTUAL_CONSTRAINT_DECOMPOSITION.json',dict(schema='actual-finger-contact-friction-limit-decomposition/v1',new_physics_steps=0,right_finger_names=[h['names'][i] for i in ix],native_dof_frictionloss_nm=m.dof_frictionloss[hd].tolist(),native_dof_damping=m.dof_damping[hd].tolist(),native_dof_armature=m.dof_armature[hd].tolist(),rows=rows,source_trace=r['trace'],interpretation='Actual saved pre-state and actual43ctrl only; efc_J.T*efc_force separated by native constraint type and independently cup contact force mapped with mj_applyFT. Finger joint dry friction is distinct from cup-surface sliding friction. A static motor-to-cup-contact map must include non-contact joint constraint reactions as well as bias/passive/inertia; these forces were omitted from v2 contact-only allocation.',implementation=_file_binding(Path(__file__))))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);run(p.parse_args().root)
