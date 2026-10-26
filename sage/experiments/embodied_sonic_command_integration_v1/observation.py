"""Actual joint names, calibrated RGB and timestamps to official GR00T state groups."""
import math
import numpy as np
from scipy.spatial.transform import Rotation
from .contract import finite

def build_observation(contract,*,joint_names,joint_positions,base_quat_wxyz,images,image_time_s,state_time_s,now_s,prompt,camera_calibrated,left_hardware_coupling=False,max_age_s=.1):
    if not camera_calibrated:raise ValueError('GR00T camera calibration is not supplied')
    if len(joint_names)!=len(set(joint_names)) or set(joint_names)!=set(contract.state_names):raise ValueError('complete unique43 named joint state required')
    q=finite(joint_positions,(43,),'joint state');named=dict(zip(joint_names,q))
    if left_hardware_coupling:
        for dest,src in [(5,3),(6,4)]:named[contract.left_names[dest]]=named[contract.left_names[src]]
    if not all(math.isfinite(t) and 0<=now_s-t<=max_age_s for t in (image_time_s,state_time_s)):raise ValueError('stale camera or robot observation')
    if not math.isfinite(now_s) or not prompt:raise ValueError('current time and task prompt required')
    if 'ego_view' not in images:raise ValueError('ego_view RGB is required; no substitute image')
    video={}
    for name,key in [('ego_view','ego_view'),('left_wrist','left_wrist'),('right_wrist','wrist_view')]:
        if name not in images:continue
        image=np.asarray(images[name])
        if image.dtype!=np.uint8 or image.ndim!=3 or image.shape[-1]!=3 or min(image.shape[:2])<=0:raise ValueError('camera must supply uint8 HWC RGB')
        video[key]=image.copy()[None,None]
    quat=finite(base_quat_wxyz,(4,),'base quaternion')
    if abs(np.linalg.norm(quat)-1)>1e-3:raise ValueError('base quaternion must be normalized')
    gravity=Rotation.from_quat(quat[[1,2,3,0]]).inv().apply([0.,0.,-1.]).astype(np.float32)
    state={g:np.array([named[n] for n in names],dtype=np.float32)[None,None] for g,names in contract.groups.items()}
    state['projected_gravity']=gravity[None,None]
    return dict(video=video,state=state,language={'annotation.human.task_description':[[prompt]]},q=np.array([named[n] for n in contract.state_names],dtype=np.float32)[None,None],timestamps=image_time_s)
