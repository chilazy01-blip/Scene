"""Plan cup-body contacts with explicit rim margin, using private kinematic queries."""
import argparse,os,resource,time
from pathlib import Path
import numpy as np
from scipy.optimize import least_squares,linprog
from scipy.spatial.transform import Rotation
from sage.experiments.embodied_native_sonic_grasp_feedback_v1.mesh_grasp_plan_r2 import MeshDistanceQuery,DISTAL,ROLES,right_indices
from sage.experiments.embodied_native_sonic_grasp_feedback_v1.posture_screen import load_model,hand_ids,contact_pair,IK
from sage.experiments.embodied_carry_v1.grasp import RIGHT_CLOSED,group
from sage.experiments.embodied_native_sonic_loaded_grasp_v1.quality import contacts,required_preload
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding


def run(root,parent,offset):
    import mujoco as mj
    source=parent/'attempt_09/full';r=read_bound_json(source/'REPORT.json');trace=read_bound_json(source/'TRACE.json')
    old=read_bound_json(parent/'EQUILIBRIUM_GRASP_PLAN_R3.json')
    m=load_model(r['model']['path']);d=mj.MjData(m);h=hand_ids(m);ix=right_indices(m,h);fq=h['qpos'][ix];fd=h['dofs'][ix]
    names=[h['names'][i] for i in ix];ends=np.array([RIGHT_CLOSED[n]*.5 for n in names]);q0=np.array(trace['records'][979]['substeps'][-1]['full_qpos_after'])
    query=MeshDistanceQuery(mj,m);ik=IK(mj,m);w=m.body('right_wrist_yaw_link').id;pid=m.body('payload').id
    R=np.array(old['wrist_rotation']);goal=np.array(old['wrist_goal_m'])+np.array([0,0,offset]);fit=ik.solve(q0,goal,R,max_evaluations=250)
    reserve=.1/h['kp'][ix];flo=np.minimum(0,ends)+np.where(ends<0,reserve,1e-6);fhi=np.maximum(0,ends)-np.where(ends>0,reserve,1e-6)
    initial=np.r_[fit['angles_rad'],old['physical_touch_angles_rad']]
    lo=np.r_[np.maximum(ik.lower,initial[:7]-.4),flo];hi=np.r_[np.minimum(ik.upper,initial[:7]+.4),fhi]
    initial=np.clip(initial,lo+1e-7,hi-1e-7);printed=[0];begin=time.monotonic()
    def details():
        data=query.data;objR=data.xmat[pid].reshape(3,3);origin=data.xpos[pid];points={g:[] for g in ROLES}
        for c in data.contact:
            pair=contact_pair(query.model,c);ns=[a['name'] for a in pair]
            if 'payload_surface' not in ns:continue
            other=pair[1-ns.index('payload_surface')]
            if group(other['body']) not in ROLES:continue
            if c.dist<.003:points[group(other['body'])].append((np.asarray(c.pos)-origin)@objR)
        return {g:float(np.mean([p[2] for p in points[g]])) if points[g] else .055 for g in ROLES}
    def residual(x):
        q=q0.copy();q[ik.qids]=x[:7];q[fq]=x[7:];oldroles,gaps,scene=query.inspect(q);z=details();roles={g:dict(distance=.015,normal_z=0.) for g in ROLES}
        for co in query.data.contact:
            pair=contact_pair(query.model,co);ns=[a['name'] for a in pair]
            if 'payload_surface' not in ns:continue
            side=ns.index('payload_surface');g=group(pair[1-side]['body'])
            if g in roles and co.dist<roles[g]['distance']:roles[g]=dict(distance=float(co.dist),normal_z=float((1 if side==1 else -1)*co.frame[2]))
        err=[(roles[g]['distance']+.00025)/.001 for g in ROLES]
        # All native hand segments may make legal cup contacts; no fingertip-only ban.
        err.append(max(.003-scene,0)/.001)
        err.extend(max(abs(roles[g]['normal_z'])-.2,0)/.1 for g in ROLES)
        err.extend(max(z[g]-.042,0)/.003 for g in ROLES)
        err.extend(max(-.035-z[g],0)/.003 for g in ROLES)
        err.extend(2.*(query.data.xpos[w]-goal)/.015)
        err.extend(2.*Rotation.from_matrix(R.T@query.data.xmat[w].reshape(3,3)).as_rotvec()/.12)
        err.extend(.015*(x-initial)/.3)
        if query.calls-printed[0]>=100:
            printed[0]=query.calls;print(dict(queries=query.calls,offset=offset,z=z,max_residual=float(np.max(np.abs(err)))),flush=True)
        return np.asarray(err)
    opt=least_squares(residual,initial,bounds=(lo+1e-8,hi-1e-8),max_nfev=100,diff_step=1e-4,ftol=1e-6,xtol=1e-7,gtol=1e-6)
    q=q0.copy();q[ik.qids]=opt.x[:7];q[fq]=opt.x[7:];d.qpos[:]=q;d.qvel[:]=0;mj.mj_forward(m,d)
    rows,info=contacts(mj,m,d,True);pre=required_preload(rows,info['weight_n'],np.array(info['com_m']),2.)
    bad=[];heights={g:[] for g in ROLES};W=[];T=[];roles=[]
    for c in d.contact:
        pair=contact_pair(m,c);ns=[a['name'] for a in pair]
        if 'payload_surface' in ns:
            side=ns.index('payload_surface');other=pair[1-side]
            if c.dist>=0:continue
            if group(other['body']) not in ROLES:continue
            role=group(other['body']);local=d.xmat[pid].reshape(3,3).T@(c.pos-d.xpos[pid]);heights[role].append(float(local[2]))
            J=np.zeros((3,m.nv));mj.mj_jac(m,d,J,None,c.pos,int(m.geom_bodyid[c.geom[1-side]]));D=np.asarray(c.frame).reshape(3,3);sign=1 if side==1 else -1;u,v=c.friction[:2]
            for ray in [[1,u,0],[1,-u,0],[1,0,v],[1,0,-v]]:
                F=sign*D.T@ray;W.append(np.r_[F,np.cross(c.pos-d.xipos[pid],F)]);T.append(J[:,fd].T@F);roles.append(role)
        elif c.dist<0 and any(a['body'].startswith('right_hand_') for a in pair) and any(n.startswith('scene_collision_') for n in ns):bad.append(dict(reason='hand_scene',pair=pair,depth=-float(c.dist)))
    allocation=None
    if W and pre['feasible']:
        W=np.asarray(W).T;T=np.asarray(T).T;A=np.array([[float(x==g) for x in roles] for g in ROLES]);minimum=np.array([max(1.5,pre['required_group_normal_n'][g]) for g in ROLES]);dry=np.sign(ends)*m.dof_frictionloss[fd];offset_tau=d.qfrc_bias[fd]-d.qfrc_passive[fd]+dry;act=h['actuators'][ix]
        tlo=np.maximum(m.actuator_ctrlrange[act,0],h['kp'][ix]*(np.minimum(0,ends)-opt.x[7:]));thi=np.minimum(m.actuator_ctrlrange[act,1],h['kp'][ix]*(np.maximum(0,ends)-opt.x[7:]))
        z=linprog(np.ones(len(roles)),A_ub=np.r_[A,-A,T,-T],b_ub=np.r_[np.full(3,6),-minimum,thi-offset_tau,-tlo+offset_tau],A_eq=W,b_eq=np.zeros(6),bounds=(0,None),method='highs')
        if z.success:
            ref=opt.x[7:]+(T@z.x+offset_tau)/h['kp'][ix];allocation=dict(feasible=True,motor_reference_angles_rad=ref.tolist(),group_normals_n={g:float((A@z.x)[i]) for i,g in enumerate(ROLES)},net_wrench_error=float(np.max(np.abs(W@z.x))))
        else:allocation=dict(feasible=False,reason=z.message)
    margins={g:.055-max(v) if v else -1 for g,v in heights.items()}
    depth=max([-x['distance_m'] for x in rows],default=0)
    eligible=bool(all(v for v in heights.values()) and min(margins.values())>=.008 and depth<.001 and not bad and allocation and allocation['feasible'])
    out=root/f'POWER_GRASP_PLAN_{int(abs(offset)*1000):02d}.json';assert not out.exists()
    result=dict(new_physics_steps=0,eligible=eligible,offset_z_m=offset,wrist_goal_m=d.xpos[w].tolist(),wrist_rotation=d.xmat[w].reshape(3,3).tolist(),
        physical_touch_joint_names=names,physical_touch_angles_rad=opt.x[7:].tolist(),arm_reference_angles_rad=opt.x[:7].tolist(),quasistatic_motor_allocation=allocation,
        original_contacts=rows,contact_heights_m=heights,rim_margin_m=margins,bad=bad,max_penetration_m=depth,preload_capacity_plan=pre,optimizer_cost=float(opt.cost),queries=query.calls,wall_s=time.monotonic()-begin,
        source_report=_file_binding(source/'REPORT.json'),source_trace=r['trace'],old_plan=_file_binding(parent/'EQUILIBRIUM_GRASP_PLAN_R3.json'),model=r['model'],implementation=_file_binding(Path(__file__)),
        limitation='Private reference planning using original final contact model; no physical state insertion and no dynamic success claimed.')
    safe_save(out,result);print({k:result[k] for k in ['eligible','rim_margin_m','bad','quasistatic_motor_allocation','wall_s','queries']},flush=True)


if __name__=='__main__':
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);ap.add_argument('--parent',type=Path,required=True);ap.add_argument('--offset',type=float,default=-.015)
    a=ap.parse_args();run(a.root,a.parent,a.offset)
