from copy import deepcopy
import pytest

from sage.experiments.embodied_task_interface.contracts import audit_json, outcome


def fixture(task="pick_place"):
    from sage.experiments.embodied_scene_v2.config import default
    return default(task), dict(goal_xy_error_m=.01, stable_seconds=1., forbidden_contact_steps={},
                              max_robot_scene_penetration_m=0., max_lift_m=.1,
                              bilateral_seconds=.1, target_floor_contact_steps=0)


@pytest.mark.parametrize("task", ["navigate", "pick_place"])
def test_unvalidated_and_infrastructure_are_not_task_failures(task):
    c, m = fixture(task)
    r = outcome(c, m, stopped=False, reason="running", engineering=None)
    assert r["success"] is None and r["status"] == "unvalidated"
    r = outcome(c, m, stopped=True, reason="restore_error", engineering=False)
    assert r["status"] == "infrastructure_error" and r["truncated"] and not r["terminated"]
    assert not r["success"]


@pytest.mark.parametrize("task", ["navigate", "pick_place"])
def test_timeout_and_policy_failure_have_distinct_lifecycle(task):
    c, m = fixture(task)
    m["goal_xy_error_m"] = 1.
    r = outcome(c, m, stopped=True, reason="time_limit", engineering=True)
    assert r["status"] == "timeout" and r["truncated"] and not r["terminated"]
    r = outcome(c, m, stopped=True, reason="native_plan_end", engineering=True)
    assert r["status"] == "task_failure" and r["terminated"] and not r["truncated"]


@pytest.mark.parametrize("field,value", [("goal_xy_error_m", .06), ("bilateral_seconds", .05),
    ("max_robot_scene_penetration_m", .003), ("max_lift_m", .079999),
    ("target_floor_contact_steps", 1), ("forbidden_contact_steps", {"pair": 1}),
    ("stable_seconds", .999)])
def test_exact_frozen_rejection_boundaries(field, value):
    c, m = fixture()
    good = deepcopy(m)
    m[field] = value
    assert outcome(c, good, stopped=True, reason="native_plan_end", engineering=True)["success"]
    assert not outcome(c, m, stopped=True, reason="native_plan_end", engineering=True)["success"]


def test_source_stability_tolerance_and_inclusive_lift_preserved():
    c, m = fixture()
    m.update(stable_seconds=1. - 1e-9, max_lift_m=.08)
    assert outcome(c, m, stopped=True, reason="native_plan_end", engineering=True)["success"]


def test_nonfinite_audit_metadata_can_be_serialized_without_losing_finite_values():
    import json
    value = audit_json(dict(speed=float("nan"), nested=[float("inf"), .25]))
    assert value == dict(speed=None, nested=[None, .25])
    json.dumps(value, allow_nan=False)
