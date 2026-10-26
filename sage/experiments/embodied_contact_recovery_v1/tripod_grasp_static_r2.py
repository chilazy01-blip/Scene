"""D bounded static search for three-digit acquisition using actual arm IK.

The object is fixed at its saved pose. Only scratch arm/finger joint positions
change; generated commands are not executed by this worker.
"""
import os, sys, itertools
from pathlib import Path
import numpy as np
import mujoco
import h5py
from .work import E,R,c,finish

work=Path(os.environ['CONTINUOUS_JOB_DIR']);os.environ.update(NP_ROOT=str(R),NP_JOB=str(work))
sys.path.insert(0,str(R/'tools'));sys.path.insert(0,str(R/'branches/A/source'))
from .target_adapter_r4 import install
install('A','gain_translation',work/'static_interface')
import run
from ik.sim import ArmIK6
folder=E/'jobs/C_development_03/episode';m=mujoco.MjModel.from_binary_path(str(folder/'MODEL.mjb'));d=mujoco.MjData(m)
with h5py.File(folder/'TRACE.h5','r') as f:initial=f['substep/integration_before'][17200]
mujoco.mj_setState(m,d,initial,mujoco.mjtState.mjSTATE_INTEGRATION);mujoco.mj_forward(m,d)
q0=d.qpos.copy();obj=m.body('red_block').id;sid=m.site('right_palm').id
palm=d.site_xpos[sid].copy();wrist=d.site_xmat[sid].reshape(3,3).copy()
ctrl=run.G1Controller(m,d,None,None,None,c.read(R/'branches/A/source/model_config.json'));ik=ArmIK6(m,ctrl)
names=['thumb_0','thumb_1','thumb_2','index_0','index_1','middle_0','middle_1'];closed=np.array([.8,-.9,-1.5,1.4,1.5,1.4,1.5]);qa=np.array([m.jnt_qposadr[m.joint('right_hand_'+n+'_joint').id] for n in names]);groups={'thumb':[0,1,2],'index':[3,4],'middle':[5,6]}
def contacts_for(digit=None):
    matches=[];forbidden=[]
    for ct in d.contact:
        bodies=[int(m.geom_bodyid[g]) for g in [ct.geom1,ct.geom2]];bn=[m.body(b).name for b in bodies]
        hand=any(n.startswith('right_hand') for n in bn)
        if not hand or ct.dist>0:continue
        if obj in bodies:
            if digit is None or any(n.startswith('right_hand_'+digit+'_') for n in bn):matches.append(ct)
        else:forbidden.append(ct)
    return matches,forbidden
def set_pose(arm,alphas):
    d.qpos[:]=q0;d.qvel[:]=0.;d.qpos[ik.qpos_idx]=arm
    for digit,ids in groups.items():d.qpos[qa[ids]]=closed[ids]*alphas[digit]
    mujoco.mj_forward(m,d)
def wrench_rank(contacts):
    maps=[]
    for ct in contacts:
        x,y,z=ct.pos-d.xipos[obj];skew=np.array([[0,-z,y],[z,0,-x],[-y,x,0]])
        maps.append(np.vstack([np.eye(3),skew/.037]))
    if not maps:return 0,[]
    s=np.linalg.svd(np.concatenate(maps,axis=1),compute_uv=False)
    return int(np.sum(s>1e-8)),s.tolist()
rows=[]
for offset in itertools.product([-.04,-.02,0.,.02,.04],repeat=3):
    d.qpos[:]=q0;mujoco.mj_forward(m,d)
    goal=palm+wrist@np.array(offset)
    arm,resid,rot_resid=ik.solve(d,goal,wrist,iters=100)
    result={'palm_local_offset_m':list(offset),'arm_ik_residual_m':float(resid),'arm_ik_rotation_residual':float(rot_resid),'finger_first_contact_alpha':{}}
    if resid>.003:
        result['static_candidate']=False;result['reason']='arm_ik_residual';rows.append(result);continue
    solved={};fail=None
    for digit,ids in groups.items():
        low=.15;high=None
        for alpha in np.linspace(.15,1.,35):
            alphas={n:.15 for n in groups};alphas[digit]=float(alpha);set_pose(arm,alphas)
            matches,forbidden=contacts_for(digit)
            if forbidden:
                result['first_forbidden']=[{'geoms':[m.geom(g).name for g in [ct.geom1,ct.geom2]],'penetration_m':float(-ct.dist)} for ct in forbidden];fail='forbidden_before_'+digit+'_contact';break
            if matches:
                high=float(alpha);break
            low=float(alpha)
        if fail or high is None:
            fail=fail or digit+'_not_reachable';break
        for _ in range(9):
            mid=.5*(low+high);alphas={n:.15 for n in groups};alphas[digit]=mid;set_pose(arm,alphas)
            matches,_=contacts_for(digit)
            if matches:high=mid
            else:low=mid
        solved[digit]=high+.001
    result['finger_first_contact_alpha']=solved
    if fail:
        result['static_candidate']=False;result['reason']=fail;rows.append(result);continue
    set_pose(arm,solved);matches,forbidden=contacts_for();rank,singular=wrench_rank(matches)
    actual_digits=sorted({m.body(int(m.geom_bodyid[g])).name.split('_')[2] for ct in matches for g in [ct.geom1,ct.geom2] if m.body(int(m.geom_bodyid[g])).name.startswith('right_hand')})
    max_pen=max([-float(ct.dist) for ct in matches],default=0.)
    result.update(arm_target_rad=arm.tolist(),finger_target_rad=d.qpos[qa].tolist(),contact_digits=actual_digits,
                  contacts=[{'geoms':[m.geom(g).name for g in [ct.geom1,ct.geom2]],'pos':ct.pos.tolist(),'penetration_m':float(-ct.dist)} for ct in matches],
                  forbidden=[{'geoms':[m.geom(g).name for g in [ct.geom1,ct.geom2]],'penetration_m':float(-ct.dist)} for ct in forbidden],
                  wrench_rank=rank,wrench_singular_values=singular,maximum_penetration_m=max_pen,
                  static_candidate=bool(not forbidden and actual_digits==['index','middle','thumb'] and rank==6 and max_pen<=.002))
    rows.append(result)
valid=[r for r in rows if r['static_candidate']]
report={'physics_steps':0,'policy_calls':0,'source':str(folder),'source_row':17200,'method':'D_object_pose_planning',
        'variables':'Seven arm joints from actual fixed-object IK and three independent digit closure fractions;125 bounded palm-offset candidates at saved lifted state.',
        'candidates':rows,'feasible_count':len(valid),'best':min(valid,key=lambda r:np.linalg.norm(r['palm_local_offset_m'])) if valid else None,
        'limitations':'Scratch first-contact acquisition only; does not establish force closure, viable approach path, dynamic retention or quality acceptance.',
        'dynamic_admission':False,'production_accepted':False}
c.write(E/'D_LIFTED_TRIPOD_STATIC_SEARCH.json',report);finish(report)
