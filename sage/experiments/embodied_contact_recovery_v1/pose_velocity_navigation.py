"""Measured D carry navigation with proportional approach and no speed floor."""
import numpy as np


def velocity_request(qpos, goal_xy, goal_yaw):
    w,x,y,z=qpos[3:7]
    yaw=float(np.arctan2(2*(w*z+x*y),1-2*(y*y+z*z)))
    dx,dy=np.asarray(goal_xy)-qpos[:2]
    error=np.array([np.cos(yaw)*dx+np.sin(yaw)*dy,-np.sin(yaw)*dx+np.cos(yaw)*dy])
    turn=float(np.arctan2(np.sin(goal_yaw-yaw),np.cos(goal_yaw-yaw)))
    return np.array([2*error[0],2*error[1],np.clip(1.5*turn,-.6,.6)])


def walk_to(runner,goal_xy,goal_yaw=0.,timeout=30.,tol=.07):
    import instrument
    goal=np.asarray(goal_xy,float);tr=instrument.ACTIVE_TRACE
    for _ in range(int(round(timeout/runner.model.opt.timestep))):
        if runner.state['cs']%8==0:
            command=velocity_request(runner.data.qpos,goal,goal_yaw)
            runner.ctrl.lin_vel_x,runner.ctrl.lin_vel_y,runner.ctrl.ang_vel_z=map(float,command)
            tr.append('D_pose_navigation/physics_row',tr.n);tr.append('D_pose_navigation/goal',goal)
            tr.append('D_pose_navigation/requested',command)
        runner.step_once()
        if np.linalg.norm(goal-runner.data.qpos[:2])<tol:break
    runner.ctrl.lin_vel_x=runner.ctrl.lin_vel_y=runner.ctrl.ang_vel_z=0.
    runner.run(1.5)
    return float(np.linalg.norm(goal-runner.data.qpos[:2]))
