"""Task-only acceptance over per-step reconstructed measurements, not physics proof.

No model loading, controller, mj_step, or motion authorization occurs here.
Real qualification must additionally pass independent motor/policy/dynamics audits.
"""

import math
import numpy as np

LIMITS = {
    "simulation_dt_s": 0.005,
    "initial_stand_s": 10.0,
    "minimum_forward_m": 1.0,
    "final_stand_s": 5.0,
    "minimum_pelvis_m": 0.7,
    "minimum_up_component": 0.97,
    "maximum_penetration_m": 0.01,
    "maximum_contact_force_n": 600.0,
    "maximum_stand_root_speed_m_s": 0.04,
    "maximum_stand_horizontal_drift_m": 0.02,
    "maximum_stand_joint_velocity_rms_rad_s": 0.6,
    "minimum_stand_both_feet_contact_fraction": 0.9,
    "maximum_lateral_deviation_m": 0.15,
    "maximum_goal_error_m": 0.15,
    "swing_clearance_m": 0.015,
    "stance_force_n": 2.0,
    "swing_force_max_n": 1.0,
    "minimum_cycles_each_foot": 1,
}
PHASES = ("observer", "settling", "initial_stand", "walking", "braking", "final_stand")


def _tail_window(rows, seconds):
    if not rows:
        return []
    end = float(rows[-1]["time_after_s"])
    selected = [r for r in rows if float(r["time_after_s"]) > end - seconds + 1e-9]
    if not selected or end - float(selected[0]["time_before_s"]) < seconds - 1e-9:
        return []
    return selected


def _stand(rows, seconds):
    window = _tail_window(rows, seconds)
    if not window:
        return {
            "passed": False,
            "duration_s": 0.0,
            "reason": "insufficient continuous standing duration",
        }
    anchor = np.asarray(window[0]["root_before_m"][:2], dtype=float)
    speed = max(float(np.linalg.norm(r["root_velocity_m_s"])) for r in window)
    drift = max(
        float(np.linalg.norm(np.asarray(r["root_after_m"][:2]) - anchor))
        for r in window
    )
    joint_rms = max(
        float(np.sqrt(np.mean(np.square(r["body_joint_velocity_rad_s"]))))
        for r in window
    )
    both = float(
        np.mean(
            [
                all(
                    r["feet"][s]["ground_force_n"] > LIMITS["stance_force_n"]
                    for s in ("left", "right")
                )
                for r in window
            ]
        )
    )
    supported = all(
        any(
            r["feet"][s]["ground_force_n"] > LIMITS["stance_force_n"]
            for s in ("left", "right")
        )
        for r in window
    )
    gates = {
        "root_speed": speed <= LIMITS["maximum_stand_root_speed_m_s"],
        "root_drift": drift <= LIMITS["maximum_stand_horizontal_drift_m"],
        "joint_velocity": joint_rms <= LIMITS["maximum_stand_joint_velocity_rms_rad_s"],
        "double_support": both >= LIMITS["minimum_stand_both_feet_contact_fraction"],
        "at_least_one_foot_grounded_each_sample": supported,
    }
    return {
        "passed": all(gates.values()),
        "duration_s": float(window[-1]["time_after_s"] - window[0]["time_before_s"]),
        "window_start_s": float(window[0]["time_before_s"]),
        "window_end_s": float(window[-1]["time_after_s"]),
        "maximum_root_speed_m_s": speed,
        "maximum_xy_drift_m": drift,
        "maximum_joint_velocity_rms_rad_s": joint_rms,
        "both_feet_contact_fraction": both,
        "gates": gates,
    }


def _cycles(rows, side):
    state = "unseen"
    count = 0
    for r in rows:
        foot = r["feet"][side]
        stance = foot["ground_force_n"] > LIMITS["stance_force_n"]
        swing = (
            foot["ground_force_n"] <= LIMITS["swing_force_max_n"]
            and foot["clearance_m"] >= LIMITS["swing_clearance_m"]
        )
        if stance:
            if state == "swing":
                count += 1
            state = "stance"
        elif swing and state == "stance":
            state = "swing"
    return count


