from types import SimpleNamespace
import numpy as np
import pytest
from .task_continuous import Task
from .task_joint import Task as JointTask

@pytest.mark.parametrize('stage,duration',[('place',65),('retract',40)])
def test_place_and_retract_keep_desired_origin_and_original_world_goal(stage,duration):
    task=object.__new__(Task);task.stage=stage;task.events=[];task.case={'target_object_xyz_m':[2.6,2.2,.787]};task.last_object_local=np.array([.15,.1,-.01]);task.grasp_R=np.array([[0,0,1],[1,0,0],[0,1,0]])
    desired=np.array([2.3,2.2,1.03]);task.desired=lambda t:(desired.copy(),np.eye(3));calls=[];task.synchronize=lambda *a,**kw:calls.append(kw)
    data=SimpleNamespace(xpos=np.array([[2.29,2.19,1.018]]));goal=np.array([2.1,2.2,1.1])
    Task.move(task,1700,data,goal,np.eye(3),120)
    assert np.array_equal(task.path['origin'],desired) and task.path['duration']==duration
    expected=np.asarray(task.case['target_object_xyz_m'])-task.grasp_R@task.last_object_local if stage=='place' else goal
    assert np.array_equal(task.path['goal'],expected) and np.array_equal(task.path['R'],task.grasp_R)
    assert calls==[{'force':True}]

def test_loaded_force_policy_is_exact_inherited_implementation():
    assert Task.force_update is JointTask.force_update

@pytest.mark.parametrize('stage',['initial_stand','preinsert','lift','loaded_hover','tuck','carry'])
def test_all_preplacement_moves_delegate_unchanged(monkeypatch,stage):
    calls=[];monkeypatch.setattr(JointTask,'move',lambda *args:calls.append(args))
    task=object.__new__(Task);task.stage=stage;data=object();goal=np.zeros(3);R=np.eye(3)
    Task.move(task,1301,data,goal,R,60)
    assert calls and calls[0][0] is task and calls[0][1:]==(1301,data,goal,R,60)
