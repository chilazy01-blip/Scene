import numpy as np
from .relative_grip_wrench import wrench,limit_update

def test_rigid_following_translation_has_no_false_damping_force():
    v=np.array([0.,0.,0.,.2,-.1,.04]);w=wrench(1.4715,.15,np.zeros(3),np.eye(3),np.array([.1,0,-.15]),np.eye(3),np.array([.1,0,-.15]),np.eye(3),v,v);np.testing.assert_allclose(w,[0,0,1.4715,0,0,0],atol=1e-15)

def test_rigid_following_rotation_has_no_false_damping_force():
    h=np.array([0.,0.,.3,0.,0.,0.]);r=np.array([.1,0,-.15]);c=h.copy();c[3:]=np.cross(h[:3],r);w=wrench(1.4715,.15,np.zeros(3),np.eye(3),r,np.eye(3),r,np.eye(3),h,c);np.testing.assert_allclose(w,[0,0,1.4715,0,0,0],atol=1e-15)

def test_reference_opening_is_slow_and_original_bounds_preserved():
    old=np.array([.3,-.3]);q=limit_update(old,[.1,-.1],np.array([.4,-.45]));np.testing.assert_allclose(q,[.299,-.299]);q=limit_update(old,[1.,-1.],np.array([.4,-.45]));np.testing.assert_allclose(q,[.306,-.306])