def evaluate(rows, case):
    """Check task metrics. Caller must reconstruct rows from actual logged states."""
    gates = {"nonempty": bool(rows)}
    if not rows:
        return {
            "task_metrics_passed": False,
            "gates": gates,
            "limits": dict(LIMITS),
            "not_a_physics_audit": True,
        }
    try:
        dt = LIMITS["simulation_dt_s"]
        stage_numbers = [PHASES.index(r["phase"]) for r in rows]
        gates["phase_order"] = all(
            a <= b for a, b in zip(stage_numbers, stage_numbers[1:])
        )
        gates["all_required_phases"] = all(
            p in [r["phase"] for r in rows]
            for p in ("initial_stand", "walking", "braking", "final_stand")
        )
        gates["exact_physics_timestep"] = all(
            abs((r["time_after_s"] - r["time_before_s"]) - dt) <= 1e-9 for r in rows
        )
        gates["continuous_time"] = all(
            abs(a["time_after_s"] - b["time_before_s"]) <= 1e-9
            for a, b in zip(rows, rows[1:])
        )
        gates["continuous_root_state"] = all(
            np.array_equal(a["root_after_m"], b["root_before_m"])
            for a, b in zip(rows, rows[1:])
        )
        numeric = []
        for r in rows:
            numeric.extend(
                [
                    r["time_before_s"],
                    r["time_after_s"],
                    r["up_component"],
                    r["penetration_m"],
                    r["contact_force_n"],
                ]
            )
            for key in (
                "root_before_m",
                "root_after_m",
                "root_velocity_m_s",
                "body_joint_velocity_rad_s",
                "xfrc_applied",
                "qfrc_applied",
            ):
                numeric.extend(np.asarray(r[key], dtype=float).reshape(-1).tolist())
            for side in ("left", "right"):
                numeric.extend(
                    [r["feet"][side]["ground_force_n"], r["feet"][side]["clearance_m"]]
                )
        gates["finite"] = bool(np.isfinite(numeric).all())
        gates["vector_shapes"] = all(
            len(r["root_before_m"]) == 3
            and len(r["root_after_m"]) == 3
            and len(r["root_velocity_m_s"]) == 3
            and len(r["body_joint_velocity_rad_s"]) == 29
            and np.asarray(r["xfrc_applied"]).shape == (50, 6)
            and len(r["qfrc_applied"]) == 49
            for r in rows
        )
        gates["no_external_support"] = all(
            not np.any(r["xfrc_applied"]) and not np.any(r["qfrc_applied"])
            for r in rows
        )
        gates["no_environment_or_nonfoot_floor_contact"] = all(
            r["forbidden_contacts"] == 0 for r in rows
        )
        gates["original_physical_limits"] = all(
            r["root_after_m"][2] >= LIMITS["minimum_pelvis_m"]
            and r["up_component"] >= LIMITS["minimum_up_component"]
            and 0 <= r["penetration_m"] <= LIMITS["maximum_penetration_m"]
            and 0 <= r["contact_force_n"] <= LIMITS["maximum_contact_force_n"]
            for r in rows
        )
        initial = [r for r in rows if r["phase"] == "initial_stand"]
        final = [r for r in rows if r["phase"] == "final_stand"]
        moving = [r for r in rows if r["phase"] in ("walking", "braking")]
        first = _stand(initial, LIMITS["initial_stand_s"])
        last = _stand(final, LIMITS["final_stand_s"])
        gates["initial_continuous_10s_stand"] = first["passed"]
        gates["final_continuous_5s_stand"] = last["passed"]
        yaw = math.radians(float(case["start_yaw_deg"]))
        direction = np.array([math.cos(yaw), math.sin(yaw)])
        side = np.array([-direction[1], direction[0]])
        origin = (
            np.asarray(moving[0]["root_before_m"][:2])
            if moving
            else np.asarray(case["start_xy_m"])
        )
        endpoint = np.asarray(rows[-1]["root_after_m"][:2])
        forward = float((endpoint - origin) @ direction)
        goal_error = float(np.linalg.norm(endpoint - np.asarray(case["goal_xy_m"])))
        lateral = max(
            abs(
                float(
                    (np.asarray(r["root_after_m"][:2]) - np.asarray(case["start_xy_m"]))
                    @ side
                )
            )
            for r in rows
        )
        cycles = {s: _cycles(moving, s) for s in ("left", "right")}
        gates["actual_forward_at_least_1m"] = forward >= LIMITS["minimum_forward_m"]
        gates["actual_landing_cycles_both_feet"] = all(
            n >= LIMITS["minimum_cycles_each_foot"] for n in cycles.values()
        )
        gates["route_lateral_error"] = lateral <= LIMITS["maximum_lateral_deviation_m"]
        gates["destination_error"] = goal_error <= LIMITS["maximum_goal_error_m"]
        return {
            "task_metrics_passed": all(gates.values()),
            "gates": gates,
            "limits": dict(LIMITS),
            "initial_stand": first,
            "final_stand": last,
            "forward_m": forward,
            "goal_error_m": goal_error,
            "maximum_lateral_error_m": lateral,
            "foot_cycles": cycles,
            "physics_samples": len(rows),
            "not_a_physics_audit": True,
            "qualification_requires": [
                "exact input/model/source bindings",
                "independent full-state/action/torque/contact reconstruction",
                "causal policy replay",
                "continuous dynamics audit",
                "all3fixed conditions same controller version",
                "real-state video/manual review",
            ],
        }
    except (KeyError, TypeError, ValueError, IndexError) as error:
        gates["valid_measurement_schema"] = False
        return {
            "task_metrics_passed": False,
            "gates": gates,
            "error": str(error),
            "limits": dict(LIMITS),
            "not_a_physics_audit": True,
        }
