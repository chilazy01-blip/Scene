"""Official teleop coordinate and mode-mask semantics, no integration."""
import numpy as np
from scipy.spatial.transform import Rotation
from .teleop_reference import root_normalize,blocks,LOWER_INDICES,LEFT_OFFSET,RIGHT_OFFSET


def test_root_frame_positions_quaternions_and_order():
    rotation=Rotation.from_euler('z',90,degrees=True).as_matrix();root=np.array([2.,3.,.8])
    local=np.array([[.2,.3,.4],[.4,-.3,.2],[0,0,.5]])
    world=local@rotation.T+root
    positions,quats=root_normalize(world,np.repeat(rotation[None],3,axis=0),root,np.array([2**-.5,0,0,2**-.5]))
    assert np.allclose(positions.reshape(3,3),local)
    assert np.allclose(quats.reshape(3,4),[[1,0,0,0]]*3)


def test_teleop_masks_and_lower_joint_order():
    q=np.zeros((100,36));q[:,3]=1;q[:,7:]=np.arange(29);v=np.zeros((100,29))
    result=blocks(q,v,0,[1,0,0,0],[1,0,0,0],[0,0,0],[[1,2,3],[4,5,6],[7,8,9]],np.repeat(np.eye(3)[None],3,axis=0))
    assert result['encoder_mode_4'].tolist()==[1,0,0,0]
    assert np.all(result['motion_joint_positions_10frame_step5']==0)
    assert np.all(result['smpl_joints_10frame_step1']==0)
    assert result['motion_joint_positions_lowerbody_10frame_step5'].reshape(10,12)[0].tolist()==[0,6,1,7,2,8,3,9,4,10,5,11]
    assert result['vr_3point_local_target'].tolist()==[1,2,3,4,5,6,7,8,9]


def test_official_asymmetric_wrist_offsets():
    assert LEFT_OFFSET.tolist()==[.18,-.025,0.]
    assert RIGHT_OFFSET.tolist()==[.18,.025,0.]
