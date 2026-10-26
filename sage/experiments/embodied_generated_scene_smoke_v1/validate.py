"""Compile and validate the generated model without advancing physics."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from .common import RUN_ROOT, SOURCE, SOURCE_CONTRACT, read_json, sha256, write_json
from .runtime import build_custom_sim, geom_label


def _named_max_difference(
    source_model: Any,
    generated_model: Any,
    mujoco: Any,
    object_type: Any,
    field: str,
    names: list[str],
) -> float:
    values = []
    source_array = getattr(source_model, field)
    generated_array = getattr(generated_model, field)
    for name in names:
        left = mujoco.mj_name2id(source_model, object_type, name)
        right = mujoco.mj_name2id(generated_model, object_type, name)
        if min(left, right) < 0:
            raise RuntimeError(f"missing named object during model comparison: {name}")
        values.append(float(np.max(np.abs(source_array[left] - generated_array[right]))))
    return max(values, default=0.0)


def validate(run_root: Path) -> dict[str, Any]:
    import mujoco
    import onnxruntime as ort

    contract = read_json(SOURCE_CONTRACT)
    versions = {
        "mujoco": mujoco.__version__,
        "numpy": np.__version__,
        "onnxruntime": ort.__version__,
    }
    mismatches = {
        key: {"expected": contract["environment"][key], "actual": value}
        for key, value in versions.items()
        if contract["environment"][key] != value
    }
    if mismatches:
        raise RuntimeError(f"runtime version mismatch: {mismatches}")
    sys.path.insert(0, str(SOURCE))
    from ik import pipeline

    model_path = run_root / "model/MODEL.xml"
    source_model = mujoco.MjModel.from_xml_path(str(SOURCE / "scene.xml"))
    generated_model = mujoco.MjModel.from_xml_path(str(model_path))
    if (source_model.nq, source_model.nv, source_model.nu) != (
        generated_model.nq,
        generated_model.nv,
        generated_model.nu,
    ):
        raise RuntimeError("controller-facing model dimensions changed")

    joint_names = [
        mujoco.mj_id2name(source_model, mujoco.mjtObj.mjOBJ_JOINT, index)
        for index in range(source_model.njnt)
    ]
    actuator_names = [
        mujoco.mj_id2name(source_model, mujoco.mjtObj.mjOBJ_ACTUATOR, index)
        for index in range(source_model.nu)
    ]
    robot_body_names = [
        mujoco.mj_id2name(source_model, mujoco.mjtObj.mjOBJ_BODY, index)
        for index in range(1, source_model.nbody)
        if mujoco.mj_id2name(source_model, mujoco.mjtObj.mjOBJ_BODY, index)
        not in {"table", "table_white"}
    ]
    differences = {
        "joint_ranges": _named_max_difference(
            source_model,
            generated_model,
            mujoco,
            mujoco.mjtObj.mjOBJ_JOINT,
            "jnt_range",
            joint_names,
        ),
        "actuator_ctrlrange": _named_max_difference(
            source_model,
            generated_model,
            mujoco,
            mujoco.mjtObj.mjOBJ_ACTUATOR,
            "actuator_ctrlrange",
            actuator_names,
        ),
        "actuator_gainprm": _named_max_difference(
            source_model,
            generated_model,
            mujoco,
            mujoco.mjtObj.mjOBJ_ACTUATOR,
            "actuator_gainprm",
            actuator_names,
        ),
        "robot_and_object_body_mass": _named_max_difference(
            source_model,
            generated_model,
            mujoco,
            mujoco.mjtObj.mjOBJ_BODY,
            "body_mass",
            robot_body_names,
        ),
        "robot_and_object_body_inertia": _named_max_difference(
            source_model,
            generated_model,
            mujoco,
            mujoco.mjtObj.mjOBJ_BODY,
            "body_inertia",
            robot_body_names,
        ),
    }
    if any(value != 0.0 for value in differences.values()):
        raise RuntimeError(f"frozen controller plant changed: {differences}")

    case = read_json(
        Path(
            "/data/wsj/main/scene_runs/codex_trellis_v2/"
            "embodied_data_stability_s3_20261014_v1/source_a_task_smoke_01/CASE_DRAW.json"
        )
    )
    model, data, _controller = build_custom_sim(SOURCE, model_path, case["spawn"])
    geometry = pipeline.randomize_scene(
        model,
        data,
        spawn_yaw=np.radians(case["spawn_yaw_deg"]),
        cyl_xy=case["cyl_xy"],
        cyl_mass_scale=case["cyl_mass_scale"],
        cyl_friction=case["cyl_friction"],
        brown_dz=0.0,
        blue_dz=0.0,
        brown_dxy=(0.0, 0.0),
        blue_dxy=(0.0, 0.0),
    )
    contacts = [
        {
            "pair": [
                geom_label(model, mujoco, int(contact.geom1)),
                geom_label(model, mujoco, int(contact.geom2)),
            ],
            "distance_m": float(contact.dist),
        }
        for contact in data.contact
    ]
    binding = read_json(run_root / "model/BINDING.json")
    result = {
        "schema": "embodied-generated-scene-static-validation/v1",
        "passed": True,
        "physics_steps": 0,
        "runtime_versions": versions,
        "model_dimensions": {
            "nq": model.nq,
            "nv": model.nv,
            "nu": model.nu,
            "nbody": model.nbody,
            "ngeom": model.ngeom,
        },
        "source_model_dimensions": {
            "nq": source_model.nq,
            "nv": source_model.nv,
            "nu": source_model.nu,
            "nbody": source_model.nbody,
            "ngeom": source_model.ngeom,
        },
        "frozen_parameter_max_abs_differences": differences,
        "source_robot_xml_sha256_matches_binding": (
            sha256(SOURCE / "g1.xml") == binding["source_robot_sha256"]
        ),
        "scene_geometry_after_case_initialization": geometry,
        "initial_contacts": contacts,
        "finite_initial_state": bool(
            np.isfinite(data.qpos).all()
            and np.isfinite(data.qvel).all()
            and np.isfinite(data.ctrl).all()
        ),
        "controller_constructed": True,
        "production_accepted": False,
    }
    write_json(run_root / "model/STATIC_VALIDATION.json", result)
    return result


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, default=RUN_ROOT)
    args = parser.parse_args(argv)
    print(validate(args.run_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

