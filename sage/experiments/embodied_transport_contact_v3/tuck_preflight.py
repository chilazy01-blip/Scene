"""Three fixed compact carrying paths; hypothetical rigid grasp, zero physics."""
import argparse
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from sage.experiments.embodied_transport_contact_v1.fast_kinematics import solve,ARM_NAMES
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding


def run(root):
    import mujoco
    path=root/"attempt_01/active_1000/REPORT.json"; r=read_bound_json(path);t=read_bound_json(Path(r["trace"]["path"]))
    rows=[x for x in t["records"] if x["sonic_candidate_consumed_by_physics"]]
    frame=next(e["frame"] for e in r["task_events"] if e["to"]=="carry")-1
    initial=np.array(rows[frame]["substeps"][-1]["full_qpos_after"])
    m=mujoco.MjModel.from_xml_path(r["model"]["path"]);d=mujoco.MjData(m);d.qpos[:]=initial;mujoco.mj_forward(m,d)
    w=m.body("right_wrist_yaw_link").id;g=m.geom("payload_geom").id;body=m.body("payload").id
    p=d.xpos[w].copy();R=d.xmat[w].reshape(3,3).copy();base=d.qpos[:3].copy()
    local=R.T@(d.xpos[body]-p);localR=R.T@d.xmat[body].reshape(3,3)
    qids=np.array([m.joint(n).qposadr[0] for n in ARM_NAMES]);oid=int(m.joint("payload_free").qposadr[0])
    candidates=[[.12,-.24,.20],[.18,-.24,.20],[.16,-.28,.18]];checks=[]
    for vector in candidates:
        d.qpos[:]=initial;goal=base+vector;samples=[]
        for i in range(1,31):
            xyz=p+(goal-p)*i/30
            ik=solve(mujoco,m,d.qpos,xyz,R,max_evaluations=120)
            d.qpos[qids]=ik["angles_rad"]
            mujoco.mj_kinematics(m,d)
            actualR=d.xmat[w].reshape(3,3)
            d.qpos[oid:oid+3]=d.xpos[w]+actualR@local
            quat=Rotation.from_matrix(actualR@localR).as_quat();d.qpos[oid+3:oid+7]=quat[[3,0,1,2]]
            mujoco.mj_forward(m,d);bad=[]
            for c in d.contact:
                a,b=map(int,(c.geom1,c.geom2));names=[m.geom(j).name for j in (a,b)]
                if any(n.startswith(("task_","scene_proxy_","room_wall_")) for n in names):bad.append(names)
                if g in (a,b) and not any("hand" in n for n in names):bad.append(names)
            samples.append({"fraction":i/30,"position_error_m":ik["position_error_m"],"orientation_error_rad":ik["orientation_error_rad"],"joint_margin_rad":ik["joint_limit_margin_rad"],"collisions":bad})
        checks.append({"wrist_relative_to_base_m":vector,"angles_rad":ik["angles_rad"],"passed":all(s["position_error_m"]<.005 and s["orientation_error_rad"]<.05 and not s["collisions"] for s in samples),"samples":samples})
    chosen=next((x["wrist_relative_to_base_m"] for x in checks if x["passed"]),None)
    result={"schema":"compact-carry-geometric-preflight/v1","physics_steps":0,"report":_file_binding(path),"implementation":_file_binding(Path(__file__)),"actual_source_clear_frame":frame,
            "original_wrist_relative_to_base_m":(p-base).tolist(),"checks":checks,"selected_wrist_relative_to_base_m":chosen,"passed":chosen is not None,
            "scope":"90 hypothetical rigid-grasp FK samples only; payload pose assignments are confined to geometric sandbox, never applied to real episode; new tuck retains all original physical retention/clearance/command gates",
            "causal_revision":2,"max_physical_revisions":2,"finding":"carry braking75 also fails actual ankle range at830. Outstretched right wrist ~.39m lateral. Add compact load posture before walking instead of further duration tuning; continuous physical acquisition/transport/release still required"}
    save(root/"TUCK_PREFLIGHT.json",result)
    print({"selected":chosen,"original_relative":(p-base).tolist(),"checks":[(x["wrist_relative_to_base_m"],x["passed"],x["angles_rad"]) for x in checks]})

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--root",type=Path,required=True);run(p.parse_args().root)
