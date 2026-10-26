"""Preserve all attempt denominators and separate diagnostic/audit physics."""
import argparse
from pathlib import Path
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding
from sage.experiments.embodied_data_stability_v1.audit_candidates import sha256_file


def review(output,roots,diagnostic,historical):
    reports=[];attempts=[];replays=[];bound_sources={};changed=[];exports=[]
    for root in roots:
        paths=sorted(root.glob("attempt_01/*/REPORT.json"))
        for path in paths:
            r=read_bound_json(path)
            reports.append({"report":_file_binding(path),"physics_steps":r["physics_steps"],"active_motor_steps":r["active_physics_steps"],
                            "task_mode":r["task_mode"],"task_passed":r["task_passed"],"stop_reason":r["stop_reason"],"wall_s":r["runtime"]["wall_seconds"]})
            for b in r["source_bindings"].values():bound_sources[b["path"]]=b
        a=read_bound_json(root/"attempt_01/RESULT.json")
        attempts.append({"attempt":_file_binding(root/"attempt_01/RESULT.json"),"completed":a["task_passed"],"physics_steps":a["physics_steps"],
                         "driver_elapsed_s":a["elapsed_s"],"task_mode":reports[-1]["task_mode"],"final_stop":a["outcomes"][-1]["stop_reason"]})
        for path in root.glob("attempt_01/*/DYNAMICS_REPLAY.json"):
            r=read_bound_json(path);replays.append({"audit":_file_binding(path),"physics_steps":r["physics_steps"],"passed":r["passed"]})
        for path in root.glob("episode/EPISODE.json"):
            r=read_bound_json(path);exports.append({"episode":_file_binding(path),"samples":r["samples"],"full_transport":r["full_transport_passed"]})
    for name,b in bound_sources.items():
        if sha256_file(Path(name))!=b["sha256"]:changed.append(name)
    diag=read_bound_json(diagnostic/"DIAGNOSTIC_RESULT.json")
    old=read_bound_json(historical/"ADJUSTMENT_REVIEW.json")
    pure_path=historical.parent/"embodied_transport_20261020_v6/BATCH_REVIEW.json"
    pure=read_bound_json(pure_path)
    historical_steps=old["physics_steps_this_three_version_batch"]+pure["physics_steps"]
    episode_steps=sum(r["physics_steps"] for r in reports);audit_steps=sum(r["physics_steps"] for r in replays)
    result={"schema":"continuous-transport-development-cost/v1","implementation":_file_binding(Path(__file__)),"all_reports":reports,"all_attempts":attempts,
            "isolated_diagnostic":_file_binding(diagnostic/"DIAGNOSTIC_RESULT.json"),"isolated_diagnostic_steps":diag["physics_steps"],
            "episode_physics_steps":episode_steps,"recorded_control_audit_steps":audit_steps,"dynamics_audits":replays,
            "new_phase_total_physics_steps":episode_steps+diag["physics_steps"]+audit_steps,
            "historical_reviews":[_file_binding(historical/"ADJUSTMENT_REVIEW.json"),_file_binding(pure_path)],"historical_transport_physics_steps":historical_steps,
            "transport_development_total_physics_steps":historical_steps+episode_steps+diag["physics_steps"]+audit_steps,
            "physical_full_attempts":sum(x["task_mode"]=="full_transport" for x in attempts),"completed_full_attempts":sum(x["task_mode"]=="full_transport" and x["completed"] for x in attempts),
            "exports":exports,"accepted_full_samples":sum(x["samples"] for x in exports if x["full_transport"]),
            "source_files_checked":len(bound_sources),"changed_frozen_sources":changed,"no_frozen_source_mutation":not changed,
            "learning_effect":"not measured; no training run; positive expert data admission only","diversity":"one generated development room and one50g cylinder; baseline plus fixed +/-1cm start check, no held-out claim",
            "yield_scope":"counts all development versions, qualifying prefixes and failures; dynamics replay/isolated diagnostic never counted as new autonomous successes",
            "review_physics_steps":0}
    save(output,result)
    print({k:v for k,v in result.items() if k not in ("all_reports","all_attempts","dynamics_audits","exports","historical_reviews","implementation","isolated_diagnostic")})

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--output",type=Path,required=True);p.add_argument("--root",type=Path,action="append",required=True)
    p.add_argument("--diagnostic",type=Path,required=True);p.add_argument("--historical",type=Path,required=True)
    a=p.parse_args();review(a.output,a.root,a.diagnostic,a.historical)
