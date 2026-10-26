"""Physical measurements and a paired descriptive comparison, not a success-rate claim."""
import argparse
import json
from pathlib import Path
import numpy as np

from .common import ROOT
from .protocol import read_bound_json, safe_save, _file_binding, spent_steps


def measure(root):
    root = Path(root)
    report = read_bound_json(root / "full/REPORT.json")
    trace = read_bound_json(root / "full/TRACE.json")
    case = read_bound_json(root / "CASE.json")
    protocol = read_bound_json(root / "PROTOCOL.json")
    rows = trace["warmup_substeps"] + [s for r in trace["records"] for s in r["substeps"]]
    suffix = rows[protocol["prefix_physics_steps"]:]
    tail = rows[-200:]
    root_speed = np.linalg.norm([s["root_velocity_m_s"] for s in tail], axis=1)
    cup_speed = np.linalg.norm([s["object_velocity_m_s"] for s in tail], axis=1)
    final = rows[-1]
    quat = np.asarray(final["full_qpos_after"][-4:])
    assert abs(float(quat @ quat) - 1) < 1e-8
    upright = float(1 - 2 * (quat[1]**2 + quat[2]**2))
    held = [s for s in rows if s["stage"] in ("carry", "target_stop")]
    start = np.asarray(held[0]["full_qpos_before"][:2])
    end = np.asarray(held[-1]["full_qpos_after"][:2])
    bad_tail = [dict(time_s=s["time_after_s"], root_speed_m_s=float(rv), cup_speed_m_s=float(cv),
                     desk_supported=s["desk_supported"], hand_contact=s["hand_contact"])
                for s, rv, cv in zip(tail, root_speed, cup_speed)
                if rv >= .06 or cv >= .02 or not s["desk_supported"] or s["hand_contact"]]
    stage_metrics = {}
    for stage in sorted({s["stage"] for s in suffix}):
        segment = [s for s in suffix if s["stage"] == stage]
        if segment:
            acceleration = np.linalg.norm([s["root_acceleration_m_s2"] for s in segment], axis=1)
            speed = np.linalg.norm([s["root_velocity_m_s"] for s in segment], axis=1)
            stage_metrics[stage] = dict(physics_steps=len(segment), seconds=len(segment)*.005,
                root_speed_max_m_s=float(max(speed)), root_acceleration_rms_m_s2=float(np.sqrt(np.mean(acceleration**2))),
                root_acceleration_max_m_s2=float(max(acceleration)))
    result = dict(schema="codex-reference-physical-measurements/v1", new_physics_steps=0,
        case_id=case["case_id"], task_passed=report["task_passed"], arm=protocol["arm"],
        paired_case_id=protocol["paired_case_id"], target_object_xyz_m=case["target_object_xyz_m"],
        final_cup_position_m=final["object_m"], cup_upright_cosine=upright,
        additional_upright_quality_passed=upright >= .98,
        final200_root_speed_max_m_s=float(max(root_speed)), final200_root_speed_p95_m_s=float(np.percentile(root_speed,95)),
        final_root_speed_margin_m_s=.06-float(max(root_speed)), final200_cup_speed_max_m_s=float(max(cup_speed)),
        original_stability_gate_bad_samples=bad_tail, original_stability_gate_all200_passed=not bad_tail,
        strict_held_robot_net_distance_m=float(np.linalg.norm(end-start)),
        strict_held_forward_distance_m=float(end[0]-start[0]),
        all_held_samples_have_hand_contact_and_offtable=all(s["hand_contact"] and not s["desk_supported"] for s in held),
        goal_error_m=report["goal_error_m"], max_held_slip_m=report["max_held_slip_m"],
        full_episode_physics_steps=report["physics_steps"], new_suffix_physics_steps=report["new_physics_steps"],
        full_episode_seconds=report["physics_steps"]*.005, suffix_seconds=len(suffix)*.005,
        stage_metrics=stage_metrics, report=_file_binding(root / "full/REPORT.json"),
        implementation=_file_binding(Path(__file__)))
    safe_save(root / "MEASUREMENTS.json", result)
    if not report["task_passed"] or upright < .98:
        safe_save(root / "DIAGNOSIS.json", dict(stop_reason=report["stop_reason"], engineering_error=report["error"],
            failed_task_gates=[k for k,v in report["gates"].items() if not v],
            measured_final_cup_up=upright, bad_final200_samples=bad_tail,
            last_stage=report["stage"], stage_metrics=stage_metrics,
            evidence=_file_binding(root / "MEASUREMENTS.json"),
            scope="Measured failure evidence; cause must be checked before any revision, no automatic parameter sweep."))
    print({k:result[k] for k in ("case_id","task_passed","cup_upright_cosine","final_root_speed_margin_m_s","goal_error_m","suffix_seconds")}, flush=True)
    return result

