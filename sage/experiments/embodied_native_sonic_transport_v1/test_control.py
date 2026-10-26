"""Ownership and reference semantics regression; no physical integrations."""
import numpy as np
import pytest
from .control import body_target,feedforward
from sage.experiments.embodied_data_stability_v1 import sonic_native_dynamic_shadow as native
from sage.experiments.embodied_data_stability_v1.sonic_semantic_shadow import ISAACLAB_TO_MUJOCO


def test_all29_targets_including_right_arm_are_sonic_outputs():
    target=np.linspace(-.3,.3,29)
    result,guard=body_target(target,np.zeros(29),np.full(29,-1.),np.full(29,1.),.6)
    assert np.array_equal(result,target)
    assert np.array_equal(result[22:29],target[22:29])
    assert guard['projected_joints']==[]


def test_only_original_legal_ranges_change_outputs():
    target=np.linspace(-.3,.3,29);target[22]=.55
    lo=np.full(29,-1.);hi=np.full(29,1.);hi[22]=.5
    result,guard=body_target(target,np.zeros(29),lo,hi,.6)
    assert result[22]==.5
    assert np.array_equal(result[np.arange(29)!=22],target[np.arange(29)!=22])
    assert guard['projected_joints']==[22]


def test_no_active_body_or_arm_gravity_override():
    bias=np.arange(29,dtype=float)
    assert np.array_equal(feedforward(bias,True),np.zeros(29))
    assert np.array_equal(feedforward(bias,False),bias)


def test_g1_reference_encoder_receives_arm_horizon():
    q=np.zeros((100,36));q[:,3]=1.;v=np.zeros((100,29))
    q[:,29:36]=np.arange(7)[None,:]*.1
    blocks=native.build_dynamic_g1_encoder_blocks(q,v,0,initial_robot_quaternion_wxyz=[1,0,0,0],current_robot_quaternion_wxyz=[1,0,0,0])
    expected=np.empty(29);expected[list(ISAACLAB_TO_MUJOCO)]=q[0,7:]
    assert np.array_equal(blocks['motion_joint_positions_10frame_step5'].reshape(10,29),np.repeat(expected[None,:],10,axis=0))
    assert np.count_nonzero(blocks['motion_joint_positions_10frame_step5'])>0
    assert np.count_nonzero(blocks['smpl_joints_10frame_step1'])==0


@pytest.mark.parametrize('x',[np.nan,np.inf,-np.inf])
def test_nonfinite_policy_output_rejected(x):
    target=np.zeros(29);target[25]=x
    with pytest.raises(ValueError,match='nonfinite'):body_target(target,np.zeros(29),np.full(29,-1.),np.full(29,1.),.6)
