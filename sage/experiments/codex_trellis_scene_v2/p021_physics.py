"""P021 experimental, final-GLB-bound sliding-friction dynamics.

This is a declared-coefficient experiment, not measured furniture physics.
Source admission and resource scheduling belong to the scene/launch stages.
Only this final GLB supplies collision geometry. A single deterministic convex
hull preserves exterior extrema but fills cavities and gaps between feet.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import resource
import struct
import time
from typing import Any
from xml.etree import ElementTree as ET

import mujoco
import numpy as np
import scipy
from scipy.spatial import ConvexHull, cKDTree
from scipy.spatial.transform import Rotation


GLTF_TO_Z = np.array([[1., 0., 0., 0.], [0., 0., -1., 0.],
                      [0., 1., 0., 0.], [0., 0., 0., 1.]])
METHODS = {"B0_bound_control", "A_support_priority", "B_explicit_pairs"}
SOLREF = [.01, 1.]
SOLIMP = [.9, .95, .001, .5, 2.]
GEOM_FRICTION = [.9, .05, .001]


def _require(condition: Any, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")


def _bound(path: Path) -> dict:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return {"path": str(path.resolve()), "bytes": path.stat().st_size,
            "sha256": digest.hexdigest()}


def _check_file(record: dict, path: Path | None = None) -> None:
    actual = _bound(path or Path(record["path"]))
    _require(all(actual[key] == record[key] for key in ("bytes", "sha256")),
             f"file content changed: {actual['path']}")


def _array_hash(value: np.ndarray, dtype: str) -> str:
    array = np.ascontiguousarray(value, dtype=dtype)
    return hashlib.sha256(array.tobytes()).hexdigest()


def _positive(value: Any, label: str) -> float:
    _require(not isinstance(value, bool), f"{label} must be positive finite")
    number = float(value)
    _require(math.isfinite(number) and number > 0, f"{label} must be positive finite")
    return number


def _validate_spec(spec: dict) -> None:
    _require(spec.get("schema") == "p021-physics-scene-spec/v1", "unsupported scene spec schema")
    _require(spec.get("method") in METHODS, "unsupported friction method")
    _positive(spec["floor_mu"], "floor_mu")
    _require(spec.get("parameter_origin") == "designed_test_coefficient", "coefficient origin must be explicit")
    _require(spec.get("measured_asset_friction") is None, "measured friction is unsupported in this experiment")
    _require(isinstance(spec.get("development"), bool), "development flag is required")
    _require(spec["development"] or isinstance(spec.get("scene_glb"), dict), "formal run requires upstream final scene binding")
    identifiers = [obj["id"] for obj in spec["objects"]]
    _require(identifiers and all(isinstance(item, str) and item for item in identifiers), "object IDs must be nonempty strings")
    _require(len(set(identifiers)) == len(identifiers), "duplicate object IDs")
    _require(spec.get("mass_model", "legacy_box_v2") in ("legacy_box_v2", "material_voxel_v1"), "unsupported mass model")
    if spec.get("mass_model") == "material_voxel_v1":
        profiles = spec.get("physical_profiles", {})
        _require(isinstance(profiles, dict) and set(profiles) == set(identifiers),
                 "material mass model requires one explicit physical profile per object")
        _positive(spec.get("mass_voxel_pitch_m", .01), "mass_voxel_pitch_m")
    for obj in spec["objects"]:
        _require(np.isfinite([float(obj[key]) for key in ("x", "y", "z", "yaw")]).all(), "nonfinite object pose")
    for key in ("width", "length", "height"):
        _positive(spec["room"][key], f"room.{key}")
    simulation = spec["simulation"]
    _require(simulation.get("integrator", "RK4") in ("RK4", "implicitfast"), "integrator must be RK4 or implicitfast")
    dt = _positive(simulation["dt"], "dt")
    for key in ("settle_s", "action_s", "sample_interval_s"):
        duration = _positive(simulation[key], key)
        _require(abs(duration / dt - round(duration / dt)) <= 1e-7, f"{key} must be an integer number of timesteps")
    _require(abs(simulation["action_s"] / simulation["sample_interval_s"] - round(simulation["action_s"] / simulation["sample_interval_s"])) < 1e-7,
             "action duration must be divisible by sample interval")
    velocity = np.asarray(simulation["initial_velocity_m_s"], dtype=float)
    _require(velocity.shape == (3,) and np.isfinite(velocity).all() and velocity[2] == 0 and np.linalg.norm(velocity[:2]) > 0,
             "initial velocity must be finite, horizontal and nonzero")
    _require(dt <= SOLREF[0] / 2, "dt exceeds positive-solref time-constant safety condition")


def _read_glb(path: Path) -> tuple[dict, bytes]:
    raw = path.read_bytes()
    _require(len(raw) >= 20, "invalid GLB header")
    magic, version, length = struct.unpack_from("<4sII", raw)
    _require(magic == b"glTF" and version == 2 and length == len(raw), "invalid GLB header or length")
    chunks, offset = {}, 12
    while offset < len(raw):
        _require(offset + 8 <= len(raw), "truncated GLB chunk")
        size, kind = struct.unpack_from("<II", raw, offset)
        offset += 8
        _require(offset + size <= len(raw) and kind not in chunks, "invalid or duplicate GLB chunk")
        chunks[kind] = raw[offset:offset + size]
        offset += size
    _require(0x4E4F534A in chunks and 0x004E4942 in chunks, "GLB requires JSON and embedded binary")
    document = json.loads(chunks[0x4E4F534A])
    _require(document.get("asset", {}).get("version") == "2.0", "unsupported glTF version")
    _require(not document.get("animations") and not document.get("skins"), "animated or skinned meshes are unsupported")
    _require(len(document.get("buffers", [])) == 1 and "uri" not in document["buffers"][0], "external or multiple buffers are unsupported")
    return document, chunks[0x004E4942]


def _accessor(document: dict, binary: bytes, index: int) -> np.ndarray:
    accessor = document["accessors"][index]
    _require("sparse" not in accessor and not accessor.get("normalized", False), "sparse/normalized accessors unsupported")
    kinds = {5120: "i1", 5121: "u1", 5122: "<i2", 5123: "<u2", 5125: "<u4", 5126: "<f4"}
    counts = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}
    dtype, components = np.dtype(kinds[accessor["componentType"]]), counts[accessor["type"]]
    view = document["bufferViews"][accessor["bufferView"]]
    _require(view.get("buffer", 0) == 0, "unsupported buffer reference")
    count = int(accessor["count"])
    offset = int(view.get("byteOffset", 0)) + int(accessor.get("byteOffset", 0))
    stride = int(view.get("byteStride", components * dtype.itemsize))
    end = offset + max(0, count - 1) * stride + components * dtype.itemsize
    _require(count > 0 and stride >= components * dtype.itemsize and offset >= 0 and
             end <= len(binary) and end <= int(view.get("byteOffset", 0)) + view["byteLength"], "accessor outside buffer view")
    return np.ndarray((count, components), dtype=dtype, buffer=binary, offset=offset,
                      strides=(stride, dtype.itemsize)).copy()


def _node_matrix(node: dict) -> np.ndarray:
    if "matrix" in node:
        _require(not any(key in node for key in ("translation", "rotation", "scale")), "node mixes matrix and TRS")
        matrix = np.asarray(node["matrix"], dtype=float).reshape(4, 4).T
    else:
        matrix = np.eye(4)
        quaternion = np.asarray(node.get("rotation", [0, 0, 0, 1]), dtype=float)
        _require(np.isfinite(quaternion).all() and abs(np.linalg.norm(quaternion) - 1) < 1e-5, "invalid glTF XYZW quaternion")
        matrix[:3, :3] = Rotation.from_quat(quaternion).as_matrix() @ np.diag(node.get("scale", [1, 1, 1]))
        matrix[:3, 3] = node.get("translation", [0, 0, 0])
    _require(np.isfinite(matrix).all() and np.allclose(matrix[3], [0, 0, 0, 1], atol=1e-12) and
             abs(np.linalg.det(matrix[:3, :3])) > 1e-15, "invalid/singular node matrix")
    return matrix


def _geometry(scene_glb: Path, spec: dict) -> tuple[dict, dict]:
    """Decode final positions/triangles without losing ancestor transforms or instances."""
    document, binary = _read_glb(scene_glb)
    nodes = document["nodes"]
    expected = {obj["id"] for obj in spec["objects"]}
    seen, ids, groups, architecture = set(), set(), {identifier: [] for identifier in expected}, []

    def visit(index: int, parent: np.ndarray, path: list[int], inherited: str | None,
              object_root: np.ndarray | None = None) -> None:
        _require(index not in path, "cycle in GLB node graph")
        _require(index not in seen, "GLB node has multiple parents")
        seen.add(index)
        node = nodes[index]
        own = node.get("extras", {}).get("scene_object_id")
        _require(own is None or isinstance(own, str) and own, "invalid scene_object_id")
        _require(not (own and inherited and own != inherited), "conflicting ancestor object IDs")
        identifier = own or inherited
        if identifier:
            ids.add(identifier)
        world = parent @ _node_matrix(node)
        matrix = GLTF_TO_Z @ world
        if own and inherited is None:
            object_root = matrix
        ancestry = path + [index]
        if "mesh" in node:
            mesh = document["meshes"][node["mesh"]]
            parts, faces, primitive_bindings, start = [], [], [], 0
            for primitive_index, primitive in enumerate(mesh["primitives"]):
                _require(primitive.get("mode", 4) == 4 and not primitive.get("targets") and not primitive.get("extensions"), "only static uncompressed triangle primitives supported")
                position_accessor = primitive["attributes"]["POSITION"]
                _require(document["accessors"][position_accessor]["componentType"] == 5126 and
                         document["accessors"][position_accessor]["type"] == "VEC3", "POSITION must be float VEC3")
                vertices = _accessor(document, binary, position_accessor).astype(np.float64)
                if "indices" in primitive:
                    _require(document["accessors"][primitive["indices"]]["componentType"] in (5121, 5123, 5125), "indices must be unsigned integers")
                    indices = _accessor(document, binary, primitive["indices"]).reshape(-1).astype(np.int64)
                else:
                    indices = np.arange(len(vertices), dtype=np.int64)
                _require(len(indices) % 3 == 0 and len(indices) > 0 and indices.min() >= 0 and indices.max() < len(vertices), "invalid mesh triangle indices")
                _require(np.isfinite(vertices).all(), "nonfinite visual vertices")
                primitive_bindings.append({"primitive_index": primitive_index, "vertex_count": len(vertices),
                                           "triangle_count": len(indices) // 3,
                                           "local_vertices_f64_sha256": _array_hash(vertices, "<f8"),
                                           "local_faces_i64_sha256": _array_hash(indices.reshape(-1, 3), "<i8")})
                parts.append(vertices @ matrix[:3, :3].T + matrix[:3, 3])
                faces.append(indices.reshape(-1, 3) + start)
                start += len(vertices)
            record = {"node_index": index, "name": node.get("name", ""), "path": ancestry,
                      "world_matrix_gltf_y_up": world.tolist(), "world_matrix_z_up": matrix.tolist(),
                      "primitives": primitive_bindings}
            cloud = np.concatenate(parts)
            record["world_vertices_f64_sha256"] = _array_hash(cloud, "<f8")
            entry = {"binding": record, "vertices": cloud, "faces": np.concatenate(faces)}
            if identifier:
                _require(identifier in expected, f"unexpected object ID: {identifier}")
                entry["object_root_matrix_z_up"] = object_root.copy()
                groups[identifier].append(entry)
            else:
                architecture.append(entry)
        for child in node.get("children", []):
            visit(child, world, ancestry, identifier, object_root)

    for index in document["scenes"][document.get("scene", 0)]["nodes"]:
        visit(index, np.eye(4), [], None)
    _require(ids == expected, f"object ID mismatch: missing={sorted(expected-ids)} extra={sorted(ids-expected)}")
    _require(all(groups.values()), "object lacks triangle geometry")
    floor_parts = []
    for entry in architecture:
        node = nodes[entry["binding"]["node_index"]]
        if node.get("name") == "floor" or "floor_material_id" in node.get("extras", {}):
            floor_parts.append(entry)
        else:
            ancestor_nodes = [nodes[item] for item in entry["binding"]["path"]]
            _require(any(item.get("name", "").startswith("wall_") or item.get("extras", {}).get("architecture_wall") for item in ancestor_nodes),
                     f"unbound non-architecture mesh: {node.get('name')}")
    _require(len(floor_parts) == 1, "exactly one actual GLB architectural floor is required")
    floor = floor_parts[0]
    bounds = np.asarray([floor["vertices"].min(axis=0), floor["vertices"].max(axis=0)])
    extents = bounds[1] - bounds[0]
    _require(np.all(extents > 1e-7), "floor must be a nondegenerate closed rectangular slab")
    # An AABB alone cannot prove support. Require only box corners and complete
    # top triangulation; tilted, holed, sloped or nonrectangular floors reject.
    corners = np.array(np.meshgrid(*[(lo, hi) for lo, hi in zip(*bounds)], indexing="ij")).reshape(3, -1).T
    _require(cKDTree(corners).query(floor["vertices"])[0].max() < 1e-6 and
             cKDTree(floor["vertices"]).query(corners)[0].max() < 1e-6, "floor is not an axis-aligned rectangular slab")
    triangles = floor["vertices"][floor["faces"]]
    top = triangles[np.all(np.abs(triangles[:, :, 2] - bounds[1, 2]) < 1e-6, axis=1)]
    area = float(np.linalg.norm(np.cross(top[:, 1] - top[:, 0], top[:, 2] - top[:, 0]), axis=1).sum() / 2)
    _require(abs(area - extents[0] * extents[1]) <= 1e-6, "floor top does not cover its rectangle exactly")
    _require(np.allclose(bounds[:, :2], [[0, 0], [spec["room"]["width"], spec["room"]["length"]]], atol=1e-5, rtol=0), "floor bounds disagree with room")
    floor["world_bounds_z_up"] = bounds.tolist()
    floor["support_z_m"] = float(bounds[1, 2])
    floor["top_triangle_area_m2"] = area
    floor["excluded_architecture"] = [item["binding"] for item in architecture if item is not floor]
    floor["other_architecture_parts"] = [item for item in architecture if item is not floor]
    return groups, floor


def _hull(points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    unique = np.unique(np.asarray(points, dtype=np.float64), axis=0)
    hull = ConvexHull(unique)  # No QJ random perturbation or mesh repair.
    selected = np.sort(hull.vertices)
    remap = np.full(len(unique), -1, dtype=int)
    remap[selected] = np.arange(len(selected))
    faces = remap[hull.simplices].copy()
    vertices = unique[selected]
    for i, face in enumerate(faces):
        normal = np.cross(vertices[face[1]] - vertices[face[0]], vertices[face[2]] - vertices[face[0]])
        if np.dot(normal, hull.equations[i, :3]) < 0:
            face[1], face[2] = face[2], face[1]
        faces[i] = np.roll(face, -int(np.argmin(face)))
    faces = faces[np.lexsort((faces[:, 2], faces[:, 1], faces[:, 0]))]
    return vertices, faces


def _vec(values: Any) -> str:
    return " ".join(format(float(value), ".17g") for value in np.asarray(values).reshape(-1))


def object_mass_frame(parts: list[dict]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Asset-root metric box: bake scale/shear once, retain a rigid body frame.

    A fixed local-axis reflection correction before the polar decomposition
    keeps the result equivariant under any proper world rotation, including
    repeated singular values. Mesh reflections remain baked in the points.
    """
    root = np.asarray(parts[0]["object_root_matrix_z_up"])
    _require(all(np.array_equal(root, part["object_root_matrix_z_up"]) for part in parts),
             "object ID has multiple distinct roots; a unique asset frame is required")
    linear = root[:3, :3].copy()
    if np.linalg.det(linear) < 0:
        linear[:, 0] *= -1
    u, _, vt = np.linalg.svd(linear)
    rotation = u @ vt
    points = np.concatenate([part["vertices"] for part in parts])
    local = (points - root[:3, 3]) @ rotation
    bounds = np.array([local.min(axis=0), local.max(axis=0)])
    center, extents = bounds.mean(axis=0), np.ptp(bounds, axis=0)
    _require(np.all(extents > 1e-6), "degenerate visual object")
    body = np.eye(4)
    body[:3, :3] = rotation
    body[:3, 3] = root[:3, 3] + rotation @ center
    return body, local - center, extents


