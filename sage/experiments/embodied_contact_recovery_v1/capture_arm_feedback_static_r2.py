"""Check a bounded measured palm correction before another capture diagnostic."""
import os,sys
from pathlib import Path
import numpy as np,h5py,mujoco
from .work import E,R,c,finish
from .planned_tripod_world_offset import contact_geometry,forbidden_robot_contacts
from .tripod_recontact import plan_recontact

def main(config):
 cfg=c.read(config);work=Path(os.environ['CONTINUOUS_JOB_DIR']);os.environ.update(NP_ROOT=str(R),NP_JOB=str(work));sys.path.insert(0,str(R/'tools'));sys.path.insert(0,str(R/'branches/A/source'))
 from .target_adapter_r4 import install
 install('A','gain_translation',work/'static_interface')
 import run
 from ik.sim import ArmIK6
 source=E/'jobs'/cfg['source_job'];folder=source/'episode';m=mujoco.MjModel.from_binary_path(str(folder/'MODEL.mjb'));d=mujoco.MjData(m);scratch=mujoco.MjData(m)
 ctrl=run.G1Controller(m,d,None,None,None,c.read(R/'branches/A/source/model_config.json'));ik=ArmIK6(m,ctrl);obj=m.body('red_block').id
 plan=c.read(source/'MEASURED_TRIPOD_PLAN.json')
 with h5py.File(folder/'TRACE.h5','r') as f:q0=f['substep/qpos'][0];q=f['substep/qpos'][-1]
 scratch.qpos[:]=q0;scratch.qpos[ik.qpos_idx]=plan['arm_target_rad'];mujoco.mj_forward(m,scratch);goal=scratch.site_xpos[ik.site_id].copy();wrist=scratch.site_xmat[ik.site_id].reshape(3,3).copy()
 d.qpos[:]=q;d.qvel[:]=0;mujoco.mj_forward(m,d);error=goal-d.site_xpos[ik.site_id];arm,resid,rr=ik.solve(d,goal,wrist,iters=100)
 correction=np.clip(np.asarray(plan['arm_target_rad'])-q[ik.qpos_idx],-.02,.02);command=arm+float(cfg.get('tracking_correction_fraction',1.))*correction;bad=[];peak=0.
 for t in np.linspace(0,1,41):
  scratch.qpos[:]=q;scratch.qpos[ik.qpos_idx]=(1-t)*q[ik.qpos_idx]+t*command;scratch.qvel[:]=0;mujoco.mj_forward(m,scratch);bad.extend(forbidden_robot_contacts(m,scratch,obj));peak=max(peak,contact_geometry(m,scratch,obj)['maximum_object_penetration_m'])
 repair=plan_recontact(m,scratch,obj,maximum_joint_increment=float(cfg.get('maximum_joint_increment_rad',.12)))
 report={'valid':bool(resid<.003 and rr<1 and not bad and peak<=.002 and repair['valid']),'palm_position_error_m':error.tolist(),'palm_error_norm_m':float(np.linalg.norm(error)),'arm_ik_residual_m':resid,'arm_ik_rotation_deg':rr,'command_delta_rad':(command-np.asarray(plan['arm_target_rad'])).tolist(),'arm_command':command.tolist(),'goal_position':goal.tolist(),'goal_rotation':wrist.tolist(),'tracking_correction_rad':correction.tolist(),'path_forbidden':bad,'path_max_penetration_m':peak,'endpoint_retarget':repair,'new_physics_steps':0,'production_accepted':False}
 c.write(E/cfg['output'],report);finish(report)
if __name__=='__main__':main(sys.argv[1])
