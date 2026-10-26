"""Zero-step native geometry admission. First failed gate prevents any integration."""

import argparse
from .model import load_model
from pathlib import Path
import numpy as np
from .engine import authorize, setup_hand
from .contacts import contact_pair, observe, foot_metrics
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_semantic_shadow import (
    DEFAULT_ANGLES,
)
from sage.experiments.embodied_data_stability_v1.sonic_supported_shadow import (
    physical_guard,
    PHYSICAL_GATE_NAMES,
)
from sage.experiments.embodied_data_stability_v1 import (
    sonic_native_dynamic_shadow as native,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def run(root):
    import mujoco

    authorize(root)
    if (root / "NATIVE_PREFLIGHT.json").exists():
        raise FileExistsError("preflight already exists")
    case = read_bound_json(root / "CASE.json")
    scene = read_bound_json(root / "model/SCENE.json")
    model = load_model(case["model_path"])
    model.opt.timestep = native.SIMULATION_DT_S
    data = mujoco.MjData(model)
    ids = native._model_ids(mujoco, model)
    data.qpos[ids["qpos_ids"]] = DEFAULT_ANGLES
    data.qpos[:2] = case["start_xy_m"]
    setup_hand(mujoco, model, data, case)
    mujoco.mj_forward(model, data)
    guard = physical_guard(mujoco, model, data, model.body("pelvis").id, np.zeros(6))
    contacts = []
    for i, c in enumerate(data.contact):
        f = np.zeros(6)
        mujoco.mj_contactForce(model, data, i, f)
        contacts.append(
            {
                "pair": contact_pair(model, c),
                "distance_m": float(c.dist),
                "normal_force_n": float(f[0]),
            }
        )
    contacts.sort(key=lambda c: c["distance_m"])
    metrics = observe(mujoco, model, data)
    gates = {k: guard[k] for k in PHYSICAL_GATE_NAMES}
    gates.update(
        no_scene_intersection=not metrics["scene_violation"],
        no_body_fixture_intersection=not metrics["body_fixture_violation"],
        full_official_body=scene["full_official_robot_collision_model"],
        native_triangle_surfaces=scene["native_scene_triangle_collision"],
        all_surfaces_rigid=bool(np.all(model.flex_rigid)),
        no_eq_no_mocap=model.neq == 0 and model.nmocap == 0,
        all_scene_surfaces_present=model.nflex
        == len(scene["native_collision_surfaces"]),
        no_scene_obbs=not any(
            (model.geom(i).name or "").startswith(("scene_proxy_", "room_wall_"))
            for i in range(model.ngeom)
        ),
    )
    result = {
        "schema": "native-full-g1-static-admission/v1",
        "passed": all(gates.values()),
        "gates": gates,
        "physical_guard": guard,
        "contacts": contacts,
        "feet": foot_metrics(mujoco, model, data),
        "payload": metrics,
        "physics_steps": 0,
        "task_passed": False,
        "initial_qpos": data.qpos.tolist(),
        "initial_qvel": data.qvel.tolist(),
        "model": _file_binding(Path(case["model_path"])),
        "case": _file_binding(root / "CASE.json"),
        "protocol": _file_binding(root / "PROTOCOL.json"),
        "implementation": _file_binding(Path(__file__)),
        "next_action": (
            "fresh supported observer admission, then progressive active prefixes"
            if all(gates.values())
            else "stop this round; preserve initial collision evidence, no controller or collision-mask tuning"
        ),
    }
    save(root / "NATIVE_PREFLIGHT.json", result)
    print(
        {
            "passed": result["passed"],
            "failed_gates": [k for k, v in gates.items() if not v],
            "contacts": len(contacts),
            "physical_guard": guard,
            "deepest": contacts[:8],
        },
        flush=True,
    )
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    run(p.parse_args().root)
