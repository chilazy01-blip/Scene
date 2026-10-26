import numpy as np
from .feedback import advance

def test_held_equilibrium_preserves_position_stiffness_and_velocity_damping():
    kp=np.array([2.,1.5]);kd=.1;reference=np.array([.2,-.3]);target=advance(reference,[.1,-.2],[.1,-.2],kp,[-.5,-.5],[.5,.5]);assert np.array_equal(target,reference)
    q=np.array([.1,-.1]);v=np.array([.02,-.03]);tau=kp*(target-q)-kd*v;dq=np.array([.001,-.002]);dv=np.array([.01,.02]);assert np.allclose((kp*(target-q-dq)-kd*(v+dv))-tau,-kp*dq-kd*dv,atol=1e-14)
def test_measured_contact_error_changes_persistent_target_in_correct_direction():
    a=advance([.2,-.2],[.2,-.2],[.1,-.1],[2.,2.],[-.5,-.5],[.5,.5]);assert a[0]>.2 and a[1]<-.2
    b=advance(a,[.1,-.1],[.1,-.1],[2.,2.],[-.5,-.5],[.5,.5]);assert np.array_equal(a,b)
def test_native_target_envelope_and_bounded_rate_hold():
    a=advance([.499,-.499],[100.,-100.],[0.,0.],[1.5,1.5],[-.5,-.5],[.5,.5]);assert np.array_equal(a,[.5,-.5])
    a=advance([0.,0.],[100.,-100.],[0.,0.],[1.5,1.5],[-.5,-.5],[.5,.5]);assert np.array_equal(a,[.006,-.006])
