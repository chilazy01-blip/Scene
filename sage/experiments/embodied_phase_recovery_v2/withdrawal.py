"""Feedback reference for an explicit post-release actual-joint goal."""
import numpy as np
import mujoco
from sage.experiments.embodied_collision_expert_v2.planner_interior import collision_roles

def reference(context,previous,desired_actual,hand):
    c=context;arm=np.array([r['pin'] for r in c.rows if r['group']=='upper'])
    residual=c.d.qpos[c.qpos]-previous;ref=previous.copy()
    ref[arm]=np.clip(desired_actual[arm]-residual[arm],np.maximum(c.lower[arm],previous[arm]-.02),np.minimum(c.upper[arm],previous[arm]+.02));ref[c.hand]=hand[c.hand]
    c.validate(ref);pred=c.d.qpos.copy();pred[c.qpos[arm]]=ref[arm]+residual[arm];pred[c.qpos[c.hand]]=ref[c.hand]+residual[c.hand]
    d=mujoco.MjData(c.m);d.qpos[:]=pred;bad,_=collision_roles(c,d,False)
    goal_data=mujoco.MjData(c.m);goal_data.qpos[:]=c.d.qpos;goal_data.qpos[c.qpos[arm]]=desired_actual[arm];mujoco.mj_kinematics(c.m,goal_data)
    goals=[goal_data.geom_xpos[c.m.geom('gripper0_'+s+'_g0_col').id].copy() for s in ['left','right']]
    errors=[float(np.linalg.norm(d.geom_xpos[c.m.geom('gripper0_'+s+'_g0_col').id]-goals[i])) for i,s in enumerate(['left','right'])]
    return ref,pred,goals,dict(position_errors_m=errors,bad=bad,reference_slew=float(np.max(abs(ref[arm]-previous[arm]))))

def motion_ticks(start,goal,arm):
    ticks=max(275,int(np.ceil(1.5*max(abs(goal[arm]-start[arm]))/.02)))
    if ticks>424:raise ValueError('withdrawal_exceeds_phase_budget')
    return ticks

def interpolate(start,goal,tick,ticks,arm):
    f=min(1.,max(0.,tick/(ticks-1)));f=f*f*(3-2*f);q=start.copy();q[arm]=(1-f)*start[arm]+f*goal[arm];return q
