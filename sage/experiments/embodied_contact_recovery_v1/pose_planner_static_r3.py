"""Dry evaluation of the versioned D optimizer. No control execution."""
import numpy as np
import mujoco
from scipy.spatial.transform import Rotation

def solve(runner,geo,target_xy,cylinder_half=.037,allow_stance=False):
    from scipy.optimize import minimize
    m,d,ik=runner.model,runner.data,runner.ik
    palm,wrist=runner.palm_pose()
    relative_p=wrist.T@(runner.cyl_pos()-palm)
    relative_R=wrist.T@d.xmat[runner.cyl_bid].reshape(3,3)
    scratch=mujoco.MjData(m)
    scratch.qpos[:]=d.qpos
    scratch.qvel[:]=0
    base=d.qpos[:2].copy()
    seed=d.qpos[ik.qpos_idx].copy()
    goal=runner.cyl_pos().copy()
    goal[:2]=target_xy
    goal[2]=max(goal[2],geo['blue_top_z']+cylinder_half+.065)
    obj_yaw=np.arctan2(d.xmat[runner.cyl_bid].reshape(3,3)[1,0],d.xmat[runner.cyl_bid].reshape(3,3)[0,0])
    desired_R=Rotation.from_euler('z',obj_yaw).as_matrix()
    aids=np.asarray(ik.act_idx)
    dofs=np.asarray(ik.dof_idx)
    def fk(x):
        scratch.qpos[:]=d.qpos
        scratch.qpos[ik.qpos_idx]=x[:-2]
        scratch.qpos[:2]=base+x[-2:]
        mujoco.mj_kinematics(m,scratch)
        mujoco.mj_comPos(m,scratch)
        rw=scratch.site_xmat[ik.site_id].reshape(3,3)
        op=scratch.site_xpos[ik.site_id]+rw@relative_p
        return op,rw@relative_R,rw
    def cost(x):
        pos,rot,_=fk(x)
        orient=Rotation.from_matrix(desired_R@rot.T).as_rotvec()
        return 1500*np.sum((pos-goal)**2)+8*np.sum(orient**2)+.15*np.sum((x[:-2]-seed)**2)+20*np.sum(x[-2:]**2)
    def constraints(x):
        pos,rot,_=fk(x)
        # Measured full-body support envelope and static actuator feasibility.
        feet=np.array([scratch.xpos[m.body(side+'_ankle_roll_link').id,:2] for side in ['left','right']])
        com=scratch.subtree_com[m.body('pelvis').id,:2] if any(m.body(i).name=='pelvis' for i in range(m.nbody)) else scratch.subtree_com[1,:2]
        stability=np.r_[com-(feet.min(axis=0)-.07),feet.max(axis=0)+.07-com]
        obj_adr=int(m.jnt_qposadr[m.joint('red_block_joint').id])
        scratch.qpos[obj_adr:obj_adr+3]=pos
        quat=np.zeros(4);mujoco.mju_mat2Quat(quat,rot.ravel())
        scratch.qpos[obj_adr+3:obj_adr+7]=quat
        mujoco.mj_forward(m,scratch)
        collision_margin=1.
        for ct in scratch.contact:
            bodies=[m.body(int(m.geom_bodyid[g])).name for g in [ct.geom1,ct.geom2]]
            ground=any(m.geom(g).name=='ground' for g in [ct.geom1,ct.geom2])
            foot=any('ankle_roll' in b for b in bodies)
            held='red_block' in bodies and any('right_hand' in b for b in bodies)
            tolerance=.01 if ground and foot else (.008 if held else 0.)
            collision_margin=min(collision_margin,float(ct.dist)+tolerance)
        torque=np.minimum(scratch.qfrc_bias[dofs]-m.actuator_ctrlrange[aids,0],m.actuator_ctrlrange[aids,1]-scratch.qfrc_bias[dofs])
        table_clear=pos[2]-geo['blue_top_z']-cylinder_half-.02
        return np.r_[stability,torque,table_clear,rot[2,2]-np.cos(np.radians(5)),collision_margin]
    result=minimize(cost,np.r_[seed,0.,0.],method='SLSQP',
                    bounds=list(zip(ik.lo,ik.hi))+([(-.12,.12),(-.12,.12)] if allow_stance else [(0.,0.),(0.,0.)]),
                    constraints=[{'type':'ineq','fun':constraints}],
                    options={'maxiter':65,'ftol':1e-7})
    pos,rot,planned_wrist=fk(result.x)
    valid=bool(result.success and np.min(constraints(result.x))>=-1e-5 and np.linalg.norm(pos-goal)<.025)
    return {'valid':valid,'variables':result.x.tolist(),'cost':float(result.fun),'iterations':int(result.nit),'message':str(result.message),'min_constraint':float(np.min(constraints(result.x))),'goal':goal.tolist(),'planned_object_position':pos.tolist(),'planned_object_rotation':rot.tolist(),'planned_wrist_rotation':planned_wrist.tolist(),'object_position_error_m':float(np.linalg.norm(pos-goal))}
