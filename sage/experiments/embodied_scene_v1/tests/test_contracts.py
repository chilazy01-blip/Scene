import json
from pathlib import Path
import numpy as np
import pytest
from sage.experiments.embodied_scene_v1.package import rigid,bound,verify_binding
from sage.experiments.embodied_scene_v1.environment import SceneEnvironment


def test_reflections_and_scale_cannot_be_physical_pose():
    for scale in ([1,1,-1],[1,2,1]):
        a=np.eye(4);a[:3,:3]=np.diag(scale)
        with pytest.raises(ValueError):rigid(a)


def test_rotated_semantic_extents_do_not_sort_axes():
    r=np.array([[0,-1,0],[1,0,0],[0,0,1.]])
    a=np.eye(4);a[:3,:3]=r;a[:3,3]=[1,2,3]
    rigid(a)
    local=np.array([[0,0,0],[.03,.16,.24]])
    world=local@r.T+a[:3,3]
    recovered=(world-a[:3,3])@r
    np.testing.assert_allclose(np.ptp(recovered,axis=0),[.03,.16,.24],atol=1e-12)


def test_tampered_asset_binding_fails(tmp_path):
    p=tmp_path/'source';p.write_bytes(b'original');source=bound(p);p.write_bytes(b'changed')
    with pytest.raises(ValueError,match='hash mismatch'):verify_binding(source)


def test_reset_and_action_contract():
    import os
    episode=os.environ.get('EMBODIED_TEST_EPISODE')
    if not episode:pytest.skip('Requires guarded reference episode')
    env=SceneEnvironment(episode)
    try:
        a=env.reset();action=np.zeros(env.model.nu)
        if env.task['task']=='pick_place':
            action[env.model.actuator('gripper_finger_joint1').id]=.04
            action[env.model.actuator('gripper_finger_joint2').id]=-.04
        for _ in range(10):env.step(action)
        advanced=env.save();env.reset()
        for _ in range(10):env.step(action)
        np.testing.assert_array_equal(env.save(),advanced)
        np.testing.assert_array_equal(env.reset()['qpos'],a['qpos'])
        with pytest.raises(ValueError):env.step(np.full(env.model.nu,np.nan))
        with pytest.raises(ValueError):env.step(np.full(env.model.nu,1e9))
        with pytest.raises(ValueError):env.reset(seed=1)
        assert env.data.time==0
        if env.task.get('physics_only'):
            with pytest.raises(ValueError):env.render()
    finally:env.close()


def test_stretch_optical_frame_preserves_forward_and_centers():
    import os,mujoco
    from sage.experiments.embodied_scene_v1.cameras import canonicalize_stretch_cameras
    episode=os.environ.get('EMBODIED_NAV_EPISODE')
    if not episode:pytest.skip('Requires guarded navigation episode')
    p=Path(episode);m=mujoco.MjModel.from_binary_path(str(p/'model.mjb'));d=mujoco.MjData(m)
    reset=np.load(p/'reset_state.npz',allow_pickle=False)
    mujoco.mj_setState(m,d,reset['state'],mujoco.mjtState(int(reset['state_spec'])));mujoco.mj_forward(m,d)
    i=m.camera('camera_rgb').id;position=d.cam_xpos[i].copy();forward=-d.cam_xmat[i].reshape(3,3)[:,2].copy()
    canonicalize_stretch_cameras(m);mujoco.mj_forward(m,d)
    np.testing.assert_allclose(d.cam_xpos[i],position,atol=1e-12)
    np.testing.assert_allclose(-d.cam_xmat[i].reshape(3,3)[:,2],forward,atol=1e-12)
    assert d.cam_xmat[i].reshape(3,3)[2,1]>.98
