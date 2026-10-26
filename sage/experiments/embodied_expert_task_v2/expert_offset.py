"""A versioned feed-forward reference correction around an unmodified CPU WBC.

The original expert goals drive the WBC from real observations. A frozen,
independently checked pose correction is added once to every joint command,
including the waist and legs that the WBC overwrites in its upper-goal path.
This adapter makes no claim that reference geometry proves dynamics.
"""
from pathlib import Path
import numpy as np

def make_runtime(source,weights,session_factory=None):
    from humanoidmimicgen.dataset_playback import PlaybackConfig,ActionEnv
    from humanoidmimicgen.wbc_runtime import get_env,get_policies,get_robot_type_and_model
    import onnxruntime as ort
    c=PlaybackConfig.from_dict(source['config']);c.save_video=c.enable_onscreen=c.enable_offscreen=False;c.sim_frequency=200;c.action_source='wbc-goal'
    c.wbc_model_path=','.join(str(Path(weights[k]).resolve()) for k in ('stand','walk'))
    original=ort.InferenceSession
    def cpu_session(path,*args,**kwargs):
        options=ort.SessionOptions();options.intra_op_num_threads=options.inter_op_num_threads=1
        s=original(path,sess_options=options,providers=['CPUExecutionProvider'])
        if s.get_providers()!=['CPUExecutionProvider']:raise RuntimeError('CPU provider required')
        return session_factory(s) if session_factory else s
    ort.InferenceSession=cpu_session
    try:
        sync=get_env(c,onscreen=False,offscreen=False);kind,model=get_robot_type_and_model(c.robot,c.enable_waist);policy,_,_=get_policies(c,kind,model,activate_keyboard_listener=False)
    finally:ort.InferenceSession=original
    env=ActionEnv(sync,policy,default_base_height=c.controller_initial_base_height);env.reset(seed=source['seed']);env.reset_to(dict(states=source['arrays']['states'][0].copy()))
    return env,policy,model

def qpos_mapping(raw_model,robot_model):
    import mujoco
    mapping={}
    for j in range(raw_model.njnt):
        if raw_model.jnt_type[j]!=mujoco.mjtJoint.mjJNT_HINGE:continue
        name=mujoco.mj_id2name(raw_model,mujoco.mjtObj.mjOBJ_JOINT,j)
        for prefix in ('robot0_','gripper0_left_','gripper0_right_'):
            if name.startswith(prefix):name=name[len(prefix):];break
        index=robot_model.dof_index(name)
        if index in mapping:raise ValueError('ambiguous MuJoCo/Pinocchio joint map')
        mapping[index]=int(raw_model.jnt_qposadr[j])
    if sorted(mapping)!=list(range(43)) or robot_model.num_dofs!=43:raise ValueError('incomplete joint mapping')
    return np.asarray([mapping[i] for i in range(43)],dtype=int)

def source_goal(source,index):
    a=source['arrays']
    return dict(navigate_cmd=a['navigate'][index].copy(),base_height_command=a['height'][index].copy(),wrist_pose=a['wrist'][index].copy(),target_upper_body_pose=a['upper'][index].copy())

def apply_offset(action,offset):
    q=np.asarray(action['q']);delta=np.asarray(offset)
    if q.shape!=(43,) or delta.shape!=(43,) or not np.isfinite(q).all() or not np.isfinite(delta).all():raise ValueError('invalid joint command or correction')
    return dict(q=q.copy()+delta)
