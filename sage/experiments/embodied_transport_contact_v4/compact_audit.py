"""Additional original lift and compact-load retention gates, zero integration."""
import argparse
from pathlib import Path
import numpy as np
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding


def audit(root):
    r=read_bound_json(root/"REPORT.json");t=read_bound_json(Path(r["trace"]["path"]));c=read_bound_json(Path(r["case"]["path"]))
    rows=[x for x in t["records"] if x["sonic_candidate_consumed_by_physics"]]
    tuck=next(e["frame"] for e in r["task_events"] if e["to"]=="tuck")
    carry=next(e["frame"] for e in r["task_events"] if e["to"]=="carry")
    before=[s for x in rows if tuck-25<=x["reference_tick"]<tuck for s in x["substeps"]]
    compact=[s for x in rows if tuck<=x["reference_tick"]<carry for s in x["substeps"]]
    carry_samples=[s for x in rows if x["task"]["stage"] in ("carry","target_stop") for s in x["substeps"]]
    anchor=np.array(rows[carry]["task"]["anchor_local_xyz_m"])
    def clear(s):
        p=s["payload"]
        return p["bottom_z_m"]>=c["support_top_m"]+.02 and not p["source_supported"] and not p["target_supported"] and p["opposing"]
    gates={"original_lift_before_compact100substeps":len(before)==100 and all(clear(s) for s in before),
           "compact_actual_duration_and_no_support":len(compact)>=400 and all(clear(s) and not s["support_enabled"] for s in compact),
           "compact_and_carry_unchanged30mm_retention":bool(compact and carry_samples) and all(np.linalg.norm(np.array(s["payload"]["local_position_m"])-anchor)<=.03 for s in compact+carry_samples)}
    result={"schema":"compact-load-additional-audit/v1","passed":all(gates.values()),"gates":gates,"report":_file_binding(root/"REPORT.json"),
            "implementation":_file_binding(Path(__file__)),"physics_steps":0,"compact_duration_s":len(compact)*.005,
            "min_compact_source_clearance_m":min(s["payload"]["bottom_z_m"]-c["support_top_m"] for s in compact),
            "carry_opposing_contact_fraction":sum(s["payload"]["opposing"] for s in carry_samples)/max(1,len(carry_samples))}
    save(root/"COMPACT_AUDIT.json",result)
    print(result)

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--root",type=Path,required=True);audit(p.parse_args().root)
