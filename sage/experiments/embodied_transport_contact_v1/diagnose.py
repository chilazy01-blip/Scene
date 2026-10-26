"""Preregistered isolated contact counterfactuals; never transport positives."""

import argparse
import copy
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding


def run(root, parent):
    import mujoco
    root.mkdir(parents=True, exist_ok=False)
    report = read_bound_json(parent / "attempt_01/active_1000/REPORT.json")
    trace = read_bound_json(Path(report["trace"]["path"]))
    rows = [r for r in trace["records"] if r["sonic_candidate_consumed_by_physics"]]
    source = mujoco.MjModel.from_xml_path(report["model"]["path"])
    source.opt.timestep = .005
    tree = ET.parse(report["model"]["path"]).getroot()
    xml = ET.Element("mujoco", model="isolated_actual_payload_support")
    ET.SubElement(xml, "compiler", angle="radian")
    world = ET.SubElement(xml, "worldbody")
    payload = tree.find(".//body[@name='payload']")
    if payload is None:
        payload = next(b for b in tree.findall(".//body") if b.find("freejoint[@name='payload_free']") is not None or b.find("joint[@name='payload_free']") is not None)
    target = next(b for b in tree.findall(".//body") if b.find("geom[@name='task_target_support']") is not None)
    for element in (payload, target):
        world.append(copy.deepcopy(element))
    modelpath = root / "isolated.xml"
    modelpath.write_text(ET.tostring(xml, encoding="unicode"))
    model = mujoco.MjModel.from_xml_path(str(modelpath))
    for attr in dir(source.opt):
        if attr.startswith("_"):
            continue
        value = getattr(source.opt, attr)
        if isinstance(value, np.ndarray):
            getattr(model.opt, attr)[:] = value
        elif isinstance(value, (int, float)):
            setattr(model.opt, attr, value)
    assert model.nq == 7 and model.nv == 6 and model.nu == 0
    for name in ("payload_geom", "task_target_support", "task_target_shaft", "task_target_base"):
        a, b = source.geom(name).id, model.geom(name).id
        for attr in ("geom_size", "geom_pos", "geom_quat", "geom_friction", "geom_solref", "geom_solimp", "geom_condim", "geom_margin", "geom_gap"):
            np.testing.assert_array_equal(getattr(source, attr)[a], getattr(model, attr)[b])
    a, b = source.geom("payload_geom").bodyid[0], model.geom("payload_geom").bodyid[0]
    for attr in ("body_mass", "body_inertia", "body_ipos", "body_iquat"):
        np.testing.assert_array_equal(getattr(source, attr)[a], getattr(model, attr)[b])
    profiles = [("default", 0, 0), ("multiccd", 16, 0), ("elliptic", 0, 1), ("multiccd_elliptic", 16, 1)]
    frames = [662, 827]
    protocol = {
        "schema": "isolated-contact-diagnostic/v1", "implementation": _file_binding(Path(__file__)),
        "report": _file_binding(parent / "attempt_01/active_1000/REPORT.json"),
        "trace": report["trace"], "source_model": report["model"], "isolated_model": _file_binding(modelpath),
        "profiles": profiles, "actual_initial_frames": frames, "steps_per_case": 400,
        "max_physics_steps": 3200, "timestep_s": .005,
        "selection": "first nondefault profile with both last100-step instantaneous speeds<=.02m/s, all support, up>=.97, XY drift<=.005m; otherwise none",
        "controller_commands": 0, "task_positive_eligible": False,
        "isolation": "actual free payload + actual static target fixture only, verified identical compiled geometry/inertia/contact parameters; original global options, except declared profile flags/cone; actual released qpos/qvel/warmstart used solely as diagnostic initial conditions",
    }
    save(root / "DIAGNOSTIC_PROTOCOL.json", protocol)
    qid = int(source.joint("payload_free").qposadr[0])
    vid = int(source.joint("payload_free").dofadr[0])
    outcomes = []
    for name, flags, cone in profiles:
        model.opt.enableflags = flags
        model.opt.cone = cone
        for frame in frames:
            s = rows[frame]["substeps"][-1]
            d = mujoco.MjData(model)
            d.qpos[:] = s["full_qpos_after"][qid:qid+7]
            d.qvel[:] = s["full_qvel_after"][vid:vid+6]
            d.qacc_warmstart[:] = s["qacc_warmstart_after"][vid:vid+6]
            origin = d.qpos[:3].copy()
            samples = []
            for step in range(400):
                mujoco.mj_step(model, d)
                mujoco.mj_forward(model, d)
                normal = 0.
                for i, c in enumerate(d.contact):
                    if set((model.geom(c.geom1).name, model.geom(c.geom2).name)) == {"payload_geom", "task_target_support"}:
                        f = np.zeros(6)
                        mujoco.mj_contactForce(model, d, i, f)
                        normal += max(0., f[0])
                samples.append({"step": step, "qpos": d.qpos.tolist(), "qvel": d.qvel.tolist(),
                                "speed_m_s": float(np.linalg.norm(d.qvel[:3])), "up": float(d.xmat[b].reshape(3,3)[2,2]),
                                "support_force_n": normal, "xy_drift_m": float(np.linalg.norm(d.qpos[:2]-origin[:2]))})
            tail = samples[-100:]
            passed = all(x["speed_m_s"] <= .02 and x["support_force_n"] > .01 and x["up"] >= .97 and x["xy_drift_m"] <= .005 for x in tail)
            outcomes.append({"profile": name, "frame": frame, "passed": passed,
                             "tail_peak_speed_m_s": max(x["speed_m_s"] for x in tail),
                             "tail_max_drift_m": max(x["xy_drift_m"] for x in tail), "samples": samples})
            print({k:v for k,v in outcomes[-1].items() if k != "samples"}, flush=True)
    eligible = [name for name,_,_ in profiles[1:] if all(x["passed"] for x in outcomes if x["profile"] == name)]
    save(root / "DIAGNOSTIC_RESULT.json", {"protocol": _file_binding(root / "DIAGNOSTIC_PROTOCOL.json"), "physics_steps": 3200,
         "selected_profile": eligible[0] if eligible else None, "outcomes": outcomes, "task_passed": False})


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--parent", type=Path, required=True)
    a = p.parse_args()
    run(a.root, a.parent)
