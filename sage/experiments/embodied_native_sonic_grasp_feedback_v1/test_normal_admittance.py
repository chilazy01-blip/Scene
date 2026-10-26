import numpy as np
from .normal_admittance import update

def test_persistent_reference_overcomes_static_deadband_without_current_q_reset():
    c=f=0.
    for i in range(400):
        force=max(0.,50*(c-.30-.04));old=c;c,f=update(c,f,force,1.,1.5)
        assert 0<=c<=.5 and abs(c-old)*1.5<=.00600000001
    assert abs(force-1.)<.06 and c>.34

def test_force_disturbance_recovers_and_unloads_without_changing_PD():
    c=.36;f=1.
    for i in range(500):
        shift=.03 if 100<=i<250 else 0.;force=max(0.,80*(c-.34-shift));c,f=update(c,f,force,1.5,1.5)
    assert abs(force-1.5)<.06

def test_force_request_rejects_invalid_values():
    import pytest
    with pytest.raises(ValueError):update(0,0,-1,1,1.5)
