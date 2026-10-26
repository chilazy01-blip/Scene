"""Frozen before physics: conservative 0.5s stop/hold acceptance, not end-of-run."""

STOP_LIMITS = {
    "hold_substeps": 100,
    "max_horizontal_speed_m_s": 0.08,
    "max_horizontal_drift_m": 0.02,
    "max_joint_velocity_rms_rad_s": 0.6,
    "min_both_feet_contact_fraction": 0.9,
    "min_forward_displacement_m": 0.05,
    "min_completed_footstep_cycles_total": 1,
}


def stop_acceptance(records):
    import numpy as np
    from .audit_sonic_walking_execution import recount_steps

    active = [r for r in records if r["sonic_candidate_consumed_by_physics"]]
    samples = [s for r in active for s in r["substeps"]]
    tail = samples[-100:]
    if not tail:
        return {"passed": False, "thresholds": STOP_LIMITS, "metrics": {}}
    speeds = [float(np.linalg.norm(s["root_velocity_after_m_s"][:2])) for s in tail]
    anchor = np.asarray(tail[0]["full_qpos_before"][:2])
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
        active[-1]["actual_root_xyz_after_m"][0]
        - active[0]["actual_root_xyz_before_m"][0]
    )
    gates = {
        "complete_100_tick_400_step_protocol": len(active) == 100
        and len(samples) == 400,
        "unsupported": all(
            not s["support_enabled"] and not np.any(s["support_wrench"])
            for s in samples
        ),
        "genuine_step_and_progress": sum(cycles.values()) >= 1 and forward >= 0.05,
        "hold_speed": max(speeds) <= 0.08,
        "hold_drift": drift <= 0.02,
        "hold_joint_velocity": rms <= 0.6,
        "hold_both_feet_contact": both >= 0.9,
        "hold_window_complete": len(tail) == 100,
    }
    return {
        "passed": all(gates.values()),
        "thresholds": STOP_LIMITS,
        "gates": gates,
        "metrics": {
            "hold_max_horizontal_speed_m_s": max(speeds),
            "hold_horizontal_drift_m": drift,
            "hold_max_joint_velocity_rms_rad_s": rms,
            "hold_both_feet_contact_fraction": both,
            "forward_displacement_m": forward,
            "completed_cycles": cycles,
        },
    }
