import numpy as np
from .impedance import update

def test_friction_reaction_is_compensated_without_velocity_cancellation():
    q=np.array([.1]);kp=np.array([1.5]);desired=np.array([.12]);friction=np.array([-.1]);target=q.copy();I=np.zeros(1);est=friction.copy()
    for _ in range(30):target,I,est,m=update(target,q,I,est,desired,desired,np.zeros(1),friction,kp,np.array([0.]),np.array([.5]))
    assert np.allclose(kp*(target-q)+friction,desired)
    v=.2;assert np.allclose(kp*(target-q)-.1*v+friction,desired-.1*v)
def test_fixed_anchor_does_not_follow_measured_joint_position():
    q=np.array([.1]);r,I,f,m=update(q,q,np.zeros(1),np.zeros(1),np.zeros(1),np.zeros(1),np.zeros(1),np.zeros(1),np.array([1.5]),np.zeros(1),np.ones(1));assert np.array_equal(r,q)
    assert 1.5*(r-.12)<0

def test_rate_limit_and_target_envelope_are_preserved():
    r,I,f,m=update(np.array([.1]),np.array([.1]),np.zeros(1),np.zeros(1),np.array([10.]),np.array([0.]),np.zeros(1),np.zeros(1),np.ones(1),np.zeros(1),np.array([.5]));assert r[0] == .10600000000000001 and I[0]==0
