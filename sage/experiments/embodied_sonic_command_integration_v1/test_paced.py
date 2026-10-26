import numpy as np
import pytest
from scipy.spatial.transform import Rotation
from .paced_reference import retime

def fixture():
    time=np.arange(100)*.02;q=np.zeros((100,36));q[:,:3]=time[:,None]*[.1,.2,.3];q[:,3:7]=Rotation.from_euler('z',time*.1).as_quat()[:,[3,0,1,2]]
    speed=np.arange(1,30)/100;q[:,7:]=time[:,None]*speed;v=np.tile(speed,(100,1))
    return q,v

def test_asymmetric_joint_values_and_velocity_time_scaling():
    q,v=fixture();a,b=retime(q,v,.65)
    assert len(a)>len(q)
    assert np.allclose(a[10,7:],q[0,7:]+.02*10*.65*v[0])
    assert np.allclose(b,v[0]*.65)
    assert np.allclose(a[0],q[0]) and np.allclose(a[-1],q[-1])
    assert np.allclose(np.linalg.norm(a[:,3:7],axis=1),1.)
    angle=Rotation.from_quat(a[10,[4,5,6,3]]).as_euler('xyz')[2]
    assert angle==pytest.approx(.02*10*.65*.1)

def test_identity_rate_preserves_whole_reference():
    q,v=fixture();a,b=retime(q,v,1.)
    assert np.allclose(a,q) and np.array_equal(b,v)

@pytest.mark.parametrize('rate',[0.,-1.,2.,np.nan])
def test_invalid_phase_rate_rejected(rate):
    with pytest.raises(ValueError):retime(*fixture(),rate)
