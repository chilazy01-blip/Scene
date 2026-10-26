"""Restore every official robot geom and native static triangle surface."""

import argparse
from copy import deepcopy
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)
from sage.experiments.embodied_data_stability_v1.audit_candidates import sha256_file
from sage.experiments.embodied_data_stability_v1.sonic_walk_official_model import (
    OFFICIAL_MODEL,
)

LOCAL_MESHES = Path(
    "/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/feasibility_guard_v4/prepared/hmg_external_control_20261007/source/humanoidmimicgen-d82844dcec242c82d6b82628ccc45933c3ad5cbd/humanoidmimicgen/wbc/robot_model/model_data/g1/meshes"
)


def prepare(root, parent):
    import mujoco
    import trimesh
    import os
    import resource

    resource.setrlimit(resource.RLIMIT_AS, (16 * 1024**3, 16 * 1024**3))
    os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:8])
    if root.exists():
        raise FileExistsError(root)
    modeldir = root / "model"
    modeldir.mkdir(parents=True)
    scene = read_bound_json(parent / "model/SCENE.json")
    for binding in [scene["model"], *scene["assets"], *scene["sources"].values()]:
        if sha256_file(Path(binding["path"])) != binding["sha256"]:
            raise ValueError("changed source asset")
    xml = ET.parse(scene["model"]["path"]).getroot()
    official = ET.parse(OFFICIAL_MODEL).getroot()
    asset = xml.find("asset")
    robot_assets = []
    for mesh in official.findall("asset/mesh"):
        pointer = OFFICIAL_MODEL.parent / "meshes" / mesh.get("file")
        expected = next(
            line.split("sha256:")[1]
            for line in pointer.read_text().splitlines()
            if line.startswith("oid ")
        )
        local = LOCAL_MESHES / mesh.get("file")
        if sha256_file(local) != expected:
            raise ValueError(
                "local robot mesh not exact official LFS object: " + str(local)
            )
        previous = asset.find("mesh[@name='" + mesh.get("name") + "']")
        if previous is not None:
            asset.remove(previous)
        node = deepcopy(mesh)
        node.set("file", str(local))
        asset.append(node)
        robot_assets.append(
            {
                "name": mesh.get("name"),
                "official_pointer": _file_binding(pointer),
                "source": _file_binding(local),
                "official_oid": expected,
            }
        )
    restored = []
    for source_body in official.findall(".//body"):
        body = xml.find(".//body[@name='" + source_body.get("name") + "']")
        if body is None:
            raise ValueError("missing robot body")
        for geom in list(body.findall("geom")):
            body.remove(geom)
        for i, source_geom in enumerate(source_body.findall("geom")):
            geom = deepcopy(source_geom)
            geom.set("name", f"robot_{source_body.get('name')}_{i}")
            body.append(geom)
        restored.append(
            {"body": source_body.get("name"), "geoms": len(source_body.findall("geom"))}
        )
    removed = []
    for body in [xml.find("worldbody"), *xml.findall(".//body")]:
        for geom in list(body.findall("geom")):
            name = geom.get("name", "")
            if name == "floor" or name.startswith(("scene_proxy_", "room_wall_")):
                body.remove(geom)
                removed.append(name)
    deformable = ET.SubElement(xml, "deformable")
    meshes = {x.get("name"): x for x in asset.findall("mesh")}
    surfaces = []
    for body in [xml.find("worldbody"), *xml.findall(".//body")]:
        for geom in body.findall("geom"):
            if not geom.get("name", "").startswith("scene_visual_"):
                continue
            path = Path(meshes[geom.get("mesh")].get("file"))
            mesh = trimesh.load(path, force="mesh", process=False)
            vertices = np.asarray(mesh.vertices)
            faces = np.asarray(mesh.faces, dtype=np.int32)
            name = "scene_collision_" + geom.get("name")
            if geom.get("name") == "scene_visual_0_0":
                name = "native_floor"
            flex = ET.SubElement(
                deformable,
                "flex",
                name=name,
                dim="2",
                body=body.get("name", "world"),
                vertex=" ".join(format(float(x), ".12g") for x in vertices.ravel()),
                element=" ".join(str(int(x)) for x in faces.ravel()),
                radius=".001",
                group="5",
                rgba="0 0 0 0",
            )
            ET.SubElement(
                flex,
                "contact",
                selfcollide="none",
                internal="false",
                contype="2",
                conaffinity="1",
                friction=".8 .005 .0001",
                condim="3",
            )
            surfaces.append(
                {
                    "name": name,
                    "visual_geom": geom.get("name"),
                    "body": body.get("name", "world"),
                    "source": _file_binding(path),
                    "vertices": len(vertices),
                    "triangles": len(faces),
                    "bounds_local_m": mesh.bounds.tolist(),
                    "radius_m": 0.001,
                }
            )
    ET.SubElement(
        xml.find("worldbody"),
        "light",
        name="test_light",
        pos="2 3 3",
        dir="0 0 -1",
        directional="true",
    )
    modelpath = modeldir / "model.xml"
    modelpath.write_text(ET.tostring(xml, encoding="unicode"))
    model = mujoco.MjModel.from_xml_path(str(modelpath))
    old = mujoco.MjModel.from_xml_path(scene["model"]["path"])
    assert (model.nq, model.nv, model.nu, model.neq, model.nmocap) == (57, 55, 43, 0, 0)
    assert model.nflex == len(surfaces) and np.all(model.flex_rigid)
    for surface in surfaces:
        f = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_FLEX, surface["name"])
        assert int(model.flex_vertnum[f]) == surface["vertices"]
        assert int(model.flex_elemnum[f]) == surface["triangles"]
    static_changes = []
    for i in range(model.nbody):
        if model.body(i).name.startswith("generated_"):
            assert model.body_dofnum[i] == 0
            static_changes.append(
                {
                    "body": model.body(i).name,
                    "old_inferred_mass_kg": float(old.body_mass[i]),
                    "new_inferred_mass_kg": float(model.body_mass[i]),
                    "fixed": True,
                }
            )
    dynamic_ids = np.array(
        [
            i
            for i in range(model.nbody)
            if not model.body(i).name.startswith("generated_")
        ]
    )
    for name in (
        "body_mass",
        "body_inertia",
        "body_ipos",
        "body_iquat",
        "jnt_range",
        "dof_damping",
        "dof_armature",
        "actuator_ctrlrange",
    ):
        a, b = getattr(model, name), getattr(old, name)
        if name.startswith("body_"):
            a, b = a[dynamic_ids], b[dynamic_ids]
        np.testing.assert_array_equal(a, b)
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
    scene.update(
        model=_file_binding(modelpath),
        parent_scene=_file_binding(parent / "model/SCENE.json"),
        implementation=_file_binding(Path(__file__)),
        schema="native-scene-full-official-g1/v1",
        official_robot_model=_file_binding(OFFICIAL_MODEL),
        official_robot_meshes=robot_assets,
        robot_restored_geoms=restored,
        native_collision_surfaces=surfaces,
        removed_proxy_geoms=removed,
        static_furniture_inferred_mass_changes=static_changes,
        compiled_model_cache=_file_binding(modeldir / "CACHE.json"),
        collision_fidelity="all official G1 visual/collision geoms restored with original contact masks (MuJoCo convex mesh-link collisions and parent filtering); every generated scene triangle retained as fixed rigid flex surface with1mm radius; no OBB/background convex-hull replacement",
        full_triangle_robot_collision=False,
        full_official_robot_collision_model=True,
        native_scene_triangle_collision=True,
        limitations=[
            "official robot collision meshes are convexified by MuJoCo, not arbitrary nonconvex per-triangle robot surfaces",
            "scene1mm triangle shell, finite timestep and solver tolerances; static furniture, not articulated or movable",
            "original procedural50g payload and source/target fixtures retained explicitly",
        ],
    )
    scene["assets"] = [
        _file_binding(Path(p))
        for p in sorted(
            {x["path"] for x in scene["assets"]}
            | {x["source"]["path"] for x in robot_assets}
        )
    ]
    save(modeldir / "SCENE.json", scene)
    case = read_bound_json(parent / "CASE.json")
    case.update(
        protocol_root=str(root),
        model_path=str(modelpath),
        scene_manifest_path=str(modeldir / "SCENE.json"),
        scene_manifest=_file_binding(modeldir / "SCENE.json"),
        fidelity_round="native surfaces plus complete official G1; fresh qualification required",
    )
    save(root / "CASE.json", case)
    cert = read_bound_json(parent / "PREFLIGHT_SAFE.json")
    cert.update(
        case=_file_binding(root / "CASE.json"),
        parent_certificate=_file_binding(parent / "PREFLIGHT_SAFE.json"),
        scope="waypoint selection only from old model; not a collision/admission certificate for new full geometry",
    )
    save(root / "PREFLIGHT_SAFE.json", cert)
    p = read_bound_json(parent / "PROTOCOL.json")
    p.update(
        schema="native-full-g1-transfer-round/v1",
        case=_file_binding(root / "CASE.json"),
        active_budgets_ticks=[100, 300, 500, 1000, 1500],
        per_process_wall_s=300,
        causal_revision=1,
        max_causal_versions=1,
        finite_stage="one fixed condition and controller; static geometry check, fresh100observer admission, progressively extended active prefixes; first rejection exits, no parameter tuning, max15240 physics steps",
        full_model=_file_binding(modeldir / "SCENE.json"),
        previous_simplified_success=_file_binding(parent / "FINAL_VALIDATION.json"),
        documentation="https://mujoco.readthedocs.io/en/3.7.0/XMLreference.html#deformable-flex",
    )
    for f in sorted(Path(__file__).parent.glob("*.py")):
        if not f.name.startswith("test"):
            p["dependencies"]["embodied_transport_native_v1/" + f.name] = _file_binding(
                f
            )
    p["dependencies"]["native_model_cache"] = _file_binding(modeldir / "CACHE.json")
    save(root / "PROTOCOL.json", p)
    save(
        root / "BUILD_REVIEW.json",
        {
            "model": _file_binding(modelpath),
            "scene": _file_binding(modeldir / "SCENE.json"),
            "robot_meshes_verified": len(robot_assets),
            "scene_surfaces": len(surfaces),
            "scene_triangles": sum(x["triangles"] for x in surfaces),
            "all_rigid": bool(np.all(model.flex_rigid)),
            "same_robot_payload_mass_inertia_and_all_joints_actuators": True,
            "fixed_furniture_inferred_mass_changes": static_changes,
            "physics_steps": 0,
            "task_passed": False,
            "implementation": _file_binding(Path(__file__)),
        },
    )
    print(
        {
            "model_built": str(root),
            "robot_meshes": len(robot_assets),
            "native_surfaces": len(surfaces),
            "native_triangles": sum(x["triangles"] for x in surfaces),
        }
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--parent", type=Path, required=True)
    a = p.parse_args()
    prepare(a.root, a.parent)
