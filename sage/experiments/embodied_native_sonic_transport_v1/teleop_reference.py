"""Official mode1 lower-body + root-normalized wrist/head target encoder blocks."""
import numpy as np
from scipy.spatial.transform import Rotation
from sage.experiments.embodied_data_stability_v1.sonic_semantic_shadow import ENCODER_BLOCKS
from sage.experiments.embodied_data_stability_v1.sonic_offline_observation_mapper import reorder_mujoco_to_isaaclab,MUJOCO_TO_ISAACLAB
from sage.experiments.embodied_data_stability_v1 import sonic_native_dynamic_shadow as native

LEFT_OFFSET=np.array([.18,-.025,0.]);RIGHT_OFFSET=np.array([.18,.025,0.]);HEAD_OFFSET=np.array([0.,0.,.35])
LOWER_INDICES=np.flatnonzero(np.asarray(MUJOCO_TO_ISAACLAB)<12)


def root_normalize(points,rotations,root_position,root_quat_wxyz):
    q=np.asarray(root_quat_wxyz);root=Rotation.from_quat(q[[1,2,3,0]]).as_matrix()
    local=(np.asarray(points)-root_position)@root
    quats=[]
    for orientation in rotations:
        scalar_last=Rotation.from_matrix(root.T@orientation).as_quat()
        wxyz=scalar_last[[3,0,1,2]]
        if wxyz[0]<0:wxyz=-wxyz
        quats.append(wxyz)
    return local.reshape(-1),np.asarray(quats).reshape(-1)


def blocks(reference,velocity,index,initial_quaternion,current_quaternion,root_position,points,rotations):
    g1=native.build_dynamic_g1_encoder_blocks(reference,velocity,index,
        initial_robot_quaternion_wxyz=initial_quaternion,current_robot_quaternion_wxyz=current_quaternion)
    result={b.name:np.zeros(b.dimension) for b in ENCODER_BLOCKS}
    result['encoder_mode_4']=np.array([1.,0.,0.,0.])
    result['motion_anchor_orientation_heading']=g1['motion_anchor_orientation_heading_10frame_step5'][:6].copy()
    future=index+np.arange(10)*5
    result['motion_joint_positions_lowerbody_10frame_step5']=reorder_mujoco_to_isaaclab(reference[future,7:])[:,LOWER_INDICES].reshape(-1)
    result['motion_joint_velocities_lowerbody_10frame_step5']=reorder_mujoco_to_isaaclab(velocity[future])[:,LOWER_INDICES].reshape(-1)
    result['vr_3point_local_target'],result['vr_3point_local_orn_target']=root_normalize(points,rotations,np.asarray(root_position),current_quaternion)
    return result
