"""Retain qualified arc, otherwise time-parameterize bounded collision-clear paths."""
import numpy as np,mujoco
from .tripod_clearance_arc_r2 import plan_arc as original_plan
from .planned_tripod_r2 import FINGER_NAMES,forbidden_robot_contacts,hand_contacts
from .safe_approach_r3 import hand_bounds

def plan_arc(runner,grasp,height=.02):
 original=original_plan(runner,grasp,height)
 finger0=np.asarray(grasp['initial_finger_rad']);finger1=np.asarray(grasp['finger_target_rad'])
 if original['valid']:
  return {**original,'finger_path_rad':[(finger0+t*(finger1-finger0)).tolist() for t in original['fractions']],'timing_optimized':False,'finger_delay_fraction':0.}
 m,live,ik=runner.model,runner.data,runner.ik;q0=live.qpos.copy();d=mujoco.MjData(m);fa=np.array([m.jnt_qposadr[m.joint('right_hand_'+n+'_joint').id] for n in FINGER_NAMES]);table=m.geom('table_top').id;top=float(live.geom_xpos[table,2]+m.geom_size[table,2]);attempts=[]
 for arc_height in [height,.03,.01]:
  base=original if arc_height==height else original_plan(runner,grasp,arc_height)
  space=np.asarray(base['fractions']);arms=np.asarray(base['arm_path_rad'])
  for delay in [0.,.1,.2]:
   phase=np.clip((space-delay)/(1.-delay),0.,1.);fingers=finger0+phase[:,None]*(finger1-finger0)
   segment=np.maximum(np.max(abs(np.diff(arms,axis=0)),axis=1),np.max(abs(np.diff(fingers,axis=0)),axis=1))/.18
   duration=float(sum(segment));timeknots=np.r_[0.,np.cumsum(segment)]/max(duration,1e-12);bad=[];gaps=[];peak=0.
   for t in np.linspace(0.,1.,201):
    d.qpos[:]=q0;d.qvel[:]=0.;d.qpos[ik.qpos_idx]=[np.interp(t,space,arms[:,j]) for j in range(7)];d.qpos[fa]=[np.interp(t,space,fingers[:,j]) for j in range(7)];mujoco.mj_forward(m,d)
    forbidden=forbidden_robot_contacts(m,d,runner.cyl_bid)
    if forbidden:bad.append({'fraction':float(t),'pairs':forbidden})
    lo,_=hand_bounds(m,d);gaps.append(float(lo[2]-top));contacts,_=hand_contacts(m,d,runner.cyl_bid);peak=max(peak,max([-float(x.dist) for x in contacts],default=0.))
   valid=not bad and min(gaps)>=.006 and peak<=.002 and max(x[0] for x in base['ik_errors'])<=.003 and max(x[1] for x in base['ik_errors'])<=1. and duration<=5.8
   brief={'arch_height_m':arc_height,'finger_delay_fraction':delay,'required_duration_s':duration,'minimum_hand_table_vertical_clearance_m':min(gaps),'max_hand_object_penetration_m':peak,'forbidden_count':len(bad),'valid':valid};attempts.append(brief)
   if valid:
    assert np.array_equal(q0,live.qpos)
    return {**base,**brief,'fractions':timeknots.tolist(),'geometric_fractions':space.tolist(),'finger_path_rad':fingers.tolist(),'path_forbidden':bad,'timing_optimized':True,'bounded_joint_speed_rad_s':.18,'search_attempts':attempts}
 return {**original,'valid':False,'timing_optimized':False,'search_attempts':attempts,'failure_reason':'No bounded timing/closure-delay candidate meets unchanged clearance,penetration,6.5s acquisition constraints.'}