def metric_object_mesh(parts: list[dict], body: np.ndarray):
    """Final visual triangles in a rigid, already-scaled metric asset frame."""
    import trimesh
    vertices, faces, offset = [], [], 0
    for part in parts:
        local = (part["vertices"]-body[:3, 3]) @ body[:3, :3]
        vertices.append(local)
        faces.append(part["faces"]+offset)
        offset += len(local)
    return trimesh.Trimesh(vertices=np.concatenate(vertices), faces=np.concatenate(faces), process=False)


def require_engineering_success(result: dict) -> dict:
    gates = result.get("engineering_gates", {})
    required = {"final_scene_unchanged", "exact_object_ids_bound", "compiled_geometry_and_inertia_bound",
                "all_states_finite", "actual_target_contacts_observed", "actual_contact_parameters_match",
                "no_nonfloor_contact", "trajectory_inside_room", "no_simulator_warnings"}
    _require(result.get("status") == "completed" and result.get("simulation_completed") is True
             and required <= gates.keys() and all(value is True for value in gates.values())
             and result.get("simulator_warnings") == [] and result.get("failures") == [],
             "physics engineering failure: " + repr(result.get("failures", result.get("status"))))
    return result


def restore_saved_state(model_path: Path, dense_path: Path, index: int) -> tuple[Any, Any]:
    """Restore the exact pre-next-step integration state; do not forward twice."""
    with np.load(dense_path, allow_pickle=False) as dense:
        _require(str(dense["state_schema"]) == "p021-integration-state/v1", "unsupported saved state")
        _require(str(dense["mujoco_version"]) == mujoco.__version__, "MuJoCo version differs")
        _require(str(dense["model_sha256"]) == _bound(Path(model_path))["sha256"], "saved state model differs")
        state_spec = int(dense["integration_state_spec"])
        _require(state_spec == int(mujoco.mjtState.mjSTATE_INTEGRATION), "incomplete integration state")
        state = dense["integration_state"][index].copy()
    model = mujoco.MjModel.from_xml_path(str(model_path))
    _require(state.shape == (mujoco.mj_stateSize(model, state_spec),) and np.isfinite(state).all(), "invalid saved state")
    data = mujoco.MjData(model)
    mujoco.mj_setState(model, data, state, state_spec)
    return model, data


