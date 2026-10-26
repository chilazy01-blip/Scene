"""Bounded palm/reference replanning in scratch before acquisition, never after lift."""
import numpy as np,mujoco
from .planned_tripod_world_offset import contact_geometry,forbidden_robot_contacts
from .tripod_recontact import plan_recontact

def replan(runner,goal,wrist):
 m,d,ik=runner.model,runner.data,runner.ik;q=d.qpos.copy()
 arm,resid,rr=ik.solve(d,goal,wrist,iters=100)
 target=arm+.5*np.clip(runner.q_cmd-q[ik.qpos_idx],-.02,.02)
 scratch=mujoco.MjData(m);bad=[];pen=0.
 for t in np.linspace(0.,1.,41):
  scratch.qpos[:]=q;scratch.qvel[:]=0;scratch.qpos[ik.qpos_idx]=(1-t)*q[ik.qpos_idx]+t*target;mujoco.mj_forward(m,scratch)
  bad.extend(forbidden_robot_contacts(m,scratch,runner.cyl_bid));pen=max(pen,contact_geometry(m,scratch,runner.cyl_bid)['maximum_object_penetration_m'])
 repair=plan_recontact(m,scratch,runner.cyl_bid,maximum_joint_increment=.18)
 valid=resid<.003 and rr<1. and not bad and pen<=.002 and repair['valid'] and np.max(abs(target-runner.q_cmd))<=.045
 assert np.array_equal(q,d.qpos)
 return {'valid':bool(valid),'arm_target_rad':target.tolist(),'finger_repair':repair,'arm_ik_residual_m':resid,'rotation_error_deg':rr,'path_forbidden':bad,'path_max_penetration_m':pen,'no_live_state_write':True}
