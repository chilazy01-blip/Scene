"""Zero-integration geometry checks for neutral approach and post-stop arm raise."""

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
    output = root / "SEQUENCE_PREFLIGHT_V3.json"
    assert not output.exists()
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
    samples = []

    def record(phase, fit=None):
        mujoco.mj_forward(m, d)
        s = measure(mujoco, m, d, ids, np.zeros(m.nv), c)
        samples.append({"phase": phase, "root": d.qpos[:3].tolist(),
                        "depth_m": s["penetration_m"], "forbidden": s["forbidden_contacts"],
                        "ik": fit})

    for x in np.linspace(c["start_xy_m"][0], 2.0, 35):
        d.qpos[:] = initial
        d.qpos[0] = x
        record("neutral_approach")
    # Conservative range around nominal stopping position; FK only, never mj_step.
    for x in (1.80, 1.85, 1.90, 1.95, 2.0):
        d.qpos[:] = initial
        d.qpos[0] = x
        result = ik.solve(d.qpos, d.qpos[:3] + c["ready_arm_relative_m"], np.eye(3), 150)
        arm0 = d.qpos[ik.qids].copy()
        for f in np.linspace(0, 1, 31):
            d.qpos[ik.qids] = (1-f)*arm0 + f*np.asarray(result["angles_rad"])
            record("raise_after_stop", result)
    bad = [s for s in samples if s["forbidden"] or s["depth_m"] > .01
           or (s["ik"] and (s["ik"]["position_error_m"] > .01 or s["ik"]["orientation_error_rad"] > .05))]
    result = {"passed": not bad, "physics_steps": 0, "samples": samples, "bad": bad,
              "not_dynamic_validation": True, "case": p["case"], "implementation": _file_binding(Path(__file__))}
    safe_save(output, result)
    print({"passed": not bad, "samples": len(samples), "bad": bad[:3]}, flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    run(ap.parse_args().root)