def _make_model(spec: dict, binding: dict, hulls: dict, output: Path) -> tuple[Any, Any]:
    root = ET.Element("mujoco", model="p021_bound_friction")
    ET.SubElement(root, "compiler", angle="radian", inertiafromgeom="false")
    option = ET.SubElement(root, "option", timestep=_vec([spec["simulation"]["dt"]]), gravity="0 0 -9.81",
                           integrator=spec["simulation"].get("integrator", "RK4"))
    ET.SubElement(option, "flag", multiccd="enable", nativeccd="enable")
    default = ET.SubElement(root, "default")
    ET.SubElement(default, "geom", friction=_vec(GEOM_FRICTION), condim="3", solref=_vec(SOLREF), solimp=_vec(SOLIMP), margin="0", gap="0")
    asset, world = ET.SubElement(root, "asset"), ET.SubElement(root, "worldbody")
    floor_bounds = np.asarray(binding["floor"]["world_bounds_z_up"])
    support_mu = float(spec["floor_mu"]) if spec["method"] == "A_support_priority" else .9
    ET.SubElement(world, "geom", name="floor", type="box", pos=_vec(floor_bounds.mean(axis=0)),
                  size=_vec((floor_bounds[1] - floor_bounds[0]) / 2), friction=_vec([support_mu, .05, .001]),
                  priority="1" if spec["method"] == "A_support_priority" else "0")
    contacts = ET.SubElement(root, "contact") if spec["method"] == "B_explicit_pairs" else None
    for index, (identifier, obj) in enumerate(binding["objects"].items()):
        name = f"object_{index:03d}"
        vertices, faces = hulls[identifier]
        ET.SubElement(asset, "mesh", name=f"mesh_{name}", vertex=_vec(vertices), face=" ".join(str(int(value)) for value in faces.reshape(-1)))
        body_matrix = np.asarray(obj["initial_body_matrix_z_up"])
        quat = Rotation.from_matrix(body_matrix[:3, :3]).as_quat()[[3, 0, 1, 2]]
        body = ET.SubElement(world, "body", name=name, pos=_vec(body_matrix[:3, 3]), quat=_vec(quat))
        ET.SubElement(body, "freejoint", name=f"joint_{name}")
        ET.SubElement(body, "inertial", pos="0 0 0", mass=_vec([obj["mass_kg"]]),
                      quat=_vec(obj.get("inertial_quaternion_wxyz", [1, 0, 0, 0])),
                      diaginertia=_vec(obj["diagonal_inertia_kg_m2"]))
        ET.SubElement(body, "geom", name=f"geom_{name}", type="mesh", mesh=f"mesh_{name}", mass="0", priority="0")
        if contacts is not None:
            mu = float(spec["floor_mu"])
            ET.SubElement(contacts, "pair", name=f"pair_{name}_floor", geom1="floor", geom2=f"geom_{name}", condim="3",
                          friction=_vec([mu, mu, .05, .001, .001]), solref=_vec(SOLREF), solreffriction="0 0", solimp=_vec(SOLIMP), margin="0", gap="0")
        obj["simulator"] = {"body_name": name, "geom_name": f"geom_{name}", "mesh_name": f"mesh_{name}", "joint_name": f"joint_{name}"}
    xml = ET.tostring(root, encoding="unicode")
    (output / "model.xml").write_text(xml + "\n")
    model = mujoco.MjModel.from_xml_string(xml)
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    return model, data


