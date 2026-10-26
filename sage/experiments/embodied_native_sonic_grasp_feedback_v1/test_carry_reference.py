import numpy as np
from scipy.spatial.transform import Rotation
from .carry_reference import capture,targets

def quat(e):
    q=Rotation.from_euler('xyz',e).as_quat();return q[[3,0,1,2]]

def fixture():
    root=np.array([1.,2.,.76]);q=quat([.02,-.01,.3]);poses=[(np.array([1.2,1.7,1.03]),Rotation.from_euler('xyz',[.3,.5,.7]).as_matrix()),(np.array([.9,2.3,1.]),np.eye(3)),(np.array([1.,2.,1.4]),np.eye(3))];return root,q,poses,capture(root,q,poses)

def test_capture_is_continuous():
    root,q,poses,a=fixture()
    for (p,R),(p2,R2) in zip(poses,targets(a,root,q)):
        np.testing.assert_allclose(p,p2,atol=1e-15);np.testing.assert_allclose(R,R2,atol=1e-15)

def test_forward_walk_does_not_bounce_wrist_height():
    root,q,poses,a=fixture();shift=np.array([.25,-.03,.04]);got=targets(a,root+shift,q)
    for (p,R),(p2,R2) in zip(poses,got):
        np.testing.assert_allclose(p2[:2],p[:2]+shift[:2]);assert p2[2]==p[2];np.testing.assert_allclose(R2,R,atol=1e-15)

def test_base_tilt_does_not_rotate_cup_reference():
    root,q,poses,a=fixture();q2=quat([.1,-.08,.3])
    for (p,R),(p2,R2) in zip(poses,targets(a,root,q2)):
        np.testing.assert_allclose(p2,p,atol=1e-15);np.testing.assert_allclose(R2,R,atol=1e-15)
