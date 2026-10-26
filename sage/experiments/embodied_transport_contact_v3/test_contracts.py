"""Stopping change is high-level carry reference only, not command clipping."""
import numpy as np
from .task import Task, ParentTask


def make_task(walk_start):
    t=object.__new__(Task)
    t.walk_start=walk_start
    t.case={"carry_brake_duration_ticks":75,"task_mode":"full_transport"}
    t.q=np.zeros((2100,36));t.q[:,0]=np.arange(2100)*.007;t.q[:,2]=.78;t.q[:,3]=1
    t.v=np.zeros((2100,29));t.walk_start_pose=t.q[0].copy();t.reference_events=[]
    return t


def test_source_stop_stays55_and_carry_stop_uses75():
    source=make_task(0);source.brake(80)
    carry=make_task(100);carry.brake(180)
    assert source.stop_frame==135 and carry.stop_frame==255
    np.testing.assert_array_equal(carry.v[255:],0)
    assert carry.reference_events[-1]["duration"]==75


def test_world_lift_goal_expires_on_begin_carry(monkeypatch):
    t=make_task(0);t.world_path={"old_lift_goal":True}
    monkeypatch.setattr(ParentTask,"begin_carry",lambda self,frame,data:None)
    t.begin_carry(500,object())
    assert t.world_path is None