def _compiled(model: Any, data: Any, binding: dict, hulls: dict) -> dict:
    records = {"mujoco_version": mujoco.__version__, "geoms": [], "pairs": [], "options": {}}
    for key in ("timestep", "gravity", "integrator", "solver", "cone", "iterations", "tolerance", "noslip_iterations", "disableflags", "enableflags", "ccd_iterations", "ccd_tolerance"):
        value = getattr(model.opt, key)
        records["options"][key] = value.tolist() if isinstance(value, np.ndarray) else (int(value) if isinstance(value, (int, np.integer)) else float(value))
    records["options"]["nativeccd_enabled"] = not bool(model.opt.disableflags & mujoco.mjtDisableBit.mjDSBL_NATIVECCD)
    records["options"]["multiccd_enabled"] = bool(model.opt.enableflags & mujoco.mjtEnableBit.mjENBL_MULTICCD)
    for geom_id in range(model.ngeom):
        records["geoms"].append({"geom_id": geom_id, "name": mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, geom_id),
                                 "type": int(model.geom_type[geom_id]), "body_id": int(model.geom_bodyid[geom_id]),
                                 "priority": int(model.geom_priority[geom_id]), "condim": int(model.geom_condim[geom_id]),
                                 **{key: getattr(model, "geom_" + key)[geom_id].tolist() for key in ("friction", "solref", "solimp", "pos", "quat", "size")}})
    for pair_id in range(model.npair):
        records["pairs"].append({"pair_id": pair_id, "geom1": int(model.pair_geom1[pair_id]), "geom2": int(model.pair_geom2[pair_id]),
                                 "condim": int(model.pair_dim[pair_id]),
                                 **{key: getattr(model, "pair_" + key)[pair_id].tolist() for key in ("friction", "solref", "solreffriction", "solimp")}})
    for identifier, obj in binding["objects"].items():
        names = obj["simulator"]
        body_id, geom_id = model.body(names["body_name"]).id, model.geom(names["geom_name"]).id
        mesh_id, joint_id = model.mesh(names["mesh_name"]).id, model.joint(names["joint_name"]).id
        names.update(body_id=body_id, geom_id=geom_id, mesh_id=mesh_id, joint_id=joint_id,
                     qpos_adr=int(model.jnt_qposadr[joint_id]), dof_adr=int(model.jnt_dofadr[joint_id]))
        start, count = int(model.mesh_vertadr[mesh_id]), int(model.mesh_vertnum[mesh_id])
        compiled_world = model.mesh_vert[start:start + count].astype(float) @ data.geom_xmat[geom_id].reshape(3, 3).T + data.geom_xpos[geom_id]
        body_matrix = np.asarray(obj["initial_body_matrix_z_up"])
        input_world = hulls[identifier][0] @ body_matrix[:3, :3].T + body_matrix[:3, 3]
        error = max(float(cKDTree(input_world).query(compiled_world)[0].max()), float(cKDTree(compiled_world).query(input_world)[0].max()))
        obj["compiled"] = {"mass_kg": float(model.body_mass[body_id]), "diagonal_inertia_kg_m2": model.body_inertia[body_id].tolist(),
                           "inertial_position_body": model.body_ipos[body_id].tolist(), "inertial_quaternion_wxyz": model.body_iquat[body_id].tolist(),
                           "mesh_position_compiler": model.mesh_pos[mesh_id].tolist(), "mesh_quaternion_compiler_wxyz": model.mesh_quat[mesh_id].tolist(),
                           "hull_vertex_world_max_error_m": error, "mesh_vertex_count": count}
        _require(error <= 1e-5, f"compiled collider binding error exceeds 1e-5m: {identifier}: {error}")
        _require(np.allclose(model.body_inertia[body_id], obj["diagonal_inertia_kg_m2"], atol=1e-12, rtol=1e-12) and
                 math.isclose(model.body_mass[body_id], obj["mass_kg"], abs_tol=1e-12, rel_tol=1e-12) and
                 np.allclose(model.body_ipos[body_id], 0, atol=1e-12), f"compiled inertia/mass/COM differs: {identifier}")
        if "inertia_tensor_kg_m2" in obj:
            rotation = Rotation.from_quat(model.body_iquat[body_id][[1, 2, 3, 0]]).as_matrix()
            tensor = rotation @ np.diag(model.body_inertia[body_id]) @ rotation.T
            _require(np.allclose(tensor, obj["inertia_tensor_kg_m2"], atol=1e-12, rtol=1e-10),
                     f"compiled full inertia tensor differs: {identifier}")
    return records


