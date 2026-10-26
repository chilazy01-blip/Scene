"""Sequence regressions only; no claim of physical task success."""
from types import SimpleNamespace
from pathlib import Path
import numpy as np
from .task_v3 import Task
from .protocol import project_target as original_project
from .protocol_v3 import project_target


def fixture(stage):
    t = Task.__new__(Task)
    t.stage, t.start, t.done, t.failure = stage, 0, False, None
    t.case = {"stage_timeouts_ticks": {}, "source_object_xyz_m": [2.1,2.2,.787],
              "grasp_local_xyz_m": [.13,.07,-.04], "insertion_retreat_m": .1}
    t.stable, t.stop_frame, t.anchor = 14, 0, None
    t.calls = []
    def change(stage, tick, data, metrics):
        t.stage, t.start, t.stable = stage, tick, 0
        t.calls.append(stage)
    t.change = change
    t.walk = lambda *a: t.calls.append("walk")
    t.ready_arm = lambda *a: t.calls.append("raise")
    t.reached = lambda *a: True
    t.move = lambda *a: t.calls.append("reach")
    d = SimpleNamespace(qpos=np.zeros(57), qvel=np.zeros(55))
    return t, d, {"object_m": [2.1,2.2,.787]}


def test_walk_before_raise():
    t,d,m = fixture("initial_stand")
    t.update(150,d,m)
    assert t.calls == ["approach", "walk"]


def test_raise_only_after_stable_stop():
    t,d,m = fixture("source_stop")
    t.update(150,d,m)
    assert t.calls == ["ready_arm", "raise"]


def test_raise_then_reach():
    t,d,m = fixture("ready_arm")
    t.update(180,d,m)
    assert t.calls == ["preinsert", "reach"]


def test_safety_adapter_unchanged():
    assert project_target is original_project


def test_no_actual_state_overwrite_in_new_raise():
    import ast, inspect, textwrap
    tree = ast.parse(textwrap.dedent(inspect.getsource(Task.ready_arm)))
    writes = [ast.unparse(t) for n in ast.walk(tree) if isinstance(n, ast.Assign) for t in n.targets]
    assert not any(t.startswith("data.") for t in writes)
    assert any(t.startswith("planning.qpos") for t in writes)
