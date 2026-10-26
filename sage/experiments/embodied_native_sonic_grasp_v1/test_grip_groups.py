import numpy as np
import pytest
from .grip_groups import advance,targets,secure


def test_loaded_middle_pauses_while_thumb_and_index_catch_up():
    r=advance(dict(thumb=.1,index=.1,middle=.1),dict(thumb=0,index=0,middle=2))
    assert r==pytest.approx(dict(thumb=.104,index=.104,middle=.1))

def test_native_bounded_reference_and_full_release():
    r=advance(dict(thumb=.5,index=.5,middle=.5),dict(thumb=0,index=0,middle=0))
    assert r==dict(thumb=.5,index=.5,middle=.5)
    names=['left_hand_thumb_0_joint','right_hand_thumb_0_joint','right_hand_index_0_joint']
    assert targets(names,r)==[0,.4,.7]
    assert targets(names,r,0)==[0,0,0]

def test_strong_opposing_contacts_not_near_zero_false_grip():
    assert not secure(dict(thumb=.01,index=0,middle=.01))
    assert secure(dict(thumb=1,index=0,middle=1))

def test_nonfinite_contact_rejected():
    with pytest.raises(ValueError):advance(dict(thumb=0,index=0,middle=0),dict(thumb=np.nan,index=0,middle=0))
