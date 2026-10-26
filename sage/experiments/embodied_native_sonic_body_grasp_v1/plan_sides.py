"""Plan actual native finger pad points on the cup body before collision refinement."""
import argparse,os,resource,time
from pathlib import Path
import numpy as np
from scipy.optimize import least_squares,linprog
from scipy.spatial.transform import Rotation
from .plan import read_bound_json,safe_save,_file_binding,load_model,hand_ids,right_indices,IK,MeshDistanceQuery,DISTAL,ROLES,contact_pair,contacts,required_preload,RIGHT_CLOSED,group


def run(root,parent,number=1):
    import mujoco as mj
    source=parent/'attempt_09/full';r=read_bound_json(source/'REPORT.json');trace=read_bound_json(source/'TRACE.json');old=read_bound_json(parent/'EQUILIBRIUM_GRASP_PLAN_R3.json')
    m=load_model(r['model']['path']);d=mj.MjData(m);ik=IK(mj,m);h=hand_ids(m);ix=right_indices(m,h);names=[h['names'][i] for i in ix];fq=h['qpos'][ix];fd=h['dofs'][ix]
    q0=np.array(trace['records'][979]['substeps'][-1]['full_qpos_after']);q=q0.copy();q[ik.qids]=old['arm_reference_angles_rad'];q[fq]=old['physical_touch_angles_rad'];d.qpos[:]=q;mj.mj_fwdPosition(m,d)
    w=m.body('right_wrist_yaw_link').id;pid=m.body('payload').id;objR=d.xmat[pid].reshape(3,3).copy();origin=d.xpos[pid].copy()
    anchors={};normals={};local_points={};bodies={}
    for c in d.contact:
        pair=contact_pair(m,c);ns=[a['name'] for a in pair]
        if 'payload_surface' not in ns or c.dist>0:continue
        side=ns.index('payload_surface');body=pair[1-side]['body']
        if body not in DISTAL:continue
        g=group(body)
        if g in anchors:continue
        bid=m.body(body).id;B=d.xmat[bid].reshape(3,3)
        anchors[g]=B.T@(c.pos-d.xpos[bid]);normals[g]=B.T@((1 if side==1 else -1)*np.array(c.frame[:3]));bodies[g]=bid;local_points[g]=objR.T@(c.pos-origin)
    assert len(anchors)==3
    profile=read_bound_json(parent/'CUP_AXIS_GEOMETRY.json');center_world=origin+np.r_[profile['selected_axis_offset_world_xy_m'],0.];center_local=objR.T@(center_world-origin)
    flex=mj.mj_name2id(m,mj.mjtObj.mjOBJ_FLEX,'payload_surface');a=int(m.flex_vertadr[flex]);n=int(m.flex_vertnum[flex]);verts=np.asarray(m.flex_vert[a:a+n])
    ratio=.85;closed=np.array([RIGHT_CLOSED[n]*ratio for n in names]);reserve=.1/h['kp'][ix];native=np.array([m.joint(n).range for n in names]);flo=np.maximum(np.minimum(0,closed)+np.where(closed<0,reserve,1e-6),native[:,0]+1e-6);fhi=np.minimum(np.maximum(0,closed)-np.where(closed>0,reserve,1e-6),native[:,1]-1e-6)
    lo=np.r_[ik.lower+1e-6,flo];hi=np.r_[ik.upper-1e-6,fhi]
    # Approach from the side so proximal links stay clear of the cup rim.
    turns={1:(-90.,0.),2:(-90.,-90.),3:(-75.,-90.),4:(-90.,-45.),5:(-60.,-90.),6:(-105.,-90.)}
    tilt,yaw=turns[number]
    wanted=Rotation.from_euler('z',yaw,degrees=True).as_matrix()@Rotation.from_euler('y',tilt,degrees=True).as_matrix()@np.array(old['wrist_rotation'])
    seedf=np.array(old['physical_touch_angles_rad']);qseed=q0.copy();qseed[fq]=seedf;d.qpos[:]=qseed;mj.mj_kinematics(m,d)
    actualW=d.xmat[w].reshape(3,3).copy();localpads={g:actualW.T@(d.xpos[bodies[g]]+d.xmat[bodies[g]].reshape(3,3)@anchors[g]-d.xpos[w]) for g in ROLES}
    raw={g:wanted@localpads[g] for g in ROLES}
    cross=(raw['index']+raw['middle'])/2;centerxy=(cross[:2]+raw['thumb'][:2])/2
    meanz=np.mean([x[2] for x in raw.values()]);goals={};directions={}
    for g in ROLES:
        u=raw[g][:2]-centerxy;u/=np.linalg.norm(u)
        worldtarget=origin+np.r_[profile['selected_axis_offset_world_xy_m'],0.]+np.r_[u*.041,raw[g][2]-meanz+.008]
        target=objR.T@(worldtarget-origin);radial=np.linalg.norm(verts[:,:2]-center_local[:2],axis=1)
        mask=(abs(verts[:,2]-target[2])<.004)&(radial>.038)&(radial<.047)
        available=verts[mask]
        if not len(available):available=verts[(radial>.038)&(radial<.047)]
        point=available[np.argmin(np.sum((available-target)**2,axis=1))]
        goals[g]=origin+objR@point+np.r_[u*.0004,0];directions[g]=np.r_[-u,0]
    wristgoal=np.mean([goals[g]-raw[g] for g in ROLES],axis=0)
    seedfit=ik.solve(q0,wristgoal,wanted,max_evaluations=400)
    print(dict(side_seed=number,tilt=tilt,yaw=yaw,wrist_goal=wristgoal.tolist(),position_error=seedfit['position_error_m'],orientation_error=seedfit['orientation_error_rad']),flush=True)
    initial=np.r_[seedfit['angles_rad'],seedf];initial=np.clip(initial,lo+1e-7,hi-1e-7)
    def fk_residual(x):
        d.qpos[:]=q0;d.qpos[ik.qids]=x[:7];d.qpos[fq]=x[7:];mj.mj_kinematics(m,d)
        err=[]
        for g in ROLES:
            B=d.xmat[bodies[g]].reshape(3,3);point=d.xpos[bodies[g]]+B@anchors[g]
            err.extend((point-goals[g])/.003);err.extend(.5*(B@normals[g]-directions[g]))
        err.extend(.005*(x-initial));return np.array(err)
    begin=time.monotonic();fit=least_squares(fk_residual,initial,bounds=(lo,hi),max_nfev=500,ftol=1e-10,xtol=1e-10,gtol=1e-8)
    first=fit.x.copy();query=MeshDistanceQuery(mj,m);printed=[0]
    def refine(x):
        err=list(fk_residual(x));z=q0.copy();z[ik.qids]=x[:7];z[fq]=x[7:];query.inspect(z)
        gaps={gid:.015 for gid in query.hand_geoms};rim=gaps.copy();roles={g:.015 for g in ROLES}
        for c in query.data.contact:
            pair=contact_pair(query.model,c);ns=[v['name'] for v in pair]
            if 'payload_surface' not in ns:continue
            side=ns.index('payload_surface');gid=int(c.geom[1-side]);g=group(pair[1-side]['body']);local=objR.T@(c.pos-origin)
            if gid in gaps:gaps[gid]=min(gaps[gid],float(c.dist))
            if gid in rim and local[2]>.045:rim[gid]=min(rim[gid],float(c.dist))
            if g in roles and -.035<local[2]<.042:roles[g]=min(roles[g],float(c.dist))
        err.extend((roles[g]+.0002)/.001 for g in ROLES)
        err.extend(max(-.0006-v,0)/.001 for v in gaps.values())
        err.extend(max(.0005-v,0)/.001 for v in rim.values())
        if query.calls-printed[0]>=100:printed[0]=query.calls;print(dict(queries=query.calls,roles=roles,max_depth=-min(gaps.values()),rim_gap=min(rim.values()),cost=float(np.linalg.norm(err))),flush=True)
        return np.asarray(err)
    opt=least_squares(refine,first,bounds=(lo,hi),max_nfev=120,diff_step=1e-3,ftol=1e-7,xtol=1e-8,gtol=1e-7)
    q=q0.copy();q[ik.qids]=opt.x[:7];q[fq]=opt.x[7:];d.qpos[:]=q;d.qvel[:]=0;mj.mj_forward(m,d)
    cs,info=contacts(mj,m,d,True);pre=required_preload(cs,info['weight_n'],np.array(info['com_m']),2.);W=[];T=[];roles=[];zroles={g:[] for g in ROLES};bad=[]
    for c in d.contact:
        pair=contact_pair(m,c);ns=[a['name'] for a in pair]
        if 'payload_surface' in ns and c.dist<0:
            side=ns.index('payload_surface');g=group(pair[1-side]['body'])
            if g not in ROLES:continue
            zroles[g].append(float((objR.T@(c.pos-origin))[2]));J=np.zeros((3,m.nv));mj.mj_jac(m,d,J,None,c.pos,int(m.geom_bodyid[c.geom[1-side]]));D=np.array(c.frame).reshape(3,3);sign=1 if side==1 else -1;u,v=c.friction[:2]
            for ray in [[1,u,0],[1,-u,0],[1,0,v],[1,0,-v]]:
                F=sign*D.T@ray;W.append(np.r_[F,np.cross(c.pos-d.xipos[pid],F)]);T.append(J[:,fd].T@F);roles.append(g)
        elif c.dist<-.001 and any(a['body'].startswith('right_hand_') for a in pair) and any(n.startswith('scene_collision_') for n in ns):bad.append(dict(pair=pair,depth=-float(c.dist)))
    allocation=None
    if W and pre['feasible']:
        W=np.array(W).T;T=np.array(T).T;A=np.array([[float(x==g) for x in roles] for g in ROLES]);minimum=np.array([max(1.5,pre['required_group_normal_n'][g]) for g in ROLES]);dry=np.sign(closed)*m.dof_frictionloss[fd];offset=d.qfrc_bias[fd]-d.qfrc_passive[fd]+dry;act=h['actuators'][ix];tlo=np.maximum(m.actuator_ctrlrange[act,0],h['kp'][ix]*(np.minimum(0,closed)-opt.x[7:]));thi=np.minimum(m.actuator_ctrlrange[act,1],h['kp'][ix]*(np.maximum(0,closed)-opt.x[7:]))
        z=linprog(np.ones(len(roles)),A_ub=np.r_[A,-A,T,-T],b_ub=np.r_[np.full(3,6.),-minimum,thi-offset,-tlo+offset],A_eq=W,b_eq=np.zeros(6),bounds=(0,None),method='highs')
        if z.success:allocation=dict(feasible=True,motor_reference_angles_rad=(opt.x[7:]+(T@z.x+offset)/h['kp'][ix]).tolist(),group_normals_n={g:float((A@z.x)[i]) for i,g in enumerate(ROLES)},net_wrench_error=float(np.max(np.abs(W@z.x))))
        else:allocation=dict(feasible=False,reason=z.message)
    margins={g:.055-max(v) if v else -1 for g,v in zroles.items()};depth=max([-c['distance_m'] for c in cs],default=0.)
    eligible=bool(all(v for v in zroles.values()) and min(margins.values())>=.008 and depth<.001 and not bad and allocation and allocation['feasible'])
    out=root/f'SIDE_GRASP_PLAN_{number:02d}.json';assert not out.exists()
    result=dict(eligible=eligible,new_physics_steps=0,reference_ratio=ratio,seed_tilt_deg=tilt,seed_yaw_deg=yaw,seed_ik=seedfit,physical_touch_joint_names=names,physical_touch_angles_rad=opt.x[7:].tolist(),arm_reference_angles_rad=opt.x[:7].tolist(),wrist_goal_m=d.xpos[w].tolist(),wrist_rotation=d.xmat[w].reshape(3,3).tolist(),quasistatic_motor_allocation=allocation,preload_capacity_plan=pre,original_contacts=cs,contact_heights_m=zroles,rim_margin_m=margins,max_penetration_m=depth,bad=bad,pad_targets_world={g:p.tolist() for g,p in goals.items()},fk_initial_fit_cost=float(fit.cost),optimizer_cost=float(opt.cost),queries=query.calls,wall_s=time.monotonic()-begin,source_report=_file_binding(source/'REPORT.json'),source_trace=r['trace'],model=r['model'],old_plan=_file_binding(parent/'EQUILIBRIUM_GRASP_PLAN_R3.json'),implementation=_file_binding(Path(__file__)),limitation='Native pad-point reference planning and static contact/PD screen only; no physical state insertion and no dynamic success.')
    safe_save(out,result);print({k:result[k] for k in ['eligible','rim_margin_m','max_penetration_m','quasistatic_motor_allocation','fk_initial_fit_cost','optimizer_cost','wall_s']},flush=True)


if __name__=='__main__':
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);ap.add_argument('--parent',type=Path,required=True);ap.add_argument('--number',type=int,default=1)
    a=ap.parse_args();run(a.root,a.parent,a.number)
