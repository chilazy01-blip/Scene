import numpy as np
import pytest
from .task_fast import fast_update

@pytest.mark.parametrize('sign',[1.,-1.])
def test_contact_error_correction_is20percent_per_tick_below_rate_limit(sign):
    old=np.array([.2,-.2]);kp=np.array([2.,1.5]);error=sign*np.array([.01,-.01]);ends=np.array([.4,-.45])
    new=fast_update(old,error,np.zeros(2),kp,ends)
    assert np.allclose(kp*(new-old),.2*error,atol=1e-15)

def test_large_disturbance_retains_original_slew_and_bounds():
    ends=np.array([.4,-.45,-.75,.7,.75,.7,.75]);old=ends*.6;kp=np.array([2.,1.5,1.5,1.5,1.5,1.5,1.5])
    for direction in (np.sign(ends),-np.sign(ends)):
        new=fast_update(old,direction,np.zeros(7),kp,ends)
        assert np.max(np.abs(new-old))<=.006+1e-12
        assert np.all(new>=np.minimum(0,ends)) and np.all(new<=np.maximum(0,ends))
    assert np.array_equal(fast_update(ends,np.sign(ends),np.zeros(7),kp,ends),ends)

def test_zero_torque_error_preserves_reference():
    old=np.array([.2,-.3]);ends=np.array([.4,-.45]);assert np.array_equal(fast_update(old,[.1,.2],[.1,.2],[2,1.5],ends),old)
