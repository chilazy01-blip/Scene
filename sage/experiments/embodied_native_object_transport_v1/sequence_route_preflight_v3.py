"""Finite FK-only search for a collision-clear post-stop bent-elbow waypoint."""
import argparse
from pathlib import Path
import numpy as np
from .protocol import authorize
from .kinematics_r3 import IK
from .metrics import measure
from .report_safe_engine import safe_save
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding
from sage.experiments.embodied_data_stability_v1 import sonic_native_dynamic_shadow as native

def run(root):
    import mujoco
    out = root / "SEQUENCE_ROUTE_PREFLIGHT_V3.json"
    assert not out.exists()
    p = authorize(root)
    c = read_bound_json(Path(p["case"]["path"]))
    m = load_model(root / "model/model.xml")
    d = mujoco.MjData(m)
    d.qpos[:50] = c["initial_robot_qpos"]
    adr = int(m.joint("payload_free").qposadr[0])
    d.qpos[adr:adr+7] = [*c["source_object_xyz_m"], *c["source_object_quat"]]
    initial = d.qpos.copy()
    ids = native._model_ids(mujoco, m)
    ik = IK(mujoco, m)
    goal = np.asarray(c["ready_arm_target_rad"])
    attempts = []
    selected = None
    for pitch, elbow in ((-.4, 1.6), (-.8, 1.6), (-.8, 1.9), (-1.2, 1.6), (-1.2, 1.9), (-.4, 1.9)):
        middle = initial[ik.qids].copy()
        middle[0], middle[3] = pitch, elbow
        samples = []
        for x in (1.75, 1.80, 1.85, 1.90, 1.95):
            for a,b in ((initial[ik.qids], middle), (middle, goal)):
                for f in np.linspace(0,1,31):
                    d.qpos[:] = initial
                    d.qpos[0] = x
                    d.qpos[ik.qids] = (1-f)*a+f*b
                    mujoco.mj_forward(m,d)
                    s = measure(mujoco,m,d,ids,np.zeros(m.nv),c)
                    samples.append({"x":x,"depth":s["penetration_m"],"forbidden":s["forbidden_contacts"]})
        bad = [s for s in samples if s["forbidden"] or s["depth"]>.01]
        row = {"middle_rad":middle.tolist(),"samples":samples,"bad_count":len(bad),"first_bad":bad[:3],"passed":not bad}
        attempts.append(row)
        print({"pitch":pitch,"elbow":elbow,"bad":len(bad)},flush=True)
        if not bad:
            selected=row
            break
    safe_save(out,{"passed": selected is not None,"selected":selected,"attempts":attempts,
                   "physics_steps":0,"not_dynamic_validation":True,"original_direct_raise_failure":_file_binding(root/"SEQUENCE_PREFLIGHT_V3.json"),
                   "implementation":_file_binding(Path(__file__)),"case":p["case"]})

if __name__ == "__main__":
    ap=argparse.ArgumentParser();ap.add_argument("--root",type=Path,required=True);run(ap.parse_args().root)
