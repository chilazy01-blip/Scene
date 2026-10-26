"""Freeze real motion protocol only after the actual environment confirmation."""

import argparse
from pathlib import Path
import sys
import numpy as np
from . import engine, audit, reference, metrics, attempt
from sage.experiments.embodied_native_walk_v1.motion_gate import (
    require_environment_confirmation,
    require_motion_protocol,
)
from sage.experiments.embodied_native_walk_v1.acceptance_v1 import LIMITS
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.audit_candidates import sha256_file
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_full_shadow import (
    _make_session,
)
from sage.experiments.embodied_data_stability_v1 import (
    sonic_native_dynamic_shadow as native,
)
from sage.experiments.embodied_locomotion_v1.reference import walking


def prepare(root):
    import mujoco
    import onnxruntime
    import resource
    import os

    resource.setrlimit(resource.RLIMIT_AS, (16 * 1024**3, 16 * 1024**3))
    os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:8])

    approved = require_environment_confirmation(root)
    plan = approved["plan"]
    if (root / "MOTION_PROTOCOL.json").exists():
        raise FileExistsError("motion protocol already frozen")
    pre = read_bound_json(root / "GEOMETRY_PREFLIGHT.json")
    assert pre["passed"] and len(pre["conditions"]) == 3
    assert read_bound_json(root / "BIAS_RECONSTRUCTION_PROBE.json")["passed"]
    inputs = {}
    for name, relative, digest in (
        (
            "planner",
            "planner/target_vel/V2/planner_sonic.onnx",
            native.EXPECTED_PLANNER_SHA256,
        ),
        (
            "encoder",
            "policy/sonic_v1_1/model_encoder.onnx",
            native.EXPECTED_ENCODER_SHA256,
        ),
        (
            "decoder",
            "policy/sonic_v1_1/model_decoder.onnx",
            native.EXPECTED_DECODER_SHA256,
        ),
    ):
        path = native.DEFAULT_BUNDLE / relative
        if sha256_file(path) != digest:
            raise ValueError("official NN model changed")
        inputs[name] = _file_binding(path)
    planner = _make_session(Path(inputs["planner"]["path"]))
    q, v, meta = walking(planner)
    del planner
    np.savez_compressed(root / "WALK_REFERENCE_BASE.npz", q=q, v=v)
    save(
        root / "WALK_REFERENCE_META.json",
        {
            **meta,
            "implementation": _file_binding(Path(walking.__code__.co_filename)),
            "physics_steps": 0,
        },
    )
    cases = root / "motion_cases"
    cases.mkdir(exist_ok=False)
    case_bindings = {}
    for c in pre["conditions"]:
        case = {
            k: c[k]
            for k in (
                "id",
                "start_xy_m",
                "start_yaw_deg",
                "goal_xy_m",
                "initial_qpos",
                "corridor_min_radius_m",
            )
        }
        case.update(
            source_role="development_validation",
            dataset_split="unassigned",
            scene=_file_binding(root / "model/SCENE.json"),
        )
        save(cases / (c["id"] + ".json"), case)
        case_bindings[c["id"]] = _file_binding(cases / (c["id"] + ".json"))
    local = Path(__file__).resolve().parents[3]
    paths = set(
        Path(m.__file__).resolve()
        for m in list(sys.modules.values())
        if getattr(m, "__file__", None)
        and str(m.__file__).endswith(".py")
        and str(Path(m.__file__).resolve()).startswith(str(local))
    )
    paths.update(Path(__file__).parent.glob("*.py"))
    dependencies = {
        str(f): _file_binding(f)
        for f in sorted(paths)
        if f.is_file() and not f.name.startswith("test")
    }
    for key, b in {
        **inputs,
        **case_bindings,
        "reference_base": _file_binding(root / "WALK_REFERENCE_BASE.npz"),
        "reference_meta": _file_binding(root / "WALK_REFERENCE_META.json"),
        "bias_probe": _file_binding(root / "BIAS_RECONSTRUCTION_PROBE.json"),
        "contract_tests": _file_binding(root / "MOTION_CONTRACT_TESTS.xml"),
    }.items():
        dependencies["data:" + key] = b
    p = {
        "schema": "native-room-real-walk-protocol/v1",
        "environment_approval": _file_binding(root / "ENVIRONMENT_APPROVAL.json"),
        "plan": _file_binding(root / "PLAN.json"),
        "scene": _file_binding(root / "model/SCENE.json"),
        "max_total_physics_steps": plan["future_max_total_physics_steps"],
        "max_causal_versions": plan["future_max_causal_controller_versions"],
        "conditions": plan["conditions_to_preflight"],
        "case_bindings": case_bindings,
        "active_budgets_ticks": [100, 300, 750, 1500],
        "per_process_wall_s": 900,
        "brake_ticks": 55,
        "inputs": inputs,
        "reference_base": _file_binding(root / "WALK_REFERENCE_BASE.npz"),
        "dependencies": dependencies,
        "acceptance_limits": dict(LIMITS),
        "official_motor_arrays": native.official_control_arrays(),
        "runtime": {
            "mujoco": mujoco.__version__,
            "onnxruntime": onnxruntime.__version__,
            "raw_model_default_dt_s": 0.002,
            "declared_original_SONIC_execution_dt_s": 0.005,
            "control_dt_s": 0.02,
        },
        "control_contract": "original SONIC29 body output, official PD/effort; independent neutral14finger native-range PD; no extra external support in warmup/observer/active",
        "baseline": "observer uses constant official learned initial idle pose and motor-only qfrc_bias feedforward; not a standing success; active has no feedforward and no applied qfrc/xfrc",
        "finite_exit": "first rejection per case stops v1; no repeated failed case, no geometry changes, all stages and costs preserved; any later causal revision must have independent source/protocol and share global60000step cap",
        "implementation": _file_binding(Path(__file__)),
        "physics_steps_before_protocol": 0,
    }
    save(root / "MOTION_PROTOCOL.json", p)
    require_motion_protocol(root)
    print(
        {
            "motion_protocol_frozen": True,
            "cases": list(case_bindings),
            "reference_frames": len(q),
            "dependencies": len(dependencies),
            "physics_steps": 0,
        },
        flush=True,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    prepare(p.parse_args().root)