def verify_physics_binding(scene_glb: Path, binding_path: Path, spec: dict | None = None) -> dict:
    """Reject changed files, identities, node transforms and collider content."""
    binding = json.loads(binding_path.read_text())
    _require(binding.get("schema") in ("p021-physics-binding/v1", "p021-physics-binding/v2", "p021-physics-binding/v3"), "unsupported physics binding schema")
    _check_file(binding["scene_glb"], scene_glb)
    _check_file(binding["spec"])
    _check_file(binding["model_xml"])
    original_spec = json.loads(Path(binding["spec"]["path"]).read_text())
    _require(spec is None or spec == original_spec, "physics specification changed")
    groups, floor = _geometry(scene_glb, original_spec)
    _require(set(groups) == set(binding["objects"]), "bound object IDs changed")
    for identifier, parts in groups.items():
        obj = binding["objects"][identifier]
        _require([part["binding"] for part in parts] == obj["mesh_binding"], f"mesh/transform binding changed: {identifier}")
        _check_file(obj["collider"]["artifact"])
        vertices = np.concatenate([part["vertices"] for part in parts])
        bounds = np.array([vertices.min(axis=0), vertices.max(axis=0)])
        body = np.eye(4)
        body[:3, 3] = bounds.mean(axis=0)
        if binding["schema"] == "p021-physics-binding/v2":
            body, _, extents = object_mass_frame(parts)
            mass = max(.05, 80. * float(np.prod(extents)))
            inertia = mass / 12 * (np.sum(extents**2) - extents**2)
            _require(np.allclose(obj["diagonal_inertia_kg_m2"], inertia, rtol=1e-12, atol=1e-12)
                     and math.isclose(obj["mass_kg"], mass, rel_tol=1e-12), "mass/inertia binding changed")
        elif binding["schema"] == "p021-physics-binding/v3":
            from .multilevel_proxy import mesh_content_hash
            body, _, _ = object_mass_frame(parts)
            _check_file(obj["mass_properties_artifact"])
            props = json.loads(Path(obj["mass_properties_artifact"]["path"]).read_text())
            _require(props["identity"]["mesh_sha256"] == mesh_content_hash(metric_object_mesh(parts, body))
                     and props["profile"] == original_spec["physical_profiles"][identifier],
                     "mass geometry/profile binding changed")
            for record in props["voxel_files"]:
                path = Path(record["path"])
                _require(_bound(path)["sha256"] == record["sha256"], "mass voxel artifact changed")
            body[:3, 3] += body[:3, :3] @ np.asarray(props["center_of_mass_m"])
            _require(math.isclose(obj["mass_kg"], props["mass_kg"], rel_tol=1e-12)
                     and np.allclose(obj["inertia_tensor_kg_m2"], props["inertia_tensor_kg_m2"], atol=1e-12, rtol=1e-12)
                     and np.allclose(obj["diagonal_inertia_kg_m2"], props["principal_inertia_kg_m2"], atol=1e-12, rtol=1e-12),
                     "material mass/inertia binding changed")
        _require(np.array_equal(body, obj["initial_body_matrix_z_up"]), f"body frame changed: {identifier}")
        with np.load(obj["collider"]["artifact"]["path"], allow_pickle=False) as collider:
            _require(_array_hash(collider["vertices"], "<f8") == obj["collider"]["vertices_f64_sha256"] and
                     _array_hash(collider["faces"], "<i8") == obj["collider"]["faces_i64_sha256"], f"collider array hash mismatch: {identifier}")
    _require(floor["binding"] == binding["floor"]["mesh_binding"] and floor["world_bounds_z_up"] == binding["floor"]["world_bounds_z_up"], "floor binding changed")
    return binding


def _frame(model: Any, data: Any, binding: dict, phase: str, action_time: float | None) -> dict:
    bodies = {}
    for identifier, obj in binding["objects"].items():
        body_id = obj["simulator"]["body_id"]
        matrix, velocity = np.eye(4), np.empty(6)
        matrix[:3, :3] = data.xmat[body_id].reshape(3, 3)
        matrix[:3, 3] = data.xpos[body_id]
        # mj_objectVelocity returns rotation then translation in world axes.
        mujoco.mj_objectVelocity(model, data, mujoco.mjtObj.mjOBJ_BODY, body_id, velocity, 0)
        bodies[identifier] = {"matrix_world_z_up": matrix.tolist(), "linear_velocity_m_s": velocity[3:].tolist(),
                              "angular_velocity_rad_s": velocity[:3].tolist()}
    return {"time_s": float(data.time), "action_time_s": action_time, "phase": phase, "bodies": bodies}


