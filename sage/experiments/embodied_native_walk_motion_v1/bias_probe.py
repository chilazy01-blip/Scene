"""Prove collision-free RNE bias reconstruction equals full-forward bias, zero steps."""

import argparse
from pathlib import Path
import numpy as np
from sage.experiments.embodied_native_walk_v1.motion_gate import (
    require_environment_confirmation,
)
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def run(root):
    import mujoco

    require_environment_confirmation(root)
    if (root / "BIAS_RECONSTRUCTION_PROBE.json").exists():
        raise FileExistsError("probe exists")
    scene = read_bound_json(root / "model/SCENE.json")
    pre = read_bound_json(root / "GEOMETRY_PREFLIGHT.json")
    m = load_model(scene["model"]["path"])
    d = mujoco.MjData(m)
    rng = np.random.default_rng(719)
    errors = []
    for scale in (0.0, 0.001, 0.01, 0.05):
        d.qpos[:] = pre["conditions"][0]["initial_qpos"]
        d.qvel[:] = rng.normal(0, scale, m.nv)
        mujoco.mj_forward(m, d)
        expected = d.qfrc_bias.copy()
        mujoco.mj_kinematics(m, d)
        mujoco.mj_comPos(m, d)
        mujoco.mj_comVel(m, d)
        actual = np.zeros(m.nv)
        mujoco.mj_rne(m, d, 0, actual)
        errors.append(float(np.max(np.abs(actual - expected))))
    assert max(errors) < 1e-10
    save(
        root / "BIAS_RECONSTRUCTION_PROBE.json",
        {
            "passed": True,
            "maximum_errors": errors,
            "physics_steps": 0,
            "model": scene["model"],
            "implementation": _file_binding(Path(__file__)),
        },
    )
    print(
        {
            "bias_equivalence_passed": True,
            "maximum_error": max(errors),
            "physics_steps": 0,
        },
        flush=True,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    run(p.parse_args().root)
