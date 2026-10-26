"""Separate native touching joint poses from friction/PD compensated motor references."""
import argparse,os,resource
from pathlib import Path
import numpy as np
from scipy.optimize import least_squares,linprog
from scipy.spatial.transform import Rotation
from .mesh_grasp_plan_r2 import MeshDistanceQuery,DISTAL,ROLES,right_indices
from .posture_screen import load_model,hand_ids,contact_pair,IK
from .protocol import read_bound_json,safe_save,_file_binding
from sage.experiments.embodied_carry_v1.grasp import RIGHT_CLOSED
from sage.experiments.embodied_native_sonic_loaded_grasp_v1.quality import contacts,required_preload

def run(root):
    import mujoco
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8]);episode=root/'attempt_09/full';r=read_bound_json(episode/'REPORT.json');t=read_bound_json(episode/'TRACE.json');plan=read_bound_json(root/'NATIVE_MESH_GRASP_PLAN.json')['selected'];m=load_model(r['model']['path']);native_margin=m.geom_margin.copy();d=mujoco.MjData(m);h=hand_ids(m);ix=right_indices(m,h);names=[h['names'][i] for i in ix];fq=h['qpos'][ix];fd=h['dofs'][ix];ends=np.array([RIGHT_CLOSED[n]*.5 for n in names]);q0=np.array(t['records'][979]['substeps'][-1]['full_qpos_after']);query=MeshDistanceQuery(mujoco,m);initial=np.array(plan['finger_angles_rad']);direction=np.sign(ends);reserve=.1/h['kp'][ix];lo=np.minimum(0,ends)+np.where(ends<0,reserve,1e-6);hi=np.maximum(0,ends)-np.where(ends>0,reserve,1e-6);initial=np.clip(initial,lo+1e-6,hi-1e-6)
    finger_initial=initial.copy();ik=IK(mujoco,m);fit=ik.solve(q0,np.array(plan['wrist_goal_m']),np.array(plan['rotation']),max_evaluations=200);arm_initial=np.array(fit['angles_rad']);arm_lo=np.maximum(ik.lower,arm_initial-.25);arm_hi=np.minimum(ik.upper,arm_initial+.25);initial=np.r_[arm_initial,finger_initial];lo=np.r_[arm_lo,lo];hi=np.r_[arm_hi,hi];w=m.body('right_wrist_yaw_link').id
    def residual(x):
        q=q0.copy();q[ik.qids]=x[:7];q[fq]=x[7:];roles,gaps,scene=query.inspect(q);err=[(roles[g]['distance']+.0002)/.001 for g in ROLES];err.extend(max(.002-gaps[g],0)/.001 for g in query.non_distal);err.append(max(.003-scene,0)/.001);err.extend(max(abs(roles[g]['normal_z'])-.2,0)/.1 for g in ROLES);err.extend(.02*(x-initial)/.3);err.extend(10.*(query.data.xpos[w]-np.array(plan['wrist_goal_m']))/.02);err.extend(10.*Rotation.from_matrix(np.array(plan['rotation']).T@query.data.xmat[w].reshape(3,3)).as_rotvec()/.2);return np.array(err)
    opt=least_squares(residual,initial,bounds=(lo+1e-7,hi-1e-7),max_nfev=150,diff_step=1e-4,ftol=1e-7,xtol=1e-8,gtol=1e-6);q=q0.copy();q[ik.qids]=opt.x[:7];q[fq]=opt.x[7:];d.qpos[:]=q;d.qvel[:]=0.;mujoco.mj_forward(m,d);rows,info=contacts(mujoco,m,d,True);pre=required_preload(rows,info['weight_n'],np.array(info['com_m']),2.);bad=[]
    for c in d.contact:
        pair=contact_pair(m,c);ns=[a['name'] for a in pair]
        if 'payload_surface' in ns:
            other=pair[1-ns.index('payload_surface')]
            if other['body'].startswith('right_hand_') and other['body'] not in DISTAL and c.dist<0:bad.append(dict(reason='non_distal',pair=pair,distance_m=float(c.dist)))
        elif c.dist<0 and any(a['body'].startswith('right_hand_') for a in pair) and any(n.startswith('scene_collision_') for n in ns):bad.append(dict(reason='hand_scene',pair=pair,distance_m=float(c.dist)))
    W=[];T=[];roles=[];pid=m.body('payload').id;com=d.xipos[pid]
    for c in d.contact:
        pair=contact_pair(m,c);ns=[a['name'] for a in pair]
        if 'payload_surface' not in ns or c.dist>=0:continue
        side=ns.index('payload_surface');other=pair[1-side]
        if other['body'] not in DISTAL:continue
        role=next(g for g in ROLES if g in other['body']);J=np.zeros((3,m.nv));mujoco.mj_jac(m,d,J,None,c.pos,int(m.geom_bodyid[c.geom[1-side]]));D=np.array(c.frame).reshape(3,3);sign=1. if side==1 else -1.;u,v=c.friction[:2]
        for local in [[1,u,0],[1,-u,0],[1,0,v],[1,0,-v]]:
            F=sign*D.T@local;W.append(np.r_[F,np.cross(c.pos-com,F)]);T.append(J[:,fd].T@F);roles.append(role)
    allocation=None
    if pre['feasible'] and len(W):
        W=np.array(W).T;T=np.array(T).T;A=np.array([[float(x==g) for x in roles] for g in ROLES]);minimum=np.array([max(1.5,pre['required_group_normal_n'][g]) for g in ROLES]);dry=direction*m.dof_frictionloss[fd];offset=d.qfrc_bias[fd]-d.qfrc_passive[fd]+dry;act=h['actuators'][ix];tau_lo=np.maximum(m.actuator_ctrlrange[act,0],h['kp'][ix]*(np.minimum(0,ends)-opt.x[7:]));tau_hi=np.minimum(m.actuator_ctrlrange[act,1],h['kp'][ix]*(np.maximum(0,ends)-opt.x[7:]));z=linprog(np.ones(len(roles)),A_ub=np.r_[A,-A,T,-T],b_ub=np.r_[np.full(3,6.),-minimum,tau_hi-offset,-tau_lo+offset],A_eq=W,b_eq=np.zeros(6),bounds=(0,None),method='highs')
        if z.success:
            contact_tau=T@z.x;motor=contact_tau+offset;reference=opt.x[7:]+motor/h['kp'][ix];allocation=dict(feasible=True,preload_requested_net_wrench=[0.]*6,group_normals_n={g:float((A@z.x)[i]) for i,g in enumerate(ROLES)},desired_contact_torque_nm=contact_tau.tolist(),quasistatic_closing_dry_friction_nm=dry.tolist(),native_bias_minus_passive_nm=(d.qfrc_bias[fd]-d.qfrc_passive[fd]).tolist(),required_motor_torque_nm=motor.tolist(),motor_reference_angles_rad=reference.tolist(),original_halfclosed_bounds_passed=bool(np.all(reference>=np.minimum(0,ends)-1e-10) and np.all(reference<=np.maximum(0,ends)+1e-10)),net_wrench_residual=float(np.max(np.abs(W@z.x))))
        else:allocation=dict(feasible=False,reason=z.message)
    depth=max([-x['distance_m'] for x in rows],default=0.);groups=sorted(set(x['role'] for x in rows));vertical=max([abs(x['normal_vertical']) for x in rows],default=1.);eligible=bool(len(groups)==3 and depth<=.001 and not bad and pre['feasible'] and allocation and allocation['feasible'] and allocation['original_halfclosed_bounds_passed'] and vertical<=.3)
    assert np.array_equal(m.geom_margin,native_margin);safe_save(root/'EQUILIBRIUM_GRASP_PLAN_R3.json',dict(new_physics_steps=0,eligible=eligible,source_tick=979,source_active_prefix_ticks=980,source_physics_prefix_steps=3960,source_report=_file_binding(episode/'REPORT.json'),source_trace=r['trace'],physical_touch_joint_names=names,arm_reference_angles_rad=opt.x[:7].tolist(),wrist_goal_m=d.xpos[w].tolist(),wrist_rotation=d.xmat[w].reshape(3,3).tolist(),physical_touch_angles_rad=opt.x[7:].tolist(),motor_reference_is_a_different_quantity=True,actual_native_geometric_contacts=rows,groups=groups,max_virtual_touch_penetration_m=depth,max_vertical_normal=vertical,bad=bad,preload_capacity_plan=pre,quasistatic_motor_allocation=allocation,native_query_calls=query.calls,optimizer_cost=float(opt.cost),original_model_unchanged=True,implementation=_file_binding(Path(__file__)),limitation='Zero-integration private native geometry and quasi-static closing-friction/PD equilibrium plan. Contact-pose angles are not used as loaded motor targets. The query-only margin copy is never integrated. Static friction/contact compatibility and resulting actual equilibrium still require physical validation. Original task/physical/halfclosed motor bounds unchanged.'));print(dict(eligible=eligible,groups=groups,depth=depth,vertical=vertical,bad=bad,preload=pre,allocation=allocation,arm_reference_angles_rad=opt.x[:7].tolist(),wrist_goal_m=d.xpos[w].tolist(),wrist_rotation=d.xmat[w].reshape(3,3).tolist(),physical_touch_angles_rad=opt.x[7:].tolist()),flush=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);run(ap.parse_args().root)
