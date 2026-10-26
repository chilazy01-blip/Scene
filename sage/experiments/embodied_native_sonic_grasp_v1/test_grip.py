import numpy as np
import pytest
from .grip import preload,secure


def f(thumb=0,index=0,middle=0):return dict(thumb=thumb,index=index,middle=middle)

def test_weak_support_grows_bounded_reference_and_strong_support_holds():
    assert preload(.3,f(),.02)==pytest.approx(.302)
    assert preload(.3,f(3,1,2),.02)==.3
    assert preload(.4999,f(),.02)==.5

def test_requires_actual_thumb_and_index_contacts_before_lift():
    assert not secure(f(.01,0,.01))
    assert not secure(f(3,0,3))
    assert secure(f(1,.1,.9))

def test_rejects_nonfinite_reference():
    with pytest.raises(ValueError):preload(np.nan,f(),.02)
