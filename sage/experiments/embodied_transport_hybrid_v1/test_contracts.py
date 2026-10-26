"""Control ownership checks, not physical task success evidence."""

import numpy as np
from .control import ARM, SONIC, compose, feedforward


def test_only_right_arm_can_replace_sonic_targets():
    raw = np.arange(29, dtype=float)
    reference = -np.arange(29, dtype=float)
    applied = compose(raw, reference, True)
    np.testing.assert_array_equal(applied[SONIC], raw[SONIC])
    np.testing.assert_array_equal(applied[ARM], reference[ARM])
    np.testing.assert_array_equal(compose(raw, reference, False), raw)
    assert len(SONIC) == 22 and len(ARM) == 7


def test_active_gravity_only_arm_motors():
    bias = np.arange(29, dtype=float) + 1
    ff = feedforward(bias, True)
    np.testing.assert_array_equal(ff[SONIC], 0)
    np.testing.assert_array_equal(ff[ARM], bias[ARM])
    np.testing.assert_array_equal(feedforward(bias, False), bias)
    np.testing.assert_array_equal(bias, np.arange(29, dtype=float) + 1)


def test_standing_qualification_never_labels_a_carry_stage():
    from .task import Task

    t = object.__new__(Task)
    t.case = {"task_mode": "standing_pick_place"}
    t.events = []
    t.stage = "lift"
    t.bias = np.zeros(3)
    t.transition("carry", 100, {})
    assert t.stage == "place" and t.events[-1]["to"] == "place"
