"""Whole-attempt stage accounting, including failures and all unexecuted phases."""
import argparse
from pathlib import Path
import math
import numpy as np
from .protocol_v3 import authorize
from .report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding


def run(root):
    p = authorize(root)
    episode = root / "version_03/full"
    out = root / "SEQUENCE_V3_ATTEMPT_REVIEW.json"
    assert not out.exists()
    r = read_bound_json(episode / "REPORT.json")
    t = read_bound_json(episode / "TRACE.json")
    a = read_bound_json(episode / "AUDIT.json")
    allsteps = t["warmup_substeps"] + [s for row in t["records"] for s in row["substeps"]]
    expected = ["initial_stand", "approach", "source_stop", "ready_arm", "preinsert", "lower", "insert", "close", "lift", "tuck", "carry", "target_stop", "place", "release", "retract", "settle", "done"]
    entered = ["initial_stand"] + [e["stage"] for e in t["events"] if "stage" in e]
    rows = []
    for name in expected:
        hit = [s for s in allsteps if s["stage"] == name]
        status = "not_executed"
        if name in entered:
            index = entered.index(name)
            status = "completed" if index < len(entered)-1 or (name == "done" and r["task_passed"]) else "stopped_here"
        rows.append({"stage":name,"status":status,"physics_steps":len(hit),
                     "start_s":hit[0]["time_before_s"] if hit else None,
                     "end_s":hit[-1]["time_after_s"] if hit else None})
    last = allsteps[-1]
    budget = read_bound_json(root / "COST.json")
    charged = sum(read_bound_json(Path(q["output"])/"REPORT.json")["physics_steps"]
                  if (Path(q["output"])/"REPORT.json").exists() else q["maximum_steps"] for q in budget["reservations"])
    review = {
        "schema":"native-mug-full-attempt-review/v3", "task_passed":bool(r["task_passed"] and a["task_passed"]),
        "whole_attempt_preserved":True, "unexecuted_phases_not_fabricated":True,
        "phase_accounting":rows,"stop_reason":r["stop_reason"],"engineering_error":r["error"],
        "executed_physics_steps":len(allsteps),"duration_s":last["time_after_s"],
        "all_applied_physics_safe":all(s["safe"] for s in allsteps),
        "failed_physical_samples":[{"time_s":s["time_after_s"],"stage":s["stage"],"failed_gates":[k for k,v in s["gates"].items() if not v]} for s in allsteps if not s["safe"]],
        "rejected_command":t["rejected_command"], "stage_events":t["events"],
        "final_object_m":last["object_m"],"final_root_m":last["root_m"],
        "final_opposing_grasp":last["opposing"],"final_desk_supported":last["desk_supported"],
        "max_penetration_m":max(s["penetration_m"] for s in allsteps),
        "max_contact_force_n":max(s["maximum_contact_force_n"] for s in allsteps),
        "max_actual_joint_excess_rad":max(s["maximum_joint_excess_rad"] for s in allsteps),
        "minimum_up":min(s["up"] for s in allsteps),
        "independent_audit_gates":a["gates"],"new_physics_total":charged,"cumulative_native_physics":18059+charged,
        "positive_episode_count":0 if not r["task_passed"] else None,
        "physics_budget_snapshot":budget,
        "report":_file_binding(episode/"REPORT.json"),"trace":r["trace"],"audit":_file_binding(episode/"AUDIT.json"),
        "protocol":_file_binding(root/"VERSION_03_PROTOCOL.json"),
        "sources":{f.name:_file_binding(f) for f in Path(__file__).parent.glob("*.py")},
        "scope":"negative attempts retain full physical trace, motor/NN inputs and stage-level stopping evidence; no forced continuation beyond safety or invented completed task",
    }
    safe_save(out,review)
    print({k:review[k] for k in ("task_passed","stop_reason","duration_s","executed_physics_steps","all_applied_physics_safe","new_physics_total")},flush=True)


if __name__ == "__main__":
    ap=argparse.ArgumentParser();ap.add_argument("--root",type=Path,required=True);run(ap.parse_args().root)
