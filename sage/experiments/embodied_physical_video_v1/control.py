"""Direct, logged MuJoCo actuators and the pinned native lower-body policy."""
import numpy as np, mujoco
from .runtime import *
from sage.experiments.embodied_expert_task_v1.source_demo import load_demo
from sage.experiments.embodied_fb2_repair_v1.torque_audit import TorqueAudit

def load():
    s=load_demo(E/'human_box_table_to_shelf.hdf5')
    c=read(J/'results/B1/CONTRACT.json')
    m=mujoco.MjModel.from_binary_path(str(J/'results/B1/MODEL.mjb'))
    assert digest(J/'results/B1/MODEL.mjb')=='2fa50568ee499101f7a3f5d015c710789529c37c0562004c6856390de196f338'
    d=mujoco.MjData(m);d.time=s['arrays']['states'][0,0]
    d.qpos[:]=s['arrays']['states'][0,1:58];d.qvel[:]=s['arrays']['states'][0,58:]
    mujoco.mj_forward(m,d)
    return m,d,s,c,TorqueAudit(m,c['qpos_by_pin'],c['inspection'])

def make_policy(s):
    from humanoidmimicgen.dataset_playback import PlaybackConfig
    from humanoidmimicgen.wbc_runtime import get_policies,get_robot_type_and_model
    import onnxruntime as ort
    cfg=PlaybackConfig.from_dict(s['config'])
    w=read(E/'WEIGHTS.json')
    for v in w.values():assert digest(v['path'])==v['sha256']
    cfg.wbc_model_path=','.join(w[k]['path'] for k in ('stand','walk'))
    typ,robot=get_robot_type_and_model(cfg.robot,cfg.enable_waist)
    old=ort.InferenceSession;captures=[]
    class Session:
        def __init__(self,p):
            opts=ort.SessionOptions();opts.intra_op_num_threads=opts.inter_op_num_threads=1
            self.session=old(p,sess_options=opts,providers=['CPUExecutionProvider'])
            self.path=p
        def __getattr__(self,n):return getattr(self.session,n)
        def run(self,names,inputs,*args,**kw):
            charge(wbc_forwards=1)
            result=self.session.run(names,inputs,*args,**kw)
            captures.append((self.path,np.array(next(iter(inputs.values())),copy=True),np.array(result[0],copy=True)))
            return result
    ort.InferenceSession=lambda p,*a,**kw:Session(p)
    try:policy,_,_=get_policies(cfg,typ,robot,activate_keyboard_listener=False)
    finally:ort.InferenceSession=old
    return policy,robot,captures

def observation(d,qmap):
    return dict(q=d.qpos[qmap].astype('f4').astype('f8'),
                dq=d.qvel[qmap-1].astype('f4').astype('f8'),
                floating_base_pose=d.qpos[:7].copy(),floating_base_vel=d.qvel[:6].copy())

def policy_action(policy,robot,d,qmap,goal,synchronize=True):
    obs=observation(d,qmap)
    if synchronize:
        policy.set_goal(goal)
        # The stock adapter builds the observation before setting height/torso.
        # Fill those commands first so history describes this control tick.
        low=policy.lower_body_policy
        low.height_cmd=goal['base_height_command']
        q=np.zeros(robot.num_dofs);q[robot.get_joint_group_indices('upper_body')]=goal['target_upper_body_pose']
        robot.cache_forward_kinematics(q,auto_clip=False)
        from pinocchio import rpy
        torso=robot.frame_placement('torso_link').rotation
        pelvis=robot.frame_placement('pelvis').rotation
        yaw=np.arctan2(pelvis[1,0],pelvis[0,0])
        roll,pitch,yaw=rpy.matrixToRpy(rpy.rpyToMatrix(0,0,yaw).T@torso)
        low.roll_cmd,low.pitch_cmd,low.yaw_cmd=roll,pitch,yaw
        policy.set_observation(obs)
    else:
        policy.set_observation(obs);policy.set_goal(goal)
    return policy.get_action()['q'].copy()
