import numpy as np
import pytest
from .rate_adapter import project_target


def test_mode_handoff_limits_instead_of_rejecting():
    target=np.linspace(-2,2,29);previous=np.zeros(29)
    legal,guard=project_target(target,previous,np.full(29,-1.),np.full(29,1.),.25,True)
    assert np.array_equal(legal,np.clip(target,-.25,.25))
    assert guard['maximum_step_rad']<=.25 and guard['slew_limited_joints']


def test_old_prefix_semantics_remain_unchanged():
    with pytest.raises(ValueError,match='slew'):project_target([1.],[0.],[-1.],[1.],.25,False)


def test_actual_clamped_commands_are_next_history():
    previous=np.zeros(29);target=np.ones(29)
    for _ in range(4):previous,_=project_target(target,previous,np.full(29,-1.),np.full(29,1.),.25,True)
    assert np.array_equal(previous,target)
