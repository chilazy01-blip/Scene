"""Add one user-authorized existing mug, preserving all native room/robot physics."""

import argparse
from pathlib import Path
import time
import xml.etree.ElementTree as ET
from copy import deepcopy
import numpy as np
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)
from sage.experiments.embodied_data_stability_v1.audit_candidates import sha256_file

MUG = Path(
    "/data/wsj/main/scene_runs/codex_trellis_v2/assets_curated_v1/optimized/mug_white_001.glb"
)
REGISTRY = Path(
    "sage/experiments/codex_trellis_scene_v2/capabilities/pilot_desk_mug_v1.json"
)


def run(root, parent):
    import mujoco
    import trimesh
    import os
    import resource

    resource.setrlimit(resource.RLIMIT_AS, (16 * 1024**3, 16 * 1024**3))
    os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:8])
    assert not root.exists()
    root.mkdir(parents=True)
    start = time.monotonic()
    original = read_bound_json(parent / "model/SCENE.json")
    for b in [original["model"], *original["assets"], *original["sources"].values()]:
        assert sha256_file(Path(b["path"])) == b["sha256"]
    save(
        root / "PLAN.json",
        {
            "schema": "native-task-level-mug-plan/v1",
            "user_authorization": "可以，我记得现有资产里有杯子和书，具体选取哪个由你决定",
            "acceptance_change_authorization": "task completed + visually acceptable + no substantial physical abnormality; do not block all deeper tasks on minor raw target excess; preserve old results",
            "purpose": "transfer full-body data-collection capability from simplified props to actual generated furniture and full official G1",
            "parent_native_scene": _file_binding(parent / "model/SCENE.json"),
            "parent_walk_result": _file_binding(parent / "PARTIAL_REVIEW_FINAL.json"),
            "selected_asset": _file_binding(MUG),
            "registry": _file_binding(REGISTRY.resolve()),
            "furniture_or_room_changes_allowed": False,
            "additional_task_fixtures_allowed": False,
            "object_weld_or_state_teleport_allowed": False,
            "free_root_external_support_allowed": False,
            "max_new_physics_steps_including_audits": 40000,
            "prior_native_stage_steps": 18059,
            "cumulative_native_step_cap": 60000,
            "max_causal_control_versions": 2,
            "wall_budget_s": 7200,
            "deadline_utc": "2026-10-21 07:13:58 UTC",
            "task": "empty-hand approach native desk, pick up free mug, carry with actual steps >=0.25m, set down elsewhere on same original native desk, release/retract and both settle",
            "scope": "one development task; not generalization, visual perception autonomy, training or production qualification",
            "exit": "task complete plus video/evidence/export, or declared budget/causal-version cap; no repeated identical failed episodes",
        },
    )
    modeldir = root / "model"
    modeldir.mkdir()
    xml = ET.parse(original["model"]["path"]).getroot()
    # Trimesh dump applies glTF node transforms. Canonical asset dimensions from
    # the existing capability registry; Y-up -> Z-up, no per-grasp resizing.
    scene = trimesh.load(MUG, force="scene")
    mesh = (
        scene.to_geometry()
        if hasattr(scene, "to_geometry")
        else scene.dump(concatenate=True)
    )
    raw_vertices = np.asarray(mesh.vertices).copy()
    vertices = raw_vertices[:, [0, 2, 1]].copy()
    vertices[:, 1] *= -1
    bounds = np.array([vertices.min(0), vertices.max(0)])
    desired = np.array([0.12, 0.09, 0.11])
    scale = desired / (bounds[1] - bounds[0])
    vertices = (vertices - bounds.mean(0)) * scale
    faces = np.asarray(mesh.faces, dtype=np.int32)
    normalized = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    obj = modeldir / "mug_white_001.obj"
    normalized.export(obj)
    np.savez_compressed(modeldir / "MUG_GEOMETRY.npz", vertices=vertices, faces=faces)
    ET.SubElement(
        xml.find("asset"), "mesh", name="native_mug_visual_mesh", file=str(obj)
    )
    body = ET.SubElement(
        xml.find("worldbody"), "body", name="payload", pos="2.15 2.10 .9"
    )
    ET.SubElement(body, "freejoint", name="payload_free")
    mass = 0.15
    inertia = (
        mass
        * np.array(
            [
                desired[1] ** 2 + desired[2] ** 2,
                desired[0] ** 2 + desired[2] ** 2,
                desired[0] ** 2 + desired[1] ** 2,
            ]
        )
        / 12
    )
    ET.SubElement(
        body,
        "inertial",
        pos="0 0 0",
        mass=str(mass),
        diaginertia=" ".join(map(str, inertia)),
    )
    ET.SubElement(
        body,
        "geom",
        name="payload_visual",
        type="mesh",
        mesh="native_mug_visual_mesh",
        contype="0",
        conaffinity="0",
        group="1",
        rgba=".94 .94 .91 1",
        mass="0",
    )
    flex = ET.SubElement(
        xml.find("deformable"),
        "flex",
        name="payload_surface",
        dim="2",
        body="payload",
        vertex=" ".join(format(float(v), ".12g") for v in vertices.ravel()),
        element=" ".join(str(int(i)) for i in faces.ravel()),
        radius=".001",
        group="5",
        rgba="0 0 0 0",
    )
    ET.SubElement(
        flex,
        "contact",
        selfcollide="none",
        internal="false",
        contype="4",
        conaffinity="3",
        friction=".8 .005 .0001",
        condim="3",
    )
    path = modeldir / "model.xml"
    path.write_text(ET.tostring(xml, encoding="unicode"))
    print(
        {
            "phase": "compiling",
            "cup_triangles": len(faces),
            "cup_dims_m": desired.tolist(),
        },
        flush=True,
    )
    model = mujoco.MjModel.from_xml_path(str(path))
    previous = load_model(original["model"]["path"])
    assert (model.nq, model.nv, model.nu, model.neq, model.nmocap, model.nflex) == (
        57,
        55,
        43,
        0,
        0,
        29,
    )
    for key in ("jnt_range", "dof_damping", "dof_armature", "dof_frictionloss"):
        np.testing.assert_array_equal(
            getattr(previous, key), getattr(model, key)[: len(getattr(previous, key))]
        )
    for key in ("actuator_ctrlrange", "actuator_gainprm", "actuator_biasprm"):
        np.testing.assert_array_equal(getattr(model, key), getattr(previous, key))
    for bid in range(previous.nbody):
        name = previous.body(bid).name
        target = model.body(name).id
        for key in (
            "body_pos",
            "body_quat",
            "body_mass",
            "body_inertia",
            "body_ipos",
            "body_iquat",
        ):
            np.testing.assert_array_equal(
                getattr(previous, key)[bid], getattr(model, key)[target]
            )
    mujoco.mj_saveModel(model, str(modeldir / "model.mjb"), None)
    save(
        modeldir / "CACHE.json",
        {
            "xml": _file_binding(path),
            "binary": _file_binding(modeldir / "model.mjb"),
            "mujoco_version": mujoco.__version__,
        },
    )
    result = deepcopy(original)
    result.update(
        schema="native-task-mug-scene/v1",
        model=_file_binding(path),
        parent=_file_binding(parent / "model/SCENE.json"),
        no_payload=False,
        no_task_fixtures=True,
        no_layout_changes=True,
        implementation=_file_binding(Path(__file__)),
        physics_steps=0,
        task_passed=False,
    )
    result["assets"] += [
        _file_binding(obj),
        _file_binding(MUG),
        _file_binding(modeldir / "MUG_GEOMETRY.npz"),
    ]
    result["compiled_model_cache"] = _file_binding(modeldir / "CACHE.json")
    result["task_object"] = {
        "asset_id": "mug_white_001",
        "source": _file_binding(MUG),
        "dimensions_m": desired.tolist(),
        "mass_kg": mass,
        "mass_and_inertia_are_explicit_task_assumptions_not_measured": True,
        "inertia": "uniform bbox inertia approximation, geometry collision is not bbox",
        "geometry": "all original 39999 triangles rigidly attached to free body, includes rim/cavity/handle; no whole-cup convex hull or cylinder proxy",
        "body": "payload",
        "flex": "payload_surface",
        "source_vertex_count": len(raw_vertices),
        "collision_vertex_count": len(vertices),
        "triangle_count": len(faces),
        "normalization": {
            "axis_mapping": "x,-z,y (glTF Y-up to Z-up)",
            "scale": scale.tolist(),
            "canonical_dimensions_from_existing_registry": True,
        },
        "surface_shell_radius_m": 0.001,
        "friction": [0.8, 0.005, 0.0001],
    }
    result["limitations"] += [
        "mug source mesh is not watertight; exact rigid triangle surface plus 1mm contact shell, no claim of watertight solid ceramic",
        "empty mug assumed150g; physical parameters declared rather than measured",
    ]
    save(modeldir / "SCENE.json", result)
    print(
        {
            "model": str(path),
            "dims": [model.nq, model.nv, model.nu],
            "wall_s": time.monotonic() - start,
            "physics_steps": 0,
        },
        flush=True,
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--parent", type=Path, required=True)
    a = ap.parse_args()
    run(a.root, a.parent)
