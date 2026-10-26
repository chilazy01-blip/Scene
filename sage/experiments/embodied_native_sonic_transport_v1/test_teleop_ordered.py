"""Asymmetric reference checked against actual released CPP gatherer and header."""
import re
from pathlib import Path
import numpy as np
from .teleop_reference_ordered import blocks,LOWER_INDICES
from .teleop_reference import blocks as old_blocks
SRC=Path('/data/wsj/main/scene_runs/codex_trellis_v2/embodied_data_stability_sonic_readmission_20261018_v1/source/gear_sonic_deploy/src/g1/g1_deploy_onnx_ref')

def released_order():
    cpp=(SRC/'src/g1_deploy_onnx_ref.cpp').read_text()
    declaration=next(line for line in cpp.splitlines() if '{"motion_joint_positions_lowerbody_10frame_step5"' in line)
    assert 'lower_body_joint_mujoco_order_in_isaaclab_index' in declaration
    text=(SRC/'include/policy_parameters.hpp').read_text()
    name='lower_body_joint_mujoco_order_in_isaaclab_index'
    return np.array([int(x) for x in re.search(name+r'\s*=\s*\{([^}]+)',text).group(1).split(',')])

def inputs():
    q=np.zeros((60,36));q[:,3]=1
    q[:,7:]=np.arange(29)[None,:]+np.arange(60)[:,None]*100
    v=2*q[:,7:]+.125
    return q,v,0,[1,0,0,0],[1,0,0,0],np.zeros(3),np.zeros((3,3)),np.repeat(np.eye(3)[None,:,:],3,axis=0)

def test_actual_cpp_registry_order():
    np.testing.assert_array_equal(LOWER_INDICES,released_order())

def test_asymmetric_mujoco_horizon_positions_and_velocities():
    args=inputs();out=blocks(*args);f=np.arange(10)*5
    np.testing.assert_array_equal(out['motion_joint_positions_lowerbody_10frame_step5'].reshape(10,12),args[0][f,7:19])
    np.testing.assert_array_equal(out['motion_joint_velocities_lowerbody_10frame_step5'].reshape(10,12),args[1][f,:12])

def test_detects_original_symmetric_order_test_blindspot():
    args=inputs();new=blocks(*args);old=old_blocks(*args)
    assert not np.array_equal(new['motion_joint_positions_lowerbody_10frame_step5'],old['motion_joint_positions_lowerbody_10frame_step5'])
    for key in new:
        if 'lowerbody' not in key:np.testing.assert_array_equal(new[key],old[key])
