import numpy as np
import pytest
from .task_joint import bounded_update

def test_asymmetric_opening_and_closing_limits():
    ends=np.array([.4,-.45,-.75,.7,.75,.7,.75]);old=ends*.6
    opened=bounded_update(old,old-np.sign(ends),ends)
    closed=bounded_update(old,old+np.sign(ends),ends)
    assert np.allclose(np.abs(opened-old),.0005)
    assert np.allclose(np.abs(closed-old),.006)
    assert np.all((opened-old)*ends<0) and np.all((closed-old)*ends>0)

def test_original_halfclosed_envelope_cannot_be_widened():
    ends=np.array([.4,-.45,-.75,.7,.75,.7,.75]);q=ends.copy()
    assert np.array_equal(bounded_update(q,q+np.sign(ends),ends),ends)
    q=np.zeros(7)
    assert np.array_equal(bounded_update(q,q-np.sign(ends),ends),q)
