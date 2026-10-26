from types import SimpleNamespace
import pytest
from .task_envelope import Task,extension_ready
from .task_fast import Task as FastTask
from . import native_envelope

@pytest.mark.parametrize('stage,age',[('lift',100),('loaded_hover',50),('tuck',60),('carry',0),('carry',39)])
def test_original_prefix_force_policy_delegated_exactly(monkeypatch,stage,age):
    calls=[];monkeypatch.setattr(FastTask,'force_update',lambda *args:calls.append(args))
    task=object.__new__(Task);task.stage=stage;task.walk_start=1000
    Task.force_update(task,1000+age,None,None)
    assert calls and calls[0][0] is task

def test_extension_starts_at_declared_loaded_phase_and_is_sticky():
    t=SimpleNamespace(stage='carry',walk_start=1360)
    assert not extension_ready(t,1399) and extension_ready(t,1400)
    t.stage='target_stop';t.native_envelope_enabled=True
    assert extension_ready(t,1500)

def test_half_envelope_solver_is_exact_original_delegate(monkeypatch):
    sentinel=object();monkeypatch.setattr(native_envelope,'original_allocate',lambda *a:sentinel)
    assert native_envelope.allocate(None,None,None,None,None,.5) is sentinel

@pytest.mark.parametrize('ratio',[.4,.7,float('nan')])
def test_no_undeclared_reference_envelope(ratio):
    with pytest.raises(ValueError):native_envelope.allocate(None,None,None,None,None,ratio)
