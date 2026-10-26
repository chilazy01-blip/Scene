"""Actual friction wrench/slip reconstruction with static load feasibility bounds."""
import argparse,time,os,resource
from pathlib import Path
import numpy as np
from scipy.optimize import linprog
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_native_object_transport_v1.metrics import contact_pair
from sage.experiments.embodied_carry_v1.grasp import group
from sage.experiments.embodied_native_sonic_transport_v1.restore import load_after
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding


def velocity_at(mj,model,data,body,point):
    jac=np.zeros((3,model.nv));mj.mj_jac(model,data,jac,None,np.asarray(point),body)
    return jac@data.qvel


def capacity(contacts,weight,com,group_caps=False):
    if not contacts:return dict(eligible=False,reason='no loaded hand contact')
    # Pyramidal condim3 rays. Bound normal load by the observed preload.
    columns=[];groups=[]
    for c in contacts:
        if c['dim']!=3:return dict(eligible=False,reason='requires actual dim3 contacts')
        D=np.array(c['frame']).reshape(3,3);mu1,mu2=c['friction'][:2];sign=c['object_sign'];r=np.array(c['position_m'])-com
        for local in [[1,mu1,0],[1,-mu1,0],[1,0,mu2],[1,0,-mu2]]:
            force=sign*(D.T@local);columns.append(np.r_[force,np.cross(r,force)]);groups.append(c['role'])
    W=np.array(columns).T;load=np.array([0.,0.,weight,0.,0.,0.]);n=W.shape[1]
    equality=np.c_[W,-load];ub=[];rhs=[]
    if group_caps:
        for g in sorted(set(groups)):
            ub.append([float(x==g) for x in groups]+[0.]);rhs.append(sum(c['normal_n'] for c in contacts if c['role']==g))
    else:
        for i,c in enumerate(contacts):
            row=np.zeros(n+1);row[4*i:4*i+4]=1;ub.append(row);rhs.append(c['normal_n'])
    objective=np.zeros(n+1);objective[-1]=-1
    result=linprog(objective,A_ub=np.asarray(ub),b_ub=np.asarray(rhs),A_eq=equality,b_eq=np.zeros(6),bounds=[(0,None)]*(n+1),method='highs')
    return dict(eligible=True,optimizer_success=bool(result.success),maximum_weight_multiple=float(result.x[-1]) if result.success else None,
        full_body_weight_statically_supportable=bool(result.success and result.x[-1]>=1-1e-6),normal_bounds='per finger group redistribution' if group_caps else 'per observed contact',
        limitation='optimistic instantaneous static capacity using observed normal preload and contact geometry; not a dynamic counterfactual or proof of unique root cause')


