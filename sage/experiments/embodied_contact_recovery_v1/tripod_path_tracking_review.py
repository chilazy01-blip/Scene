"""Separate actual base motion, arm tracking and finger path at forbidden contact."""
import sys
from pathlib import Path
import numpy as np,h5py,mujoco
from .work import E,R,c,finish
from .planned_tripod_r2 import FINGER_NAMES,forbidden_robot_contacts


def main(config_path):
    cfg=c.read(config_path);folder=Path(cfg['source_episode']);m=mujoco.MjModel.from_binary_path(str(folder/'MODEL.mjb'));d=mujoco.MjData(m);scratch=mujoco.MjData(m);planned=c.read(cfg['measured_plan']);names=c.read(R/'branches/A/source/model_config.json')['joint_names'];armnames=[n for n in names if n.startswith('right_') and 'hand' not in n and any(x in n for x in ['shoulder','elbow','wrist'])];aidx=[names.index(n) for n in armnames];qa=[m.jnt_qposadr[m.joint(n).id] for n in armnames];fa=[m.jnt_qposadr[m.joint('right_hand_'+n+'_joint').id] for n in FINGER_NAMES]
    records=[]
    with h5py.File(folder/'TRACE.h5','r') as f:
        n=len(f['substep/qpos']);initial=f['substep/qpos_before'][0] if 'substep/qpos_before' in f else None
        for k in sorted(set([0,max(0,n-161),max(0,n-81),max(0,n-17),n-1])):
            mujoco.mj_setState(m,d,f['substep/integration_before'][k],mujoco.mjtState.mjSTATE_INTEGRATION);mujoco.mj_forward(m,d)
            commanded=f['interpolation/requested'][k][aidx];tele=f['finger_governor/control'][k];desired=tele[:,4]
            pairs=forbidden_robot_contacts(m,d,m.body('red_block').id)
            scratch.qpos[:]=d.qpos;scratch.qvel[:]=0.;scratch.qpos[qa]=commanded;scratch.qpos[fa]=desired;mujoco.mj_forward(m,scratch)
            ideals=forbidden_robot_contacts(m,scratch,m.body('red_block').id)
            records.append({'row':k,'time':float(d.time),'base_pose':d.qpos[:7].tolist(),'actual_forbidden':pairs,'commanded_joint_pose_forbidden_at_actual_base':ideals,'arm_names':armnames,'arm_command_minus_actual_rad':(commanded-d.qpos[qa]).tolist(),'finger_desired_minus_actual_rad':(desired-d.qpos[fa]).tolist(),'finger_goal_rad':desired.tolist(),'palm_xyz':d.site_xpos[m.site('right_palm').id].tolist()})
    report={'new_physics_steps':0,'source_trace_sha256':c.sha(folder/'TRACE.h5'),'states':records,'production_accepted':False,'scope':'Read saved before-integration states and commanded-reference scratch poses; actual motion and body posture can invalidate nominal static paths.'};c.write(E/cfg['output'],report);finish(report)


if __name__=='__main__':main(sys.argv[1])
