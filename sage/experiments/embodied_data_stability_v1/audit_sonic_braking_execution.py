"""Independent bounded start/walk/stop audit, including all PD and foot poses."""

import argparse
import json
from pathlib import Path

from . import sonic_native_dynamic_shadow as native
from .audit_candidates import canonical_sha256, sha256_file, write_json_atomic
from .audit_sonic_supported_execution import read_bound_json
from .audit_sonic_walking_execution import recount_steps
from .sonic_native_planner_preflight import _file_binding
from .sonic_semantic_shadow import DEFAULT_ANGLES, ACTION_SCALES, ISAACLAB_TO_MUJOCO
from .sonic_walk_official_model import official_body_model_xml


def audit(root):
    import mujoco
    import numpy as np

    report = read_bound_json(root / "REPORT.json")
    for b in [
        *report["source_bindings"].values(),
        *report["inputs"].values(),
        report["trace"],
        report["admission"],
    ]:
        if sha256_file(Path(b["path"])) != b["sha256"]:
            raise ValueError(f"binding changed: {b['path']}")
    trace = read_bound_json(Path(report["trace"]["path"]))
    admission = read_bound_json(Path(report["admission"]["path"]))
    if sha256_file(Path(admission["trace"]["path"])) != admission["trace"]["sha256"]:
        raise ValueError("admission trace changed")
    prior = read_bound_json(Path(admission["trace"]["path"]))
    rows = trace["records"]
    active = [r for r in rows if r["sonic_candidate_consumed_by_physics"]]
    samples = [s for r in active for s in r["substeps"]]
    all_samples = [s for r in rows for s in r["substeps"]] + trace["warmup_substeps"]
    budget = report["active_budget_ticks"]
    keys = (
        "candidate_rad",
        "encoder_input_sha256",
        "decoder_input_sha256",
        "actual_qpos",
        "actual_qvel",
        "actual_quaternion",
        "actual_gyro",
    )
    prefix = len(rows) >= 50 and all(
        a[k] == b[k] for a, b in zip(rows[:50], prior["records"][:50]) for k in keys
    )
    controls = {k: np.asarray(v) for k, v in native.official_control_arrays().items()}
    xml, model_meta = official_body_model_xml()
    model = mujoco.MjModel.from_xml_string(xml.decode())
    data = mujoco.MjData(model)
    ids = native._model_ids(mujoco, model)
    lower, upper = model.jnt_range[ids["joint_ids"]].T
    max_pd = max_transform = max_clearance_error = 0.0
    commands_safe = True
    unchanged = True
    for r in active:
        target = (
            np.asarray(DEFAULT_ANGLES)
            + np.asarray(r["raw_action_isaaclab"])[list(ISAACLAB_TO_MUJOCO)]
            * ACTION_SCALES
        )
        max_transform = max(
            max_transform, float(np.max(np.abs(target - r["candidate_rad"])))
        )
        commands_safe &= bool(
            np.isfinite(target).all() and np.all((target >= lower) & (target <= upper))
        )
        for s in r["substeps"]:
            unchanged &= s["position_target_rad"] == r["candidate_rad"]
            pd = np.clip(
                controls["kp"] * (target - s["body_position_before_rad"])
                - controls["kd"] * s["body_velocity_before_rad_s"],
                -controls["effort_limit"],
                controls["effort_limit"],
            )
            max_pd = max(max_pd, float(np.max(np.abs(pd - s["body_torque_nm"]))))
            data.qpos[:] = s["full_qpos_after"]
            mujoco.mj_forward(model, data)
            for side in ("left", "right"):
                body = model.body(side + "_ankle_roll_link").id
                geom = next(
                    i for i in range(model.ngeom) if model.geom_bodyid[i] == body
                )
                bottom = (
                    data.geom_xpos[geom, 2]
                    - np.abs(data.geom_xmat[geom].reshape(3, 3)[2])
                    @ model.geom_size[geom]
                )
                max_clearance_error = max(
                    max_clearance_error,
                    abs(bottom - s["feet"][side]["sole_clearance_m"]),
                )
    previous = np.asarray(DEFAULT_ANGLES)
    slew_safe = True
    for r in rows:
        candidate = np.asarray(r["candidate_rad"])
        if r["substeps"]:
            slew_safe &= bool(
                np.max(np.abs(candidate - previous)) <= native.MAX_CANDIDATE_STEP_RAD
            )
        previous = candidate
    physical = all(
        np.isfinite(
            [
                s["pelvis_height_m"],
                s["up_component"],
                s["penetration_m"],
                s["contact_force_n"],
            ]
        ).all()
        and s["pelvis_height_m"] >= 0.65
        and s["up_component"] >= 0.5
        and s["penetration_m"] <= 0.01
        and s["contact_force_n"] <= 600
        and s["only_declared_support_wrench"]
        for s in all_samples
    )
    gates = {
        "schema": report["schema"] == "sonic-braking-active-smoke/v1",
        "exact_qualification_prefix": prefix,
        "complete_budget": len(active) == budget and len(samples) == 4 * budget,
        "budget_bounded": budget in (100, 250, 300),
        "no_early_abort": report["stop_reason"] is None,
        "numeric_physics": physical,
        "raw_action_transform_exact": max_transform == 0,
        "all_pd_updates_exact": max_pd == 0,
        "unchanged_raw_targets": unchanged,
        "joint_limits": commands_safe,
        "candidate_slew": slew_safe,
        "handoff_safe": bool(active)
        and active[0]["handoff_step_from_last_real_target_rad"]
        <= native.MAX_CANDIDATE_STEP_RAD,
        "no_support": all(
            not s["support_enabled"] and not any(s["support_wrench"]) for s in samples
        ),
        "no_active_bias": all(not s["bias_feedforward_used"] for s in samples),
        "no_source_a": not report["source_a_body_reference_used"]
        and not report["source_a_body_command_used"],
        "foot_clearance_independently_recomputed": max_clearance_error <= 1e-12,
        "state_chain_exact": all(
            a["full_qpos_after"] == b["full_qpos_before"]
            for a, b in zip(samples, samples[1:])
        ),
        "reference_clock": [r["reference_tick"] for r in active] == list(range(budget)),
    }
    if report["short_smoke_report"]:
        binding = report["short_smoke_report"]
        if sha256_file(Path(binding["path"])) != binding["sha256"]:
            raise ValueError("short smoke binding changed")
        short = read_bound_json(Path(binding["path"]))
        old = read_bound_json(Path(short["trace"]["path"]))
        old_active = [
            r for r in old["records"] if r["sonic_candidate_consumed_by_physics"]
        ]
        gates["short_smoke_passed_and_100_tick_prefix_exact"] = (
            short["active_smoke_passed"]
            and len(active) >= 100
            and all(
                a[k] == b[k] for a, b in zip(active[:100], old_active) for k in keys
            )
        )
    else:
        gates["long_run_requires_short_smoke"] = budget == 100
    tail = samples[-200:]
    anchor = np.asarray(tail[0]["full_qpos_before"][:2]) if tail else np.zeros(2)
    speed = max(
        (float(np.linalg.norm(s["root_velocity_after_m_s"][:2])) for s in tail),
        default=float("inf"),
    )
    drift = max(
        (
            float(np.linalg.norm(np.asarray(s["full_qpos_after"][:2]) - anchor))
            for s in tail
        ),
        default=float("inf"),
    )
    rms = max(
        (
            float(np.sqrt(np.mean(np.square(s["body_velocity_after_rad_s"]))))
            for s in tail
        ),
        default=float("inf"),
    )
    both = sum(
        all(
            s["feet"][side]["ground_contact_force_max_n"] > 2
            for side in ("left", "right")
        )
        for s in tail
    ) / max(len(tail), 1)
    cycles = {side: recount_steps(samples, side) for side in ("left", "right")}
    forward = (
        active[-1]["actual_root_xyz_after_m"][0]
        - active[0]["actual_root_xyz_before_m"][0]
        if active
        else 0.0
    )
    lateral = max(
        (
            abs(
                r["actual_root_xyz_after_m"][1]
                - active[0]["actual_root_xyz_before_m"][1]
            )
            for r in active
        ),
        default=0.0,
    )
    task = {
        "forward": forward >= 0.2,
        "both_feet_steps": all(c >= 1 for c in cycles.values()),
        "upright_quality": min((s["up_component"] for s in samples), default=0) >= 0.97,
        "height_quality": min((s["pelvis_height_m"] for s in samples), default=0)
        >= 0.7,
        "lateral_quality": lateral <= 0.15,
        "hold_complete": len(tail) == 200,
        "hold_speed": speed <= 0.08,
        "hold_drift": drift <= 0.02,
        "hold_joint_velocity": rms <= 0.6,
        "hold_double_support": both >= 0.9,
    }
    passed = all(gates.values()) and all(task.values())
    result = {
        "schema": "sonic-braking-independent-audit/v1",
        "control_passed": all(gates.values()),
        "classification": "passed" if passed else "not_accepted",
        "task_passed": passed,
        "gates": gates,
        "task_gates": task,
        "metrics": {
            "active_ticks": len(active),
            "active_steps": len(samples),
            "forward_m": forward,
            "cycles": cycles,
            "lateral_deviation_m": lateral,
            "hold_speed_m_s": speed,
            "hold_drift_m": drift,
            "hold_joint_velocity_rms_rad_s": rms,
            "hold_double_support_fraction": both,
            "max_pd_error_nm": max_pd,
            "max_transform_error_rad": max_transform,
            "max_sole_clearance_error_m": float(max_clearance_error),
        },
        "implementation": _file_binding(Path(__file__)),
        "report": _file_binding(root / "REPORT.json"),
        "trace": report["trace"],
        "physics_steps": 0,
        "production_accepted": False,
        "batch_authorized": False,
    }
    result["content_sha256_excluding_this_field"] = canonical_sha256(result)
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    result = audit(args.run_root)
    write_json_atomic(args.output, result)
    print(
        json.dumps(
            {
                k: result[k]
                for k in ("classification", "control_passed", "task_gates", "metrics")
            },
            indent=2,
        )
    )
