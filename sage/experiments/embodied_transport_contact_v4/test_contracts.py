"""Compact phase is actual held motion, not a synthetic carry event/reset."""
from types import SimpleNamespace
import numpy as np
from .task import Task,ParentTask


def test_lift_transitions_to_real_tuck_before_walk(monkeypatch):
    t=object.__new__(Task);t.case={"task_mode":"full_transport"};t.compact_ready=False;t.world_path={"old":True}
    stages=[]
    monkeypatch.setattr(ParentTask,"transition",lambda self,stage,frame,metrics:stages.append(stage))
    t.transition("carry",500,{})
    assert stages==["tuck"] and t.world_path is None
    t.compact_ready=True;t.transition("carry",625,{})
    assert stages==["tuck","carry"]


def test_tuck_does_not_start_or_reseed_walk(monkeypatch):
    t=object.__new__(Task);t.stage="tuck"
    calls=[]
    monkeypatch.setattr(ParentTask,"begin_carry",lambda *args:calls.append(args))
    t.begin_carry(500,SimpleNamespace())
    assert not calls


def test_tuck_fingers_stay_closed():
    t=object.__new__(Task);t.stage="tuck";t.stage_start=0;t.case={"ready_fraction":.45}
    assert t.hand_fraction(50)==1.
