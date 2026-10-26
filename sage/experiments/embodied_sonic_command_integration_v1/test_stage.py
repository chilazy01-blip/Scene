"""Exercise the actual early/later stage boundary with distinct actual/desired poses."""
import numpy as np
import pytest
from types import SimpleNamespace
from .task_stage import Task

@pytest.mark.parametrize('tick',[1300,1361,1362,1450])
def test_tuck_holds_desired_before_and_after_old_absolute_gate(tick):
    task=object.__new__(Task);task.stage='tuck';task.events=[];task.joint_path='old'
    desired=np.array([2.,2.2,1.03]);R=np.eye(3)
    task.desired=lambda at:(desired.copy(),R.copy())
    calls=[];task.synchronize=lambda at,data,**kw:calls.append((at,kw))
    data=SimpleNamespace(qpos=np.array([1.8,2.5,.76]),xpos=np.array([[2.,2.2,1.018]]))
    before=data.qpos.copy()
    Task.move(task,tick,data,np.array([1.94,2.14,1.018]),R,60)
    assert np.array_equal(task.path['origin'],desired)
    assert np.array_equal(task.path['goal'],desired)
    assert np.array_equal(task.path['initial_R'],R) and np.array_equal(task.path['R'],R)
    assert task.path['duration']==60 and task.joint_path is None
    assert calls==[(tick,{'force':True})] and np.array_equal(data.qpos,before)
    assert task.events[-1]['hold_carry_preparation_pose']
