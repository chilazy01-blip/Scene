"""Before-physics task criteria for a start/walk/brake/hold animation."""

LIMITS = {
    "minimum_forward_m": 0.2,
    "minimum_cycles_each_foot": 1,
    "minimum_up_component": 0.97,
    "minimum_pelvis_m": 0.7,
    "maximum_lateral_deviation_m": 0.15,
    "hold_substeps": 200,
    "maximum_hold_horizontal_speed_m_s": 0.08,
    "maximum_hold_horizontal_drift_m": 0.02,
    "maximum_hold_joint_velocity_rms_rad_s": 0.6,
    "minimum_hold_both_feet_contact_fraction": 0.9,
}


def accept(records, budget_ticks):
    import numpy as np
    from .audit_sonic_walking_execution import recount_steps

    rows = [r for r in records if r["sonic_candidate_consumed_by_physics"]]
    samples = [s for r in rows for s in r["substeps"]]
    if not samples:
        return {"passed": False, "thresholds": LIMITS, "metrics": {}, "gates": {}}
    tail = samples[-200:]
    anchor = np.asarray(tail[0]["full_qpos_before"][:2])
    speed = max(float(np.linalg.norm(s["root_velocity_after_m_s"][:2])) for s in tail)
    drift = max(
        float(np.linalg.norm(np.asarray(s["full_qpos_after"][:2]) - anchor))
        for s in tail
    )
    rms = max(
        float(np.sqrt(np.mean(np.square(s["body_velocity_after_rad_s"])))) for s in tail
    )
    both = sum(
        all(
            s["feet"][side]["ground_contact_force_max_n"] > 2
            for side in ("left", "right")
        )
        for s in tail
    ) / len(tail)
    cycles = {side: recount_steps(samples, side) for side in ("left", "right")}
    forward = (
        rows[-1]["actual_root_xyz_after_m"][0] - rows[0]["actual_root_xyz_before_m"][0]
    )
    lateral = max(
        abs(r["actual_root_xyz_after_m"][1] - rows[0]["actual_root_xyz_before_m"][1])
        for r in rows
    )
    up = min(s["up_component"] for s in samples)
    height = min(s["pelvis_height_m"] for s in samples)
    gates = {
        "complete_protocol": len(rows) == budget_ticks
        and len(samples) == budget_ticks * 4,
        "minimum_forward": forward >= 0.2,
        "both_feet_completed_cycles": all(c >= 1 for c in cycles.values()),
        "upright_quality": up >= 0.97,
        "pelvis_quality": height >= 0.7,
        "lateral_quality": lateral <= 0.15,
        "hold_complete": len(tail) == 200,
        "hold_speed": speed <= 0.08,
        "hold_drift": drift <= 0.02,
        "hold_joint_velocity": rms <= 0.6,
        "hold_double_support": both >= 0.9,
        "unsupported": all(
            not s["support_enabled"] and not any(s["support_wrench"]) for s in samples
        ),
    }
    return {
        "passed": all(gates.values()),
        "thresholds": LIMITS,
        "gates": gates,
        "metrics": {
            "forward_m": forward,
            "lateral_deviation_m": lateral,
            "cycles": cycles,
            "minimum_up_component": up,
            "minimum_pelvis_m": height,
            "hold_speed_m_s": speed,
            "hold_drift_m": drift,
            "hold_joint_velocity_rms_rad_s": rms,
            "hold_double_support_fraction": both,
        },
    }
