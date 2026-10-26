from dataclasses import replace

import pytest

from sage.experiments.embodied_data_stability_v1.source_a_quality_repair import (
    FingerLatchController,
    load_repair_config,
    sample_polyline,
    select_safe_translation_route,
)


def test_each_finger_latches_independently_and_only_lost_contact_recovers():
    config = replace(
        load_repair_config(),
        contact_loss_confirm_steps=2,
        slip_recovery_threshold_m=1.0,
    )
    closed = [1.0, 1.0, -1.0, 1.0, 1.0, 1.0, 1.0]
    controller = FingerLatchController(closed, config)
    controller.begin_grasp(0.0)
    q = [0.2] * 7
    raw = [0.8, 0.8, -0.8, 0.8, 0.8, 0.8, 0.8]
    controller.commands(raw, q)
    controller.observe(
        q=q,
        contacts={"index": -0.001},
        max_penetration_m=0.001,
        slip_m=0.0,
        sim_time_s=0.1,
    )
    assert controller.group_state == {
        "thumb": "seeking_contact",
        "index": "latched",
        "middle": "seeking_contact",
    }
    index_before = controller.targets[3]
    for step in range(2):
        controller.observe(
            q=q,
            contacts={},
            max_penetration_m=0.0,
            slip_m=0.0,
            sim_time_s=0.2 + step * 0.01,
        )
    assert controller.targets[3] > index_before
    assert controller.targets[5] is None


def test_penetration_guard_unloads_all_fingers_below_normal_preload():
    config = load_repair_config()
    controller = FingerLatchController([1.0] * 7, config)
    controller.begin_grasp(0.0)
    q = [0.3] * 7
    controller.commands([1.0] * 7, q)
    controller.observe(
        q=q,
        contacts={"thumb": -0.009},
        max_penetration_m=0.009,
        slip_m=0.0,
        sim_time_s=0.1,
    )
    assert all(state == "latched" for state in controller.group_state.values())
    assert controller.targets == pytest.approx([0.302] * 7)
    assert {event["event"] for event in controller.events} >= {"penetration_guard_unload"}


def test_opposing_contacts_tighten_only_until_cage_depth_is_reached():
    config = replace(
        load_repair_config(),
        cage_recovery_interval_steps=2,
        contact_loss_confirm_steps=100,
        slip_recovery_threshold_m=1.0,
    )
    controller = FingerLatchController([1.0] * 7, config)
    controller.begin_grasp(0.0)
    q = [0.2] * 7
    controller.commands([1.0] * 7, q)
    controller.observe(
        q=q,
        contacts={"thumb": -0.001, "middle": -0.001},
        max_penetration_m=0.001,
        slip_m=0.056,
        sim_time_s=0.1,
    )
    before_thumb = controller.targets[0]
    before_middle = controller.targets[5]
    controller.observe(
        q=q,
        contacts={"thumb": -0.001, "middle": -0.001},
        max_penetration_m=0.001,
        slip_m=0.056,
        sim_time_s=0.2,
    )
    controller.observe(
        q=q,
        contacts={"thumb": -0.001, "middle": -0.001},
        max_penetration_m=0.001,
        slip_m=0.056,
        sim_time_s=0.3,
    )
    assert controller.targets[0] > before_thumb
    assert controller.targets[5] > before_middle
    stopped = controller.targets.copy()
    for index in range(4):
        controller.observe(
            q=q,
            contacts={"thumb": -0.001, "middle": -0.001},
            max_penetration_m=0.001,
            slip_m=0.044,
            sim_time_s=0.4 + index * 0.1,
        )
    assert controller.targets == stopped


def test_release_cannot_begin_until_support_is_confirmed():
    controller = FingerLatchController([1.0] * 7, load_repair_config())
    controller.begin_grasp(0.0)
    controller.begin_support_unload([0.4] * 7, 0.1)
    with pytest.raises(RuntimeError, match="stable table support"):
        controller.begin_open(["thumb"], 0.2, require_support=True)
    controller.confirm_support(0.3)
    controller.begin_open(["thumb"], 0.4, require_support=True)
    assert controller.group_state["thumb"] == "opening"


def test_safe_route_uses_high_waypoint_without_moving_requested_endpoint():
    def clearance(points):
        # Direct descent through x=1 is unsafe; a z>=1 waypoint clears it.
        if len(points) == 2:
            return -0.01
        return 0.02 if points[1][2] >= 1.0 else -0.01

    plan = select_safe_translation_route(
        start=(0.0, 0.0, 1.0),
        requested=(1.0, 0.0, 0.5),
        candidates=[(1.0, 0.0, 0.5)],
        clearance=clearance,
        reachable=lambda _point: (True, 0.001),
        min_clearance_m=0.003,
        safe_height=lambda _point: 1.0,
    )
    assert plan is not None
    assert plan["kind"] == "high_then_descend"
    assert plan["points"][-1] == [1.0, 0.0, 0.5]


def test_polyline_sampling_has_no_duplicate_joint_point():
    samples = sample_polyline([(0, 0, 0), (1, 0, 0), (1, 1, 0)], 3)
    assert samples == [
        (0.0, 0.0, 0.0),
        (0.5, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (1.0, 0.5, 0.0),
        (1.0, 1.0, 0.0),
    ]
