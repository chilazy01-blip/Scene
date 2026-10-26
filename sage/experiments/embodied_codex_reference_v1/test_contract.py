from types import SimpleNamespace
import numpy as np
import pytest

from .proposal import validate
from .task import Task, Previous


def proposal():
    return dict(schema="codex-reference-timing/v1", place_duration_ticks=90,
                retract_duration_ticks=80, rationale="Reduce requested acceleration.",
                evidence_ids=["E1", "E4"], expected_tradeoff="Longer duration.")


@pytest.mark.parametrize("change", [dict(friction=10), dict(place_duration_ticks=64),
    dict(retract_duration_ticks=101), dict(place_duration_ticks=True),
    dict(evidence_ids=["fabricated"]), dict(rationale="")])
def test_reject_unauthorized_controls_or_unsupported_evidence(change):
    with pytest.raises(ValueError):
        validate(dict(proposal(), **change), {"E1", "E4"})


@pytest.mark.parametrize("stage", ["place", "retract"])
def test_compiler_preserves_endpoints_and_continuity_without_writing_physics(stage):
    task = object.__new__(Task)
    task.stage = stage; task.reference_proposal = proposal(); task.events = []
    task.case = {"target_object_xyz_m": [2.6, 2.23, .787]}
    task.last_object_local = np.array([.15, .01, -.02]); task.grasp_R = np.eye(3)
    origin = np.array([2.3, 2.2, 1.03]); task.desired = lambda tick: (origin.copy(), np.eye(3))
    calls = []; task.synchronize = lambda *args, **kwargs: calls.append(kwargs)
    data = SimpleNamespace(qpos=np.arange(57, dtype=float), qvel=np.arange(55, dtype=float))
    before = (data.qpos.copy(), data.qvel.copy()); goal = np.array([2.1, 2.2, 1.1])
    Task.move(task, 1597, data, goal, np.eye(3), 120)
    expected = np.asarray(task.case["target_object_xyz_m"]) - task.last_object_local if stage == "place" else goal
    assert np.array_equal(task.path["origin"], origin)
    assert np.array_equal(task.path["goal"], expected)
    assert task.path["duration"] == task.reference_proposal[stage + "_duration_ticks"]
    assert np.array_equal(data.qpos, before[0]) and np.array_equal(data.qvel, before[1])
    assert calls == [{"force": True}]


@pytest.mark.parametrize("stage,assisted", [("place", False), ("carry", True), ("lift", True)])
def test_baseline_and_uncontrolled_stages_delegate_exactly(monkeypatch, stage, assisted):
    calls = []; monkeypatch.setattr(Previous, "move", lambda *args: calls.append(args))
    task = object.__new__(Task); task.stage = stage; task.reference_proposal = proposal() if assisted else None
    Task.move(task, 10, object(), np.zeros(3), np.eye(3), 60)
    assert len(calls) == 1 and calls[0][0] is task


def test_acceptance_and_stand_handoff_are_inherited():
    assert Task.update is Previous.update
    assert Task.change is Previous.change
    assert Task.force_update is Previous.force_update
