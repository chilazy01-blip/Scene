"""Remove old task props; preserve every original room surface and robot geom."""

import argparse
from copy import deepcopy
from pathlib import Path
import xml.etree.ElementTree as ET
import resource
import os
import time
import numpy as np
from .geometry import exact_axis_aligned_box
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.audit_candidates import sha256_file
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def prepare(root, parent):
    import mujoco
    import trimesh

    resource.setrlimit(resource.RLIMIT_AS, (16 * 1024**3, 16 * 1024**3))
    os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:8])
    began = time.monotonic()
    if root.exists():
        raise FileExistsError(root)
    modeldir = root / "model"
    modeldir.mkdir(parents=True)
    old = read_bound_json(parent / "model/SCENE.json")
    for b in [old["model"], *old["assets"], *old["sources"].values()]:
        if sha256_file(Path(b["path"])) != b["sha256"]:
            raise ValueError("source asset changed")
    xml = ET.parse(old["model"]["path"]).getroot()
    world = xml.find("worldbody")
    removed = []
    for parent_node in xml.iter():
        for node in list(parent_node):
            if node.tag == "body" and (
                node.get("name", "").startswith("task_")
                or node.get("name") == "payload"
            ):
                removed.append(ET.tostring(node, encoding="unicode"))
                parent_node.remove(node)
    deformable = xml.find("deformable")
    floor = deformable.find("flex[@name='native_floor']")
    floor_source = next(
        s for s in old["native_collision_surfaces"] if s["name"] == "native_floor"
    )
    mesh = trimesh.load(floor_source["source"]["path"], force="mesh", process=False)
    recognition = exact_axis_aligned_box(mesh.vertices, mesh.faces)
    deformable.remove(floor)

    def vec(a):
        return " ".join(format(float(x), ".12g") for x in a)

    ET.SubElement(
        world,
        "geom",
        name="native_floor",
        type="box",
        pos=vec(recognition["center"]),
        size=vec(recognition["half_size"]),
        contype="2",
        conaffinity="1",
        friction=".8 .005 .0001",
        rgba="0 0 0 0",
        group="5",
    )
    # Render-only categorization lets a cutaway inspection show the room without changing physics.
    for g in xml.findall(".//geom"):
        name = g.get("name", "")
        if name.startswith("scene_visual_"):
            index = int(name.split("_")[2])
            g.set("group", "3" if index in (0, 24, 27, 30, 33, 36) else "4")
    modelpath = modeldir / "model.xml"
    modelpath.write_text(ET.tostring(xml, encoding="unicode"))
    model = mujoco.MjModel.from_xml_path(str(modelpath))
    previous = load_model(old["model"]["path"])
    assert (model.nq, model.nv, model.nu, model.neq, model.nmocap) == (50, 49, 43, 0, 0)
    assert model.nflex == 28 and np.all(model.flex_rigid)
    robot_checks = 0
    for item in old["robot_restored_geoms"]:
        a = model.body(item["body"]).id
        b = previous.body(item["body"]).id
        for key in (
            "body_mass",
            "body_inertia",
            "body_ipos",
            "body_iquat",
            "body_pos",
            "body_quat",
        ):
            np.testing.assert_array_equal(
                getattr(model, key)[a], getattr(previous, key)[b]
            )
        for geom in xml.findall(".//body[@name='" + item["body"] + "']/geom"):
            i = model.geom(geom.get("name")).id
            j = previous.geom(geom.get("name")).id
            for key in (
                "geom_type",
                "geom_size",
                "geom_pos",
                "geom_quat",
                "geom_contype",
                "geom_conaffinity",
                "geom_friction",
                "geom_solref",
                "geom_solimp",
            ):
                np.testing.assert_array_equal(
                    getattr(model, key)[i], getattr(previous, key)[j]
                )
            robot_checks += 1
    for key in ("jnt_range", "dof_damping", "dof_armature", "dof_frictionloss"):
        a = getattr(model, key)
        b = getattr(previous, key)
        # Deleted payload freejoint is last; all robot DOFs and joint ranges are unchanged.
        np.testing.assert_array_equal(a, b[: len(a)])
    np.testing.assert_array_equal(model.actuator_ctrlrange, previous.actuator_ctrlrange)
    for item in old["native_collision_surfaces"]:
        if item["name"] == "native_floor":
            continue
        f = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_FLEX, item["name"])
        g = mujoco.mj_name2id(previous, mujoco.mjtObj.mjOBJ_FLEX, item["name"])
        assert (
            model.flex_vertnum[f] == previous.flex_vertnum[g]
            and model.flex_elemnum[f] == previous.flex_elemnum[g]
        )
        av = int(model.flex_vertadr[f])
        bv = int(previous.flex_vertadr[g])
        n = int(model.flex_vertnum[f])
        np.testing.assert_array_equal(
            model.flex_vert[av : av + n], previous.flex_vert[bv : bv + n]
        )
        ae = int(model.flex_elemdataadr[f])
        be = int(previous.flex_elemdataadr[g])
        n = int(model.flex_elemnum[f]) * 3
        np.testing.assert_array_equal(
            model.flex_elem[ae : ae + n], previous.flex_elem[be : be + n]
        )
        np.testing.assert_array_equal(model.flex_contype[f], previous.flex_contype[g])
        np.testing.assert_array_equal(
            model.flex_conaffinity[f], previous.flex_conaffinity[g]
        )
    for b in model.body_pos:
        assert np.isfinite(b).all()
    binary = modeldir / "model.mjb"
    mujoco.mj_saveModel(model, str(binary), None)
    save(
        modeldir / "CACHE.json",
        {
            "xml": _file_binding(modelpath),
            "binary": _file_binding(binary),
            "mujoco_version": mujoco.__version__,
            "implementation": _file_binding(Path(__file__)),
            "physics_steps": 0,
        },
    )
    limitations = [
        "official robot collision model includes convexified link meshes, not nonconvex per-triangle robot collision",
        "furniture/wall/door/window surfaces use fixed rigid triangle shells of1mm radius; finite-step contact, static furniture and door",
        "native floor source is an exact closed cuboid; same-volume box conversion proven from all vertices/faces, not an added support plane",
        "render cutaways hide walls for inspection only; physical walls and all opening surfaces remain enabled",
        "one generated study/development source only; no held-out or learning-benefit claim",
    ]
    scene = {
        "schema": "native-generated-room-full-g1-walk/v1",
        "scene_id": "S01r2_native_study",
        "room": old["room"],
        "obstacles": old["obstacles"],
        "model": _file_binding(modelpath),
        "compiled_model_cache": _file_binding(modeldir / "CACHE.json"),
        "sources": old["sources"],
        "assets": old["assets"],
        "parent": _file_binding(parent / "model/SCENE.json"),
        "official_robot_model": old["official_robot_model"],
        "official_robot_meshes": old["official_robot_meshes"],
        "robot_restored_geoms": old["robot_restored_geoms"],
        "native_collision_surfaces": [
            s for s in old["native_collision_surfaces"] if s["name"] != "native_floor"
        ],
        "native_floor": {
            "source": floor_source["source"],
            "source_visual": "scene_visual_0_0",
            "collision_geom": "native_floor",
            "recognition": recognition,
        },
        "removed_non_native_task_bodies_xml": removed,
        "no_task_fixtures": True,
        "no_payload": True,
        "no_layout_changes": True,
        "no_visual_mesh_changes": True,
        "all_official_robot_geoms_retained": True,
        "robot_geoms_compared": robot_checks,
        "furniture_and_architecture_triangles_unchanged": True,
        "physics_steps": 0,
        "task_passed": False,
        "limitations": limitations,
        "implementation": _file_binding(Path(__file__)),
        "build_wall_s": time.monotonic() - began,
    }
    save(modeldir / "SCENE.json", scene)
    protocol = {
        "schema": "native-walk-qualification-plan/v1",
        "scene": _file_binding(modeldir / "SCENE.json"),
        "canonical_xml": _file_binding(modelpath),
        "cache": _file_binding(modeldir / "CACHE.json"),
        "mode": "ENVIRONMENT_CONFIRMATION_PENDING_NO_MJ_STEP",
        "acceptance": {
            "unsupported_initial_stand_s": 10.0,
            "actual_walk_min_m": 1.0,
            "final_stand_s": 5.0,
            "all_predeclared_conditions_pass": 3,
            "no_fall_penetration_or_furniture_support": True,
            "original_motor_and_safety_limits_unchanged": True,
        },
        "physical_steps_this_phase": 0,
        "future_max_total_physics_steps": 60000,
        "future_max_causal_controller_versions": 2,
        "budget_scope": "future exact dynamic protocol required after scene approval; stop on first failure per fixed case, no repeated failed case, no per-scene parameter search",
        "conditions_to_preflight": [
            {"id": "A", "start_xy_m": [0.85, 2.8], "start_yaw_deg": 0.0},
            {"id": "B", "start_xy_m": [0.85, 3.15], "start_yaw_deg": -5.0},
            {"id": "C", "start_xy_m": [0.9, 2.85], "start_yaw_deg": 5.0},
        ],
        "route_goal_distance_m": 1.15,
        "route_extra_stop_envelope_m": 0.30,
        "minimum_corridor_radius_m": 0.40,
        "source_role": "development_validation",
        "dataset_split": "unassigned",
        "held_out_evaluation": False,
        "dependencies": {
            f.name: _file_binding(f)
            for f in sorted(Path(__file__).parent.glob("*.py"))
            if not f.name.startswith("test")
        },
        "reused_frozen_dependencies": {
            str(f): _file_binding(f)
            for f in [
                Path(load_model.__code__.co_filename),
                Path(save.__code__.co_filename),
            ]
        },
        "implementation": _file_binding(Path(__file__)),
    }
    save(root / "PLAN.json", protocol)
    print(
        {
            "root": str(root),
            "native_surfaces": 29,
            "unchanged_triangle_surfaces": model.nflex,
            "robot_geoms_unchanged": robot_checks,
            "removed_task_bodies": len(removed),
            "physics_steps": 0,
            "build_wall_s": time.monotonic() - began,
        },
        flush=True,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--parent", type=Path, required=True)
    a = p.parse_args()
    prepare(a.root, a.parent)
