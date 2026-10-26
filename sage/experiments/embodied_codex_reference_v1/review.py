"""Physical measurements and a paired descriptive comparison, not a success-rate claim."""
import argparse
import json
from pathlib import Path
import numpy as np

from .bootstrap import ROOT
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
    for stage in ("place", "release", "retract", "settle"):
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


def summarize():
    plan = json.loads((ROOT / "PLAN.json").read_text())
    pairs = []
    for case in plan["paired_cases"]:
        entries = {}
        for arm in plan["arms"]:
            path = ROOT / case["case_id"] / arm
            mpath = path / "MEASUREMENTS.json"
            if not mpath.exists():
                entries[arm] = dict(completed=False)
                continue
            m = read_bound_json(mpath)
            entries[arm] = dict(completed=True, **{k:m[k] for k in ("task_passed","cup_upright_cosine","goal_error_m","final_root_speed_margin_m_s","suffix_seconds","new_suffix_physics_steps")},
                               measurements=_file_binding(mpath))
            for name,file in (("audit","full/AUDIT.json"),("replay","continuous_replay/REPORT.json"),("force","FORCE_CHECK.json"),("delivery","delivery/REVIEW.json"),("visual_review","VISUAL_REVIEW.json")):
                if (path / file).exists():
                    entries[arm][name] = _file_binding(path / file)
        delta = None
        if all(entries[a]["completed"] for a in plan["arms"]):
            delta = {k:entries["codex"][k]-entries["baseline"][k] for k in ("goal_error_m","final_root_speed_margin_m_s","suffix_seconds","new_suffix_physics_steps")}
        pairs.append(dict(case_id=case["case_id"], arms=entries, codex_minus_baseline=delta))
    ledger = read_bound_json(ROOT / "COST.json")
    missing = [x for x in ledger["reservations"] if not (Path(x["output"]) / "REPORT.json").exists()]
    result = dict(schema="codex-reference-paired-pilot-review/v1", pairs=pairs,
        prior_native_steps=84564, new_physics_steps=spent_steps(ledger), cumulative_native_steps=84564+spent_steps(ledger),
        unsettled_reservations=missing, max_new_physics_steps=52000,
        model_calls=[json.loads(p.read_text()) for p in ROOT.glob("proposal_*/INVOCATION.json")],
        source_role="development_validation", dataset_split="unassigned",
        scenes=1, predefined_target_variants=2, shared_prefix=True,
        independent_success_rate_estimated=False, generalization_proven=False, learning_effect_evaluated=False,
        implementation=_file_binding(Path(__file__)))
    safe_save(ROOT / "REVIEW.json", result)
    print(json.dumps(dict(pairs=pairs,new_physics_steps=result["new_physics_steps"],cumulative_native_steps=result["cumulative_native_steps"]),ensure_ascii=False),flush=True)


if __name__ == "__main__":
    ap=argparse.ArgumentParser(); ap.add_argument("action",choices=["measure","summarize"]); ap.add_argument("--root",type=Path)
    args=ap.parse_args()
    if args.action == "measure": measure(args.root)
    else: summarize()
