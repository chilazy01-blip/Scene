from types import SimpleNamespace
import numpy as np
import pytest
from .task_brake import should_brake

@pytest.mark.parametrize('distance,cycles,failure,stage,expected',[(.249,{'left':1,'right':1},None,'carry',False),(.251,{'left':1,'right':0},None,'carry',False),(.251,{'left':1,'right':1},'object_slipped','carry',False),(.251,{'left':1,'right':1},None,'target_stop',False),(.251,{'left':1,'right':1},None,'carry',True)])
def test_actual_distance_both_foot_cycles_and_no_failure_required(distance,cycles,failure,stage,expected):
    task=SimpleNamespace(stage=stage,failure=failure,carry_origin=np.array([1.8,2.5]),carry_cycles=cycles)
    assert should_brake(task,SimpleNamespace(qpos=np.array([1.8+distance,2.5])))==expected