def _metrics(dense_path: Path, binding: dict, spec: dict, contact_summary: dict) -> dict:
    """Analyze saved state independently of MJCF/contact configuration creation."""
    with np.load(dense_path, allow_pickle=False) as dense:
        times = dense["time_s"].copy()
        action_times = dense["action_time_s"].copy()
        matrices, linear, angular = (dense[key].copy() for key in ("matrix_world_z_up", "linear_velocity_m_s", "angular_velocity_rad_s"))
        bounds, support_counts = dense["world_bounds_z_up"].copy(), dense["floor_contact_count"].copy()
    action = np.flatnonzero(action_times >= 0)
    action_t = action_times[action]
    velocity0 = np.asarray(spec["simulation"]["initial_velocity_m_s"])
    speed0 = float(np.linalg.norm(velocity0[:2]))
    direction = velocity0[:2] / speed0
    perpendicular = np.array([-direction[1], direction[0]])
    floor_z = binding["floor"]["support_z_m"]
    mu = .9 if spec["method"] == "B0_bound_control" else float(spec["floor_mu"])
    expected_distance, expected_time = speed0 ** 2 / (2 * mu * 9.81), speed0 / (mu * 9.81)
    result = {"objects": {}, "analytic_reference": {"mu": mu, "deceleration_m_s2": mu * 9.81,
              "stopping_distance_m": expected_distance, "stopping_time_s": expected_time,
              "origin": "ideal horizontal Coulomb sliding, no external measurement"},
              "measurement_conventions": {"stopped_speed_m_s": .01, "residual_window_s": 1.,
                  "fit_speed_fraction": [.2, .8], "stopping_time": "first action sample after last speed above threshold; null if not stopped", 
                  "floor_extrema": "transformed convex hull vertices: linear extrema equal all final visual vertices"}}
    for i, identifier in enumerate(binding["objects"]):
        positions = matrices[action, i, :3, 3]
        displacement = positions - positions[0]
        along = displacement[:, :2] @ direction
        speeds = np.linalg.norm(linear[action, i, :2], axis=1)
        over = np.flatnonzero(speeds > .01)
        stop_index = int(over[-1] + 1) if len(over) else 0
        stopped = stop_index < len(action)
        fit = (speeds > .2 * speed0) & (speeds < .8 * speed0)
        fitted = float(-np.polyfit(action_t[fit], linear[action[fit], i, :2] @ direction, 1)[0]) if fit.sum() >= 3 else None
        initial_up_body = matrices[0, i, :3, :3].T @ np.array([0., 0., 1.])
        up_world = matrices[:, i, :3, :3] @ initial_up_body
        tilt = np.degrees(np.arccos(np.clip(up_world[:, 2], -1, 1)))
        tail = action[action_t >= max(0, action_t[-1] - 1)]
        gap = bounds[:, i, 0, 2] - floor_z
        room = spec["room"]
        outside = ((bounds[:, i, 0, 0] < -1e-6) | (bounds[:, i, 0, 1] < -1e-6) |
                   (bounds[:, i, 1, 0] > room["width"] + 1e-6) | (bounds[:, i, 1, 1] > room["length"] + 1e-6) |
                   (bounds[:, i, 1, 2] > room["height"] + 1e-6))
        scope_valid = not contact_summary["nonfloor_contact_records"] and not outside.any()
        measured = float(along[stop_index]) if stopped else None
        result["objects"][identifier] = {"action_displacement_m": displacement[-1].tolist(), "forward_displacement_m": float(along[-1]),
            "horizontal_displacement_m": float(np.linalg.norm(displacement[-1, :2])),
            "stopping_time_s": float(action_t[stop_index]) if stopped else None, "stopping_distance_m": measured,
            "max_tilt_degrees": float(tilt.max()), "action_max_tilt_degrees": float(tilt[action].max()),
            "max_lateral_displacement_m": float(np.abs(displacement[:, :2] @ perpendicular).max()),
            "max_angular_velocity_rad_s": float(np.linalg.norm(angular[:, i], axis=1).max()),
            "residual_linear_velocity_rms_m_s": float(np.sqrt(np.mean(np.sum(linear[tail, i] ** 2, axis=1)))),
            "residual_angular_velocity_rms_rad_s": float(np.sqrt(np.mean(np.sum(angular[tail, i] ** 2, axis=1)))),
            "final_linear_velocity_m_s": linear[-1, i].tolist(), "final_angular_velocity_rad_s": angular[-1, i].tolist(),
            "floor_min_gap_m": float(gap.min()), "floor_max_gap_m": float(gap.max()), "floor_final_gap_m": float(gap[-1]),
            "max_floor_penetration_m": float(max(0, -gap.min())), "max_floor_suspension_m": float(max(0, gap.max())),
            "outside_room_sample_count": int(outside.sum()), "no_floor_contact_action_sample_count": int((support_counts[action, i] == 0).sum()),
            "finite_states": bool(np.isfinite(matrices[:, i]).all() and np.isfinite(linear[:, i]).all() and np.isfinite(angular[:, i]).all()),
            "analytic": {"validity": "requires_protocol_applicability_gate" if scope_valid else "invalid_nonfloor_contact_or_bounds",
                "fitted_deceleration_m_s2": fitted, "fit_sample_count": int(fit.sum()),
                "unfiltered_deceleration_relative_error": abs(fitted - mu * 9.81) / (mu * 9.81) if fitted is not None else None,
                "unfiltered_stopping_distance_relative_error": abs(measured - expected_distance) / expected_distance if measured is not None else None,
                "unfiltered_stopping_time_relative_error": abs(float(action_t[stop_index]) - expected_time) / expected_time if stopped else None,
                "external_physics_validated": False}}
    return result


