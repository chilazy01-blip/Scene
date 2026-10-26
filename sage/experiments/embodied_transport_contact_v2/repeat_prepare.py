"""Fixed two-condition local sensitivity check after a completed baseline."""
import argparse
from pathlib import Path
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding


def prepare(root,parent,qualification,index):
    if index not in (0,1) or root.exists():
        raise ValueError("two fixed new conditions only, no overwrite")
    q=read_bound_json(qualification/"AUDIT.json"); p=read_bound_json(qualification/"POLICY_AUDIT.json")
    if not q["full_transport_passed"] or not p["passed"]:
        raise ValueError("full baseline not independently qualified")
    plan=parent/"REPEAT_PLAN.json"
    if not plan.exists():
        save(plan,{"schema":"continuous-transport-local-repeat-plan/v1","baseline":_file_binding(qualification/"AUDIT.json"),
                   "policy":_file_binding(qualification/"POLICY_AUDIT.json"),"implementation":_file_binding(Path(__file__)),
                   "start_and_root_goals_y_offsets_m":[-.01,.01],"object_and_fixtures":"unchanged",
                   "max_cases":2,"max_causal_revisions":0,"rejected_identical_retry":False,
                   "scope":"same generated development room and same object, local start-position sensitivity only, not held-out or production robustness"})
    frozen=read_bound_json(plan)
    delta=frozen["start_and_root_goals_y_offsets_m"][index]
    root.mkdir(parents=True); (root/"model").symlink_to(parent/"model",target_is_directory=True)
    case=read_bound_json(parent/"CASE.json")
    for key in ("start_xy_m","source_root_goal_xy_m","target_root_goal_xy_m","goal_xy_m"):
        case[key]=[case[key][0],case[key][1]+delta]
    case["protocol_root"]=str(root)
    case["local_start_y_offset_m"]=delta
    save(root/"CASE.json",case)
    cert=read_bound_json(parent/"PREFLIGHT_SAFE.json")
    cert.update(case=_file_binding(root/"CASE.json"),parent_certificate=_file_binding(parent/"PREFLIGHT_SAFE.json"),
                scope="same unchanged object/fixture/model and waypoint, +/-1cm robot-start/root-goal Y sensitivity; actual-state IK and all physical guards retained")
    save(root/"PREFLIGHT_SAFE.json",cert)
    protocol=read_bound_json(parent/"PROTOCOL.json")
    protocol.update(case=_file_binding(root/"CASE.json"),baseline=_file_binding(qualification/"AUDIT.json"),repeat_plan=_file_binding(plan),
                    finite_stage="two preregistered +/-1cm start conditions, first rejection exits each case, no controller revisions")
    protocol["dependencies"]["embodied_transport_contact_v2/repeat_prepare.py"]=_file_binding(Path(__file__))
    save(root/"PROTOCOL.json",protocol)
    print({"repeat_case":index,"start_y_offset_m":delta,"root":str(root)})

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--root",type=Path,required=True);p.add_argument("--parent",type=Path,required=True)
    p.add_argument("--qualification",type=Path,required=True);p.add_argument("--index",type=int,required=True)
    a=p.parse_args();prepare(a.root,a.parent,a.qualification,a.index)
