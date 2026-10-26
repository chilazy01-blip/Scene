"""Zero-step equivalence and timing check for collision-free FK evaluation."""
import argparse
from pathlib import Path
import time
import numpy as np
from .fast_kinematics import solve as fast
from sage.experiments.embodied_transport_v1.kinematics import solve as original
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding


def run(root, parent):
    import mujoco
    path = parent / "attempt_01/active_1000/REPORT.json"
    r = read_bound_json(path)
    t = read_bound_json(Path(r["trace"]["path"]))
    rows = [x for x in t["records"] if x["sonic_candidate_consumed_by_physics"]]
    m = mujoco.MjModel.from_xml_path(r["model"]["path"])
    d = mujoco.MjData(m)
    w = m.body("right_wrist_yaw_link").id
    checks = []
    for frame in (49, 200, 370, 500, 650, 827):
        d.qpos[:] = rows[frame]["substeps"][0]["full_qpos_before"]
        mujoco.mj_forward(m, d)
        xyz, R = d.xpos[w].copy(), d.xmat[w].reshape(3,3).copy()
        for offset in ([0,0,0], [.01,0,.01]):
            start = time.monotonic()
            a = original(mujoco,m,d.qpos,xyz+offset,R,max_evaluations=80)
            elapsed = time.monotonic()-start
            start = time.monotonic()
            b = fast(mujoco,m,d.qpos,xyz+offset,R,max_evaluations=80)
            fast_elapsed = time.monotonic()-start
            error = float(np.max(np.abs(np.array(a["angles_rad"])-b["angles_rad"])))
            checks.append({"frame":frame,"offset":offset,"max_angle_error_rad":error,
                           "original_s":elapsed,"fast_s":fast_elapsed,"evaluations_equal":a["evaluations"]==b["evaluations"]})
    result = {"report":_file_binding(path),"original":_file_binding(Path(__file__).parent.parent/"embodied_transport_v1/kinematics.py"),
              "optimized":_file_binding(Path(__file__).parent/"fast_kinematics.py"),"implementation":_file_binding(Path(__file__)),
              "physics_steps":0,"checks":checks,"passed":all(x["max_angle_error_rad"]<=1e-12 and x["evaluations_equal"] for x in checks)}
    save(root/"KINEMATICS_EQUIVALENCE.json",result)
    print({"passed":result["passed"],"checks":len(checks),"max_angle_error_rad":max(x["max_angle_error_rad"] for x in checks),
           "original_s":sum(x["original_s"] for x in checks),"fast_s":sum(x["fast_s"] for x in checks)})

if __name__=="__main__":
    p=argparse.ArgumentParser(); p.add_argument("--root",type=Path,required=True); p.add_argument("--parent",type=Path,required=True)
    a=p.parse_args(); run(a.root,a.parent)
