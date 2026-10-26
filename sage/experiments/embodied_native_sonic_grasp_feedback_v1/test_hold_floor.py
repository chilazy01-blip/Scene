import numpy as np
import pytest
from .hold_floor import project

def test_loaded_unload_request_cannot_open_established_grip():
    old=dict(thumb=.4,index=.23,middle=.33);floor=old.copy()
    for _ in range(30):
        out=project(old,{g:v-.004 for g,v in old.items()},floor)
        assert out==old
        old=out;floor=out.copy()

def test_closing_reacquisition_retains_native_rate_and_envelope():
    old=dict(thumb=.49,index=.49,middle=.49)
    for _ in range(10):
        out=project(old,{g:.7 for g in old},old)
        assert all(old[g]<=out[g]<=.5 and (out[g]-old[g])*1.5<=.00600000001 for g in old)
        old=out
    assert all(x==.5 for x in old.values())

def test_cannot_inject_a_floor_ahead_of_actual_reference():
    with pytest.raises(ValueError):project(dict(thumb=.2,index=.2,middle=.2),dict(thumb=.3,index=.3,middle=.3),dict(thumb=.3,index=.2,middle=.2))