def run_physics(scene_glb: Path, spec: dict, output: Path) -> dict:
    """Run the exact spec, retaining failure artifacts and refusing output reuse."""
    output, scene_glb = Path(output).resolve(), Path(scene_glb).resolve()
    output.mkdir(parents=True, exist_ok=True)
    _require(not any((output / name).exists() for name in ("physics_result.json", "physics_binding.json", "physics_spec.json", "model.xml")),
             "physics output already contains an attempt; use a fresh directory")
    start = time.monotonic()
    stage = "validate_input"
    try:
        _validate_spec(spec)
        if spec.get("scene_glb"):
            _check_file(spec["scene_glb"], scene_glb)
        _json(output / "physics_spec.json", spec)
        scene_binding = _bound(scene_glb)
        stage = "decode_final_glb"
        groups, floor = _geometry(scene_glb, spec)
        binding = {"schema": "p021-physics-binding/v2", "scene_glb": scene_binding,
                   "spec": _bound(output / "physics_spec.json"), "objects": {},
                   "coordinate_contract": {"world": "right-handed Z-up metres", "matrix": "column vectors; row-major nested JSON arrays",
                        "gltf_to_z_up": GLTF_TO_Z.tolist(), "body_frame": "asset-root polar rotation, metric local box center; scale/shear/reflection baked once into collider"},
                   "floor": {"id": "floor", "world_bounds_z_up": floor["world_bounds_z_up"], "support_z_m": floor["support_z_m"],
                        "top_triangle_area_m2": floor["top_triangle_area_m2"], "mesh_binding": floor["binding"],
                        "collision_representation": "exact axis-aligned rectangular slab from final GLB vertices",
                        "excluded_architecture": floor["excluded_architecture"], "wall_policy": "no invented wall colliders; dense visual hull bounds checked against actual floor and room height"},
                   "limitations": ["Single exterior convex hull fills cavities and leg gaps; no internal contacts or contact-area claims.",
                        "Mass is 80 kg/m3 times asset-frame metric box volume; COM/inertia are box approximations, not measurements.",
                        "Declared friction is designed test data; material/mass/inertia truth remains unknown."]}
        if spec.get("mass_model") == "material_voxel_v1":
            binding["schema"] = "p021-physics-binding/v3"
            binding["coordinate_contract"]["body_frame"] = "asset-root polar rotation with estimated COM; scale/shear/reflection baked once"
            binding["limitations"][1] = "Material density and undilated voxel mass are estimates with explicit category fallback and resolution sensitivity."
        hulls = {}
        stage = "build_convex_hulls"
        for index, identifier in enumerate(sorted(groups)):
            parts = groups[identifier]
            points = np.concatenate([part["vertices"] for part in parts])
            bounds = np.asarray([points.min(axis=0), points.max(axis=0)])
            body, local_points, extents = object_mass_frame(parts)
            mass_properties = None
            if spec.get("mass_model") == "material_voxel_v1":
                from .physical_mass import estimate_mass_properties
                mass_properties = estimate_mass_properties(metric_object_mesh(parts, body),
                    spec["physical_profiles"][identifier], output / "mass_properties" / identifier,
                    pitch_m=float(spec.get("mass_voxel_pitch_m", .01)))
                com = np.asarray(mass_properties["center_of_mass_m"])
                body[:3, 3] += body[:3, :3] @ com
                local_points -= com
            vertices, faces = _hull(local_points)
            hulls[identifier] = (vertices, faces)
            path = output / f"collider_{index:03d}.npz"
            np.savez(path, vertices=vertices, faces=faces)
            mass = max(.05, 80. * float(np.prod(extents)))
            binding["objects"][identifier] = {"initial_body_matrix_z_up": body.tolist(), "world_bounds_z_up": bounds.tolist(),
                "mesh_binding": [part["binding"] for part in parts], "visual_vertex_count": len(points),
                "visual_triangle_count": sum(len(part["faces"]) for part in parts), "mass_kg": mass,
                "diagonal_inertia_kg_m2": (mass / 12 * np.array([extents[1] ** 2 + extents[2] ** 2,
                    extents[0] ** 2 + extents[2] ** 2, extents[0] ** 2 + extents[1] ** 2])).tolist(),
                "mass_inertia_origin": "80_times_asset_frame_metric_box_volume_and_box_inertia_v2", "true_mass_kg": None,
                "metric_box_extents_m": extents.tolist(),
                "true_inertia_kg_m2": None, "true_material": None,
                "collider": {"method": "single_convex_hull", "library": "scipy.spatial.ConvexHull/Qhull", "scipy_version": scipy.__version__,
                     "qhull_options": "default Qt; no QJ perturbation", "seed": None,
                     "input": "all final visual vertices in centered asset metric frame, deduplicated lexicographically",
                     "vertex_count": len(vertices), "face_count": len(faces), "vertices_f64_sha256": _array_hash(vertices, "<f8"),
                     "faces_i64_sha256": _array_hash(faces, "<i8"), "artifact": _bound(path)}}
            if mass_properties is not None:
                binding["objects"][identifier].update(
                    mass_kg=mass_properties["mass_kg"],
                    diagonal_inertia_kg_m2=mass_properties["principal_inertia_kg_m2"],
                    inertia_tensor_kg_m2=mass_properties["inertia_tensor_kg_m2"],
                    inertial_quaternion_wxyz=mass_properties["inertial_quaternion_wxyz"],
                    mass_inertia_origin=mass_properties["mass_origin"],
                    mass_properties_artifact=_bound(Path(mass_properties["artifact"])),
                    mass_range_kg=mass_properties["mass_range_kg"],
                    mass_resolution_sensitivity=mass_properties["resolution_sensitivity"],
                    physical_profile=mass_properties["profile"])
        hull_done = time.monotonic()
        stage = "compile_mujoco"
        model, data = _make_model(spec, binding, hulls, output)
        compiled = _compiled(model, data, binding, hulls)
        binding["compiled_parameters"] = compiled
        binding["model_xml"] = _bound(output / "model.xml")
        _json(output / "physics_binding.json", binding)
        compile_done = time.monotonic()
        stage = "simulate"
        simulation = spec["simulation"]
        dt = float(model.opt.timestep)
        settle_steps = round(simulation["settle_s"] / dt)
        action_steps = round(simulation["action_s"] / dt)
        sample_steps = round(simulation["sample_interval_s"] / dt)
        ids = list(binding["objects"])
        floor_id = model.geom("floor").id
        geom_objects = {obj["simulator"]["geom_id"]: identifier for identifier, obj in binding["objects"].items()}
        effective_mu = .9 if spec["method"] == "B0_bound_control" else float(spec["floor_mu"])
        contact_summary = {"floor_contact_records": 0, "nonfloor_contact_records": 0, "parameter_mismatch_records": 0,
                           "per_object_floor_contact_records": {identifier: 0 for identifier in ids}, "distinct_parameters": []}
        signatures, frames, dense = set(), [], []
        state_spec = int(mujoco.mjtState.mjSTATE_INTEGRATION)
        integration_states = []
        warning_counts = {}
        contact_path = output / "contacts.jsonl"
        with contact_path.open("x") as contacts_file:
            def capture(phase: str, action_time: float | None, sparse: bool = False) -> None:
                mujoco.mj_forward(model, data)  # RK4 caches can otherwise refer to an integration substage.
                state = np.empty(mujoco.mj_stateSize(model, state_spec))
                mujoco.mj_getState(model, data, state, state_spec)
                integration_states.append(state)
                for warning_id, warning in enumerate(data.warning):
                    if warning.number:
                        warning_counts[warning_id] = {"warning_id": warning_id,
                            "count": max(int(warning.number), warning_counts.get(warning_id, {}).get("count", 0)),
                            "lastinfo": int(warning.lastinfo)}
                _require(np.isfinite(data.qpos).all() and np.isfinite(data.qvel).all(), "nonfinite simulator state")
                frame = _frame(model, data, binding, phase, action_time)
                if sparse:
                    frames.append(frame)
                counts = {identifier: 0 for identifier in ids}
                for contact_index in range(data.ncon):
                    contact = data.contact[contact_index]
                    geom1, geom2 = int(contact.geom1), int(contact.geom2)
                    object_id = geom_objects.get(geom2 if geom1 == floor_id else geom1) if floor_id in (geom1, geom2) else None
                    friction, solref, solimp = contact.friction.copy(), contact.solref.copy(), contact.solimp.copy()
                    force = np.zeros(6)
                    mujoco.mj_contactForce(model, data, contact_index, force)
                    record = {"time_s": float(data.time), "action_time_s": action_time, "phase": phase,
                        "contact_index": contact_index, "geom1": geom1, "geom2": geom2, "object_id": object_id,
                        "floor_contact": object_id is not None, "distance_m": float(contact.dist), "position_z_up": contact.pos.tolist(),
                        "frame": contact.frame.reshape(3, 3).tolist(), "condim": int(contact.dim), "friction": friction.tolist(),
                        "solref": solref.tolist(), "solreffriction": contact.solreffriction.tolist(), "solimp": solimp.tolist(),
                        "force_contact_frame": force.tolist(), "efc_address": int(contact.efc_address)}
                    if object_id is not None:
                        body_state = frame["bodies"][object_id]
                        com = np.asarray(body_state["matrix_world_z_up"])[:3, 3]
                        point_velocity = np.asarray(body_state["linear_velocity_m_s"]) + np.cross(
                            body_state["angular_velocity_rad_s"], contact.pos - com)
                        contact_velocity = contact.frame.reshape(3, 3) @ point_velocity
                        force_on_object = force * (1 if geom2 != floor_id else -1)
                        record.update(point_velocity_world_m_s=point_velocity.tolist(),
                            tangential_velocity_contact_m_s=contact_velocity[1:].tolist(),
                            tangential_power_W=float(force_on_object[1:3] @ contact_velocity[1:3]))
                    contacts_file.write(json.dumps(record, allow_nan=False, separators=(",", ":")) + "\n")
                    signature = (int(contact.dim), *friction.tolist(), *solref.tolist(), *contact.solreffriction.tolist(), *solimp.tolist())
                    if signature not in signatures:
                        signatures.add(signature)
                        contact_summary["distinct_parameters"].append({key: record[key] for key in ("condim", "friction", "solref", "solreffriction", "solimp")})
                    if object_id is not None:
                        counts[object_id] += 1
                        contact_summary["floor_contact_records"] += 1
                        contact_summary["per_object_floor_contact_records"][object_id] += 1
                        correct = contact.dim == 3 and np.allclose(friction, [effective_mu, effective_mu, .05, .001, .001], atol=1e-12, rtol=0) and np.allclose(solref, SOLREF, atol=1e-12, rtol=0) and np.allclose(solimp, SOLIMP, atol=1e-12, rtol=0) and np.allclose(contact.solreffriction, 0, atol=1e-12)
                        contact_summary["parameter_mismatch_records"] += int(not correct)
                    else:
                        contact_summary["nonfloor_contact_records"] += 1
                matrices, linear, angular, world_bounds = [], [], [], []
                for identifier in ids:
                    body_frame = frame["bodies"][identifier]
                    matrix = np.asarray(body_frame["matrix_world_z_up"])
                    world_vertices = hulls[identifier][0] @ matrix[:3, :3].T + matrix[:3, 3]
                    matrices.append(matrix)
                    linear.append(body_frame["linear_velocity_m_s"])
                    angular.append(body_frame["angular_velocity_rad_s"])
                    world_bounds.append([world_vertices.min(axis=0), world_vertices.max(axis=0)])
                dense.append((float(data.time), -1. if action_time is None else action_time, matrices, linear, angular,
                              world_bounds, [counts[identifier] for identifier in ids], data.qpos.copy(), data.qvel.copy()))

            capture("initial", None, True)
            for step in range(settle_steps):
                mujoco.mj_step(model, data)
                capture("settle", None)
            # Impart the same horizontal COM velocity after actual settlement.
            # Change only horizontal velocity. The zero declared z component
            # means no vertical impulse; settled vz/omega remain observable.
            for obj in binding["objects"].values():
                dof = obj["simulator"]["dof_adr"]
                data.qvel[dof:dof + 2] = simulation["initial_velocity_m_s"][:2]
            capture("action", 0., True)
            for step in range(1, action_steps + 1):
                mujoco.mj_step(model, data)
                capture("action", step * dt, step % sample_steps == 0)
            frames.append(_frame(model, data, binding, "final", float(simulation["action_s"])))
        dense_path = output / "dense_state.npz"
        keys = ("time_s", "action_time_s", "matrix_world_z_up", "linear_velocity_m_s", "angular_velocity_rad_s",
                "world_bounds_z_up", "floor_contact_count", "qpos", "qvel")
        arrays = {key: np.asarray([row[i] for row in dense]) for i, key in enumerate(keys)}
        np.savez_compressed(dense_path, object_ids=np.asarray(ids), **arrays,
            integration_state=np.asarray(integration_states), integration_state_spec=state_spec,
            state_schema="p021-integration-state/v1", mujoco_version=mujoco.__version__,
            model_sha256=binding["model_xml"]["sha256"])
        from .p021_physics_diagnostics import diagnostic_frames, timestep_diagnostics
        diagnostics, sampling = diagnostic_frames(arrays, ids, simulation, binding["floor"]["support_z_m"])
        trajectory = {"schema": "p021-physics-trajectory/v2", "scene_glb": scene_binding, "binding": _bound(output / "physics_binding.json"),
                      "spec": binding["spec"], "frames": frames, "dense_state": _bound(dense_path),
                      "diagnostic_frames": diagnostics, "render_sampling": sampling,
                      "action": {"kind": "settled_horizontal_velocity_impulse_then_unforced", "initial_velocity_m_s": simulation["initial_velocity_m_s"],
                                 "retained_settled_vertical_and_angular_velocity": True, "horizontal_external_force_after_impulse_N": 0}}
        _json(output / "trajectory.json", trajectory)
        _json(output / "contact_summary.json", contact_summary)
        # Always diagnose, even when behavior/engineering gates later fail.
        stage = "numerical_sensitivity"
        numerical = timestep_diagnostics(output / "model.xml", integration_states[0], binding, spec, output)
        _json(output / "numerical_diagnostics.json", numerical)
        simulation_done = time.monotonic()
        stage = "analyze_saved_state"
        metrics = _metrics(dense_path, binding, spec, contact_summary)
        _json(output / "metrics.json", metrics)
        _check_file(scene_binding, scene_glb)
        warnings = list(warning_counts.values())
        engineering_gates = {"final_scene_unchanged": True, "exact_object_ids_bound": True, "compiled_geometry_and_inertia_bound": True,
            "all_states_finite": all(obj["finite_states"] for obj in metrics["objects"].values()),
            "actual_target_contacts_observed": all(contact_summary["per_object_floor_contact_records"].values()),
            "actual_contact_parameters_match": contact_summary["parameter_mismatch_records"] == 0,
            "no_nonfloor_contact": contact_summary["nonfloor_contact_records"] == 0,
            "trajectory_inside_room": all(obj["outside_room_sample_count"] == 0 for obj in metrics["objects"].values()),
            "no_simulator_warnings": not warnings}
        engineering_gates['no_numerical_diagnostic_warnings'] = not any(grid['warning_ids'] for grid in numerical['grids'])
        result = {"schema": "p021-physics-result/v1", "status": "completed" if all(engineering_gates.values()) else "completed_with_engineering_failures",
            "run_id": spec["run_id"], "method": spec["method"], "development": spec["development"],
            "simulation_completed": True, "engineering_gates": engineering_gates,
            "numerical_diagnostics": numerical, "numerically_resolved": numerical["base_step_resolved"],
            "failures": [key for key, value in engineering_gates.items() if not value], "simulator_warnings": warnings,
            "metrics": metrics, "contact_summary": contact_summary, "external_physics_validated": False,
            "visual_review_complete": False, "promoted": False,
            "timing_s": {"geometry_and_hulls": hull_done - start, "compile_and_binding": compile_done - hull_done,
                         "simulation_and_state_io": simulation_done - compile_done, "total": time.monotonic() - start},
            "peak_process_rss_bytes": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024),
            "rss_scope": "process lifetime high-water RSS on Linux; not an isolated per-stage measurement",
            "artifacts": {name: _bound(output / filename) for name, filename in (("binding", "physics_binding.json"), ("trajectory", "trajectory.json"),
                ("model", "model.xml"), ("dense_state", "dense_state.npz"), ("contacts", "contacts.jsonl"), ("contact_summary", "contact_summary.json"),
                ("metrics", "metrics.json"), ("spec", "physics_spec.json"), ("numerical", "numerical_diagnostics.json"))}}
        result['artifacts'].update({f'numerical_grid_{i}':grid['artifact'] for i,grid in enumerate(numerical['grids'])})
        _json(output / "physics_result.json", result)
        return result
    except Exception as exc:
        _json(output / "physics_result.json", {"schema": "p021-physics-result/v1", "status": "failed", "stage": stage,
            "simulation_completed": False, "error": f"{type(exc).__name__}: {exc}", "wall_time_s": time.monotonic() - start,
            "peak_process_rss_bytes": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024), "promoted": False})
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", required=True, type=Path)
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    result = run_physics(args.scene, json.loads(args.spec.read_text()), args.output_dir)
    print(json.dumps({"status": result["status"], "artifacts": result["artifacts"], "failures": result["failures"]}))
    require_engineering_success(result)


if __name__ == "__main__":
    main()
