import pytest
from .index_reserve_control import advance

def test_small_spare_joint_range_is_never_expanded():
    x=0.
    for _ in range(100):
        old=x;x=advance(x,.6767107015986942,0.,1.5,.7);assert x-old<=.006+1e-12
    assert x==pytest.approx(.02328929840130578)

def test_force_rebound_does_not_open_loaded_finger():
    assert advance(.02,.6767107015986942,3.,1.5,.7)==.02

def test_invalid_base_reference_is_rejected():
    with pytest.raises(ValueError):advance(0.,.701,1.,1.5,.7)
