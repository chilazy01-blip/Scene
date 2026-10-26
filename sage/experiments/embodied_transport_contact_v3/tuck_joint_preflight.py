"""Three nominal-posture seeded compact goals and bounded joint interpolation."""
import argparse
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from sage.experiments.embodied_transport_contact_v1.fast_kinematics import solve,ARM_NAMES
from sage.experiments.embodied_transport_hybrid_v3.control import ARM
from sage.experiments.embodied_data_stability_v1.sonic_semantic_shadow import DEFAULT_ANGLES
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding


def run(root):
    import mujoco
    path=root/"attempt_01/active_1000/REPORT.json";r=read_bound_json(path);t=read_bound_json(Path(r["trace"]["path"]))
    rows=[x for x in t["records"] if x["sonic_candidate_consumed_by_physics"]]
    frame=next(e["frame"] for e in r["task_events"] if e["to"]=="carry")-1
    initial=np.array(rows[frame]["substeps"][-1]["full_qpos_after"])
    m=mujoco.MjModel.from_xml_path(r["model"]["path"]);d=mujoco.MjData(m);d.qpos[:]=initial;mujoco.mj_forward(m,d)
    w=m.body("right_wrist_yaw_link").id;g=m.geom("payload_geom").id;body=m.body("payload").id
    R=d.xmat[w].reshape(3,3).copy();base=d.qpos[:3].copy()
    local=R.T@(d.xpos[body]-d.xpos[w]);localR=R.T@d.xmat[body].reshape(3,3)
    qids=np.array([m.joint(n).qposadr[0] for n in ARM_NAMES]);oid=int(m.joint("payload_free").qposadr[0])
    checks=[]
    for vector in ([.12,-.24,.20],[.18,-.24,.20],[.16,-.28,.18]):
        seed=initial.copy();seed[qids]=np.array(DEFAULT_ANGLES)[ARM]
        ik=solve(mujoco,m,seed,base+vector,R,max_evaluations=150);goal=np.array(ik["angles_rad"]);samples=[]
        for i in range(1,31):
            d.qpos[:]=initial;d.qpos[qids]=initial[qids]+(goal-initial[qids])*i/30
            mujoco.mj_kinematics(m,d);actualR=d.xmat[w].reshape(3,3)
            d.qpos[oid:oid+3]=d.xpos[w]+actualR@local
            quat=Rotation.from_matrix(actualR@localR).as_quat();d.qpos[oid+3:oid+7]=quat[[3,0,1,2]]
            mujoco.mj_forward(m,d);bad=[]
            for c in d.contact:
                a,b=map(int,(c.geom1,c.geom2));names=[m.geom(j).name for j in (a,b)]
                if any(n.startswith(("task_","scene_proxy_","room_wall_")) for n in names):bad.append(names)
                if g in (a,b) and not any("hand" in m.body(int(m.geom_bodyid[j])).name for j in (a,b) if j!=g):bad.append(names)
            axis=d.xmat[body].reshape(3,3)[:,2];bottom=d.xpos[body,2]-(.06*abs(axis[2])+.02*np.linalg.norm(axis[:2]))
            samples.append({"fraction":i/30,"bottom_z_m":float(bottom),"collisions":bad})
        passed=ik["position_error_m"]<.005 and ik["orientation_error_rad"]<.05 and all(not s["collisions"] and s["bottom_z_m"]>=.82 for s in samples)
        checks.append({"wrist_relative_to_base_m":vector,"ik":ik,"passed":passed,"samples":samples})
    chosen=next((x["wrist_relative_to_base_m"] for x in checks if x["passed"]),None)
    save(root/"TUCK_JOINT_PREFLIGHT.json",{"report":_file_binding(path),"implementation":_file_binding(Path(__file__)),"physics_steps":0,"max_candidates":3,"checks":checks,
         "selected_wrist_relative_to_base_m":chosen,"passed":chosen is not None,"seed":"official nominal right arm, to prefer positive-elbow compact branch; actual episode unchanged",
         "scope":"three endpoints and90 rigid-grasp joint interpolation FK samples, not physical grip/transport validation; use100tick quintic arm reference before carrying"})
    print({"selected":chosen,"checks":[(x["wrist_relative_to_base_m"],x["passed"],x["ik"]["angles_rad"]) for x in checks]})

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--root",type=Path,required=True);run(p.parse_args().root)
