"""Finite zero-step retraction path comparison from actual released posture."""
import argparse
from pathlib import Path
import numpy as np
from .fast_kinematics import solve, ARM_NAMES
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding


def run(root):
    import mujoco
    report_path=root/"attempt_01/active_1000/REPORT.json"
    r=read_bound_json(report_path); trace=read_bound_json(Path(r["trace"]["path"]))
    rows=[x for x in trace["records"] if x["sonic_candidate_consumed_by_physics"]]
    row=next(x for x in rows if x["task"]["stage"]=="retract")
    m=mujoco.MjModel.from_xml_path(r["model"]["path"]); d=mujoco.MjData(m)
    initial=np.array(row["substeps"][0]["full_qpos_before"]); d.qpos[:]=initial
    mujoco.mj_forward(m,d); w=m.body("right_wrist_yaw_link").id; g=m.geom("payload_geom").id
    origin=d.xpos[w].copy(); R=d.xmat[w].reshape(3,3).copy(); qids=np.array([m.joint(n).qposadr[0] for n in ARM_NAMES])
    candidates=[[-.10,0,0],[-.10,-.05,0],[0,-.10,0],[-.10,0,.04],[-.07,0,.07]]
    checks=[]
    for vector in candidates:
        d.qpos[:]=initial; samples=[]
        for i in range(1,26):
            goal=origin+np.array(vector)*(i/25)
            ik=solve(mujoco,m,d.qpos,goal,R,max_evaluations=100)
            d.qpos[qids]=ik["angles_rad"]; mujoco.mj_forward(m,d)
            collisions=[]
            for c in d.contact:
                a,b=map(int,(c.geom1,c.geom2)); names=[m.geom(j).name for j in (a,b)]
                if g in (a,b) and any("hand" in n for n in names):
                    collisions.append(names)
                if any(n.startswith("task_") for n in names) and g not in (a,b):
                    collisions.append(names)
            samples.append({"fraction":i/25,"position_error_m":ik["position_error_m"],"orientation_error_rad":ik["orientation_error_rad"],"collisions":collisions})
        checks.append({"vector_m":vector,"passed":all(s["position_error_m"]<.005 and s["orientation_error_rad"]<.05 and not s["collisions"] for s in samples),"samples":samples})
    chosen=next((x["vector_m"] for x in checks if x["passed"]),None)
    result={"schema":"released-retraction-preflight/v1","report":_file_binding(report_path),"implementation":_file_binding(Path(__file__)),
            "model":r["model"],"physics_steps":0,"actual_release_frame":row["reference_tick"],"max_samples":125,"checks":checks,
            "selected_vector_m":chosen,"passed":chosen is not None,
            "revision_budget":"at most two new causal release/retraction controller versions, independent standing requalification and then full transport; no threshold relaxation",
            "finding":"actual target-supported handfree at release; palm recontact at750 causes Y impulse then fall. Test fixed-orientation translation before raising instead of inherited biased diagonal retreat; geometric result is not physical qualification"}
    save(root/"RETRACTION_PREFLIGHT.json",result)
    print({"selected":chosen,"checks":[(x["vector_m"],x["passed"],sum(bool(s["collisions"]) for s in x["samples"])) for x in checks]})

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--root",type=Path,required=True);run(p.parse_args().root)
