"""Static, zero-step contact checks of the exact native floor solid."""

import argparse
from pathlib import Path
import numpy as np
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)
from .preflight import authorize


def run(root):
    import mujoco

    authorize(root)
    if (root / "CONTACT_PROBES.json").exists():
        raise FileExistsError("contact probes already exist")
    scene = read_bound_json(root / "model/SCENE.json")
    rec = scene["native_floor"]["recognition"]
    vec = lambda a: " ".join(str(x) for x in a)
    results = []
    for kind, size, halfheight in (
        ("box", [0.1, 0.05, 0.02], 0.02),
        ("capsule", [0.02, 0.05], 0.07),
        ("sphere", [0.02], 0.02),
        ("cylinder", [0.02, 0.05], 0.05),
    ):
        for clearance in (0.005, 0.0005, -0.0005, -0.002, -0.008):
            z = halfheight + clearance
            xml = f'<mujoco><worldbody><geom name="native_floor" type="box" pos="{vec(rec["center"])}" size="{vec(rec["half_size"])}" contype="2" conaffinity="1" friction=".8 .005 .0001"/><body name="probe" pos="1 2 {z}"><freejoint/><geom name="probe_geom" type="{kind}" size="{vec(size)}" mass="1"/></body></worldbody></mujoco>'
            model = mujoco.MjModel.from_xml_string(xml)
            data = mujoco.MjData(model)
            mujoco.mj_forward(model, data)
            expected = clearance < 0
            normals = []
            forces = []
            for i, c in enumerate(data.contact):
                normal = (
                    1 if int(c.geom[1]) == model.geom("probe_geom").id else -1
                ) * np.array(c.frame[:3])
                f = np.zeros(6)
                mujoco.mj_contactForce(model, data, i, f)
                normals.append(float(normal[2]))
                forces.append(float(f[0]))
            passed = bool(
                (data.ncon > 0) == expected
                and (not expected or (min(normals) > 0.99 and max(forces) > 0))
            )
            results.append(
                {
                    "kind": kind,
                    "bottom_clearance_m": clearance,
                    "expected_contact": expected,
                    "contacts": data.ncon,
                    "upward_normal_z": normals,
                    "normal_forces_n": forces,
                    "passed": passed,
                    "physics_steps": 0,
                }
            )
    result = {
        "schema": "native-floor-contact-regression/v1",
        "passed": all(r["passed"] for r in results),
        "results": results,
        "physics_steps": 0,
        "floor_recognition": rec,
        "scene": _file_binding(root / "model/SCENE.json"),
        "implementation": _file_binding(Path(__file__)),
        "interpretation": "former thin-shell tests included boundary/deep crossing; native floor is a true5cm solid. No global physics flag or robot collider changed; this is static contact validation, not a drop or standing test.",
    }
    save(root / "CONTACT_PROBES.json", result)
    print(
        {
            "static_contact_checks": len(results),
            "passed": result["passed"],
            "failures": [r for r in results if not r["passed"]],
            "physics_steps": 0,
        },
        flush=True,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    run(p.parse_args().root)
