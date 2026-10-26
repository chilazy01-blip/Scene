"""Fresh-data validation of a repaired snapshot against its original task geometry."""
import numpy as np
import mujoco
from scipy.spatial.transform import Rotation
from sage.experiments.embodied_expert_task_v1.quality import names_and_roles,contacts,kinematics

def validate_pose(model,state,qpos,pair_names,limits,grasp_sides=('left','right')):
    original=mujoco.MjData(model);data=mujoco.MjData(model)
    for d,q in ((original,state[1:1+model.nq]),(data,qpos)):
        d.time=state[0];d.qpos[:]=q;d.qvel[:]=state[1+model.nq:];mujoco.mj_forward(model,d)
    names,roles=names_and_roles(model,{mujoco.mj_id2name(model,mujoco.mjtObj.mjOBJ_GEOM,i) for i in range(model.ngeom) if (mujoco.mj_id2name(model,mujoco.mjtObj.mjOBJ_GEOM,i) or '').startswith('box_')})
    q0=original.qpos;delta=data.qpos-q0;issues=[];joint_bound_excess=0.
    if not np.array_equal(data.qpos[2:7],q0[2:7]) or not np.array_equal(data.qpos[-7:],q0[-7:]):issues.append('fixed_root_or_object_changed')
    if np.max(np.abs(delta[:2]))>.03+1e-9:issues.append('root_shift_bound')
    for j in range(model.njnt):
        if model.jnt_type[j]!=mujoco.mjtJoint.mjJNT_HINGE:continue
        name=mujoco.mj_id2name(model,mujoco.mjtObj.mjOBJ_JOINT,j);amount=.35 if 'hand' in name else .1 if any(x in name for x in ('hip','knee','ankle')) else .25
        joint_bound_excess=max(joint_bound_excess,abs(float(delta[model.jnt_qposadr[j]]))-amount)
    if joint_bound_excess>1e-9:issues.append('joint_change_bound')
    feet=[i for i in range(model.nbody) if (mujoco.mj_id2name(model,mujoco.mjtObj.mjOBJ_BODY,i) or '').endswith('ankle_roll_link')]
    palms=[int(model.geom_bodyid[names.index('gripper0_'+side+'_g0_col')]) for side in ('left','right')]
    def pose_error(b):return float(np.linalg.norm(data.xpos[b]-original.xpos[b])),float(np.linalg.norm(Rotation.from_matrix(data.xmat[b].reshape(3,3)@original.xmat[b].reshape(3,3).T).as_rotvec()))
    fp,fr=np.max([pose_error(b) for b in feet],axis=0);pp,pr=np.max([pose_error(b) for b in palms],axis=0)
    if fp>1e-5 or fr>1e-4:issues.append('foot_anchor_bound')
    if pp>.035+1e-8 or pr>.08+1e-8:issues.append('palm_change_bound')
    kin=kinematics(model,data,limits);con=contacts(model,data,names,roles,limits);issues.extend(kin['violations']+con['violations'])
    cmap={}
    for c in data.contact[:data.ncon]:
        pair=tuple(sorted((int(c.geom1),int(c.geom2))));cmap[pair]=min(cmap.get(pair,float('inf')),float(c.dist))
    pairset=set(cmap)|{tuple(sorted((names.index(a),names.index(b)))) for a,b in pair_names};depth=0.;gap=float('inf');grasp={s:float('inf') for s in ('left','right')}
    for a,b in pairset:
        kinds={roles[a],roles[b]};allowed=kinds in ({'foot','floor'},{'hand','object'}) or not bool(kinds & {'robot','hand','foot'})
        dist=cmap[(a,b)] if (a,b) in cmap else max(0.,float(mujoco.mj_geomDistance(model,data,a,b,.005 if allowed else .0005,None)))
        if allowed:
            if kinds=={'hand','object'}:depth=max(depth,-dist)
        else:gap=min(gap,dist)
        if 'object' in kinds:
            for side in grasp:
                if any(names[g].startswith('gripper0_'+side+'_') for g in (a,b)):grasp[side]=min(grasp[side],dist)
    if depth>.005+1e-8:issues.append('repair_penetration_target')
    if gap<.0002-1e-8:issues.append('repair_forbidden_gap_target')
    if any(grasp[side]>.003+1e-8 for side in grasp_sides):issues.append('grasp_proximity')
    return dict(passed=not issues,issues=sorted(set(issues)),max_native_penetration=max([0.]+[-c['distance'] for c in con['contacts']]),max_repair_penetration=depth,min_forbidden_gap=gap,grasp_proximity=grasp,foot_translation_m=float(fp),foot_rotation_rad=float(fr),palm_translation_m=float(pp),palm_rotation_rad=float(pr),root_xy_delta_m=delta[:2].tolist(),joint_bound_excess=joint_bound_excess)
