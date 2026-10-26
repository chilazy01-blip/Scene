"""Replace only the grasped cylinder in the accepted generated-scene control."""

from __future__ import annotations

import argparse
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable

import numpy as np

from .common import BASE_RUN, RUN_ROOT, SOURCE, sha256, write_json


def _vector(values) -> str:
    return " ".join(f"{float(value):.17g}" for value in values)


def build_model(run_root: Path) -> dict:
    import mujoco

    qa_path = run_root / "object_asset/ASSET_QA.json"
    if not qa_path.is_file():
        raise RuntimeError("generated object asset must pass QA before model binding")
    output = run_root / "model"
    if output.exists():
        raise FileExistsError(output)
    shutil.copytree(BASE_RUN / "model", output)
    # The copied directory contains the base run's validation result.  It is
    # evidence for a different model and must never be mistaken for validation
    # of the generated-object variant.
    stale_validation = output / "STATIC_VALIDATION.json"
    if stale_validation.exists():
        stale_validation.unlink()
    base_model_path = BASE_RUN / "model/MODEL.xml"
    base_model = mujoco.MjModel.from_xml_path(str(base_model_path))
    body_id = mujoco.mj_name2id(
        base_model, mujoco.mjtObj.mjOBJ_BODY, "red_block"
    )
    frozen = {
        "mass_kg": float(base_model.body_mass[body_id]),
        "inertia_kg_m2": base_model.body_inertia[body_id].copy(),
        "inertial_pos_m": base_model.body_ipos[body_id].copy(),
        "inertial_quat_wxyz": base_model.body_iquat[body_id].copy(),
    }

    source_obj = run_root / "object_asset/red_cylinder_normalized.obj"
    target_obj = output / "assets/generated_red_cylinder.obj"
    shutil.copy2(source_obj, target_obj)
    tree = ET.parse(base_model_path)
    root = tree.getroot()
    asset = root.find("asset")
    body = root.find("worldbody/body[@name='red_block']")
    if asset is None or body is None:
        raise RuntimeError("base model is missing asset/red_block sections")
    if asset.find("mesh[@name='generated_red_cylinder_mesh']") is not None:
        raise RuntimeError("generated red cylinder mesh already exists")
    ET.SubElement(
        asset,
        "mesh",
        name="generated_red_cylinder_mesh",
        file="generated_red_cylinder.obj",
    )
    replaced = []
    for child in list(body):
        if child.tag == "inertial" or (
            child.tag == "geom"
            and child.get("name") in {"red_cylinder", "red_cap_top", "red_cap_bot"}
        ):
            replaced.append(child.get("name", "inertial"))
            body.remove(child)
    inertial = ET.Element(
        "inertial",
        pos=_vector(frozen["inertial_pos_m"]),
        quat=_vector(frozen["inertial_quat_wxyz"]),
        mass=f"{frozen['mass_kg']:.17g}",
        diaginertia=_vector(frozen["inertia_kg_m2"]),
    )
    body.insert(0, inertial)
    ET.SubElement(
        body,
        "geom",
        name="red_cylinder",
        type="mesh",
        mesh="generated_red_cylinder_mesh",
        material="red_plastic",
        mass="0",
        contype="1",
        conaffinity="1",
        friction="3 0.1 0.01",
    )
    # Source-A changes friction by these three public geom names. Keep the cap
    # names as inert, non-colliding sentinels so no controller line indexes -1.
    for name in ("red_cap_top", "red_cap_bot"):
        ET.SubElement(
            body,
            "geom",
            name=name,
            type="sphere",
            size="0.000001",
            mass="0",
            rgba="0 0 0 0",
            contype="0",
            conaffinity="0",
            friction="3 0.1 0.01",
        )
    ET.indent(root)
    model_path = output / "MODEL.xml"
    tree.write(model_path, encoding="unicode")
    compiled = mujoco.MjModel.from_xml_path(str(model_path))
    new_body_id = mujoco.mj_name2id(
        compiled, mujoco.mjtObj.mjOBJ_BODY, "red_block"
    )
    mass_error = abs(float(compiled.body_mass[new_body_id]) - frozen["mass_kg"])
    inertia_error = float(
        np.max(
            np.abs(
                compiled.body_inertia[new_body_id]
                - np.asarray(frozen["inertia_kg_m2"])
            )
        )
    )
    report = {
        "schema": "embodied-generated-red-cylinder-model-binding/v1",
        "model_path": str(model_path),
        "model_sha256": sha256(model_path),
        "base_model": str(base_model_path),
        "base_model_sha256": sha256(base_model_path),
        "source_robot_sha256": sha256(SOURCE / "g1.xml"),
        "generated_object_obj": str(target_obj),
        "generated_object_obj_sha256": sha256(target_obj),
        "replaced_elements": replaced,
        "collision_method": (
            "one generated triangle mesh geom; MuJoCo compiled convex hull contact"
        ),
        "controller_name_compatibility": {
            "red_cylinder": "generated colliding mesh",
            "red_cap_top": "1 um noncolliding sentinel",
            "red_cap_bot": "1 um noncolliding sentinel",
        },
        "frozen_object_dynamics": frozen,
        "compiled_mass_abs_error_kg": mass_error,
        "compiled_inertia_max_abs_error_kg_m2": inertia_error,
        "physics_scope": (
            "The accepted generated room, table proxies, G1 robot, hand collision meshes, "
            "controller, spawn draw, mass, inertia and friction remain fixed. Only the red "
            "object visual/collision geometry changes from an analytic cylinder plus caps "
            "to the normalized TRELLIS.2 mesh and its MuJoCo convex hull."
        ),
        "interpretation_boundary": (
            "This run isolates the red object's geometry representation. A large penetration "
            "reduction relative to the v4 generated-scene control implicates the original "
            "object representation; a persistent approximately 28 mm penetration instead "
            "implicates the frozen hand collision shell and/or grasp command."
        ),
        "passed": mass_error <= 1e-15 and inertia_error <= 1e-15,
        "physics_steps": 0,
        "production_accepted": False,
    }
    write_json(output / "BINDING.json", report)
    if not report["passed"]:
        raise RuntimeError(f"object dynamics changed: {report}")
    return report


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, default=RUN_ROOT)
    args = parser.parse_args(argv)
    print(build_model(args.run_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