def frame(mj,model,data,s,payload,case,load_lp=False):
    load_after(mj,model,data,s);com=data.xipos[payload].copy();objR=data.xmat[payload].reshape(3,3);total=np.zeros(3);hand=np.zeros(3);desk=np.zeros(3);hn=np.zeros(3);ht=np.zeros(3);torque=np.zeros(3);contacts=[]
    group_sums={g:dict(normal_n=0.,tangent_n=0.,world_force_n=np.zeros(3),world_friction_n=np.zeros(3)) for g in ['thumb','index','middle','palm','desk','other']}
    reconstruction=0.
    for i,co in enumerate(data.contact):
        pair=contact_pair(model,co);names=[p['name'] for p in pair]
        if 'payload_surface' not in names:continue
        side=names.index('payload_surface');other=pair[1-side];role='desk' if other['body']=='generated_desk' else group(other['body']);sign=1. if side==1 else -1.
        f=np.zeros(6);mj.mj_contactForce(model,data,i,f);D=np.asarray(co.frame).reshape(3,3);normal=sign*D[0]*f[0];tangent=sign*(D[1]*f[1]+D[2]*f[2]);world=normal+tangent
        otherbody=int(model.geom_bodyid[co.geom[1-side]]) if co.geom[1-side]>=0 else int(model.flex_vertbodyid[model.flex_vertadr[co.flex[1-side]]])
        relative=velocity_at(mj,model,data,payload,co.pos)-velocity_at(mj,model,data,otherbody,co.pos);contact_vel=D@relative
        mu=np.asarray(co.friction);fn=max(0.,float(f[0]));rho=(abs(f[1])/mu[0]+abs(f[2])/mu[1])/fn if fn>1e-8 else None
        record=dict(role=role,dim=int(co.dim),friction=mu.tolist(),normal_n=fn,local_force_n=f[:3].tolist(),tangent_n=float(np.linalg.norm(f[1:3])),pyramid_utilization=rho,
            position_m=np.asarray(co.pos).tolist(),position_relative_com_m=(np.asarray(co.pos)-com).tolist(),frame=D.reshape(-1).tolist(),object_sign=sign,
            world_force_on_cup_n=world.tolist(),world_friction_on_cup_n=tangent.tolist(),relative_world_velocity_m_s=relative.tolist(),tangential_speed_m_s=float(np.linalg.norm(contact_vel[1:])),
            force_dot_relative_velocity_w=float(np.dot(world,relative)),friction_dot_relative_velocity_w=float(np.dot(tangent,relative)),distance_m=float(co.dist))
        contacts.append(record);total+=world;g=group_sums[role];g['normal_n']+=fn;g['tangent_n']+=record['tangent_n'];g['world_force_n']+=world;g['world_friction_n']+=tangent
        if role=='desk':desk+=world
        elif role in ['thumb','index','middle','palm']:
            hand+=world;hn+=normal;ht+=tangent;torque+=np.cross(np.asarray(co.pos)-com,world)
    for g,a in group_sums.items():
        reconstruction=max(reconstruction,abs(a['normal_n']-s['forces'][g]))
        a['world_force_n']=a['world_force_n'].tolist();a['world_friction_n']=a['world_friction_n'].tolist()
    mass=float(model.body_mass[payload]);weight=mass*abs(model.opt.gravity[2]);grip=[c for c in contacts if c['role'] in ['thumb','index','middle','palm'] and c['normal_n']>.00001]
    rotational=np.zeros(6);mj.mj_objectVelocity(model,data,mj.mjtObj.mjOBJ_BODY,payload,rotational,0)
    bottom=np.min(np.array(case['mug_local_bounds_corners'])@objR.T+data.xpos[payload],axis=0)[2]
    result=dict(time_s=s['time_after_s'],stage=s['stage'],opposing=s['opposing'],desk_supported=s['desk_supported'],cup_com_m=com.tolist(),cup_velocity_m_s=s['object_velocity_m_s'],cup_angular_speed_rad_s=float(np.linalg.norm(rotational[:3])),
        object_local_to_wrist_m=s['object_local_m'],weight_n=weight,contacts=contacts,groups=group_sums,hand_force_world_n=hand.tolist(),desk_force_world_n=desk.tolist(),
        hand_normal_world_n=hn.tolist(),hand_friction_world_n=ht.tolist(),hand_torque_about_com_nm=torque.tolist(),net_contact_plus_gravity_n=(total+mass*model.opt.gravity).tolist(),
        maximum_recorded_normal_force_reconstruction_error_n=reconstruction,hand_supported_weight_fraction=float(hand[2]/weight),friction_supported_weight_fraction=float(ht[2]/weight),cup_bottom_m=float(bottom))
    if load_lp:
        result['static_capacity_contact_caps']=capacity(grip,weight,com)
        result['static_capacity_group_caps']=capacity(grip,weight,com,True)
    return result


def run(root,parent):
    import mujoco
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    out=root/'FRICTION_RECONSTRUCTION.json';assert not out.exists();episode=parent/'version_02/full';r=read_bound_json(episode/'REPORT.json');c=read_bound_json(Path(r['case']['path']));t=read_bound_json(episode/'TRACE.json');model=load_model(r['model']['path']);model.opt.timestep=.005;data=mujoco.MjData(model);payload=model.body('payload').id
    start=next(i for i,a in enumerate(t['records']) if a['stage']=='lift');selected_lp={start-25,start-1,start,start+5,start+10,start+15,start+20,start+25,start+30,len(t['records'])-1};rows=[]
    for index in range(start-30,len(t['records'])):
        for k,s in enumerate(t['records'][index]['substeps']):rows.append(frame(mujoco,model,data,s,payload,c,load_lp=(index in selected_lp and k==3)))
        if index%25==0:print(dict(tick=index,rows=len(rows)),flush=True)
    # Known supported, no-hand precontact state fixes the force convention independently.
    calibration_sample=t['records'][850]['substeps'][-1];cal=frame(mujoco,model,data,calibration_sample,payload,c)
    assert abs(cal['desk_force_world_n'][2]-cal['weight_n'])<.02 and np.linalg.norm(cal['hand_force_world_n'])<1e-6
    assert max(a['maximum_recorded_normal_force_reconstruction_error_n'] for a in rows)<1e-8
    result=dict(schema='native-grasp-actual-friction-forensics/v1',new_physics_steps=0,mujoco_version=mujoco.__version__,solver=int(model.opt.solver),cone=int(model.opt.cone),integrator=int(model.opt.integrator),gravity=model.opt.gravity.tolist(),mass_kg=float(model.body_mass[payload]),
        calibration=cal,rows=rows,state_samples=len(rows),report=_file_binding(episode/'REPORT.json'),trace=_file_binding(episode/'TRACE.json'),model=r['model'],implementation=_file_binding(Path(__file__)),
        interpretation='Exact recorded post-step state/contact reconstruction with original model and ctrl; no mj_step, no settings or physical states used for new execution. Instantaneous post-forward forces, not a new simulation or a force-perturbation counterfactual.')
    safe_save(out,result);print(dict(saved=str(out),rows=len(rows),new_physics_steps=0,cone=int(model.opt.cone),mass_kg=result['mass_kg']),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);ap.add_argument('--parent',type=Path,required=True);a=ap.parse_args();run(a.root,a.parent)
