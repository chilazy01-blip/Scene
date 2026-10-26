import numpy as np
from .carry_reference import capture
from .steady_carry_reference import targets
from .test_carry_reference import fixture,quat

def test_handoff_does_not_jump():
    root,q,poses,a=fixture();p,R=targets(a,root,q)[0];np.testing.assert_allclose(p,poses[0][0],atol=1e-15);np.testing.assert_allclose(R,poses[0][1],atol=1e-15)

def test_base_yaw_shake_does_not_move_or_rotate_carrying_wrist():
    root,q,poses,a=fixture();p,R=targets(a,root,quat([.08,-.1,.6]))[0];np.testing.assert_allclose(p,poses[0][0],atol=1e-15);np.testing.assert_allclose(R,poses[0][1],atol=1e-15)

def test_base_translation_is_followed_without_height_bounce():
    root,q,poses,a=fixture();shift=np.array([.3,-.02,.03]);p,R=targets(a,root+shift,quat([.08,-.1,.6]))[0];np.testing.assert_allclose(p[:2],poses[0][0][:2]+shift[:2]);assert p[2]==poses[0][0][2];np.testing.assert_allclose(R,poses[0][1],atol=1e-15)
