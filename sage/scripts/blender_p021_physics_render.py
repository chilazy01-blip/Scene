#!/usr/bin/env python3
"""Render P021 rigid trajectories using the exact, bound final GLB visual mesh.

Run inside Blender 4.3 with ``--background --python this_file -- --scene ...``.
The launcher owns CPU affinity, memory admission and Mesa setup. This script
requires a CPU Mesa environment and never constructs furniture geometry. Blender
background mode may not expose drawing-API renderer diagnostics; this is recorded
as unverified rather than inferred from the configuration or treated as failure.
Pure validation/matrix helpers can also be imported without Blender for tests.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import struct
import sys
import time
from itertools import product

import numpy as np


SCHEMA = "p021-physics-render-manifest/v1"
GLTF_TO_Z = np.array(((1, 0, 0, 0), (0, 0, -1, 0), (0, 1, 0, 0), (0, 0, 0, 1)), dtype=float)
ACTION_TIMES = tuple(index / 10 for index in range(21))
MATRIX_ATOL = 2e-5


def file_evidence(path: Path) -> dict:
    path = Path(path).resolve(strict=True)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def verify_evidence(actual: dict, expected: dict, label: str) -> None:
    if not isinstance(expected, dict) or expected.get("sha256") != actual["sha256"]:
        raise ValueError(f"{label}: missing or mismatched SHA-256 binding")
    if "bytes" in expected and expected["bytes"] != actual["bytes"]:
        raise ValueError(f"{label}: mismatched byte count")


def checked_matrix(value: object, label: str, *, rigid: bool = False) -> np.ndarray:
    matrix = np.asarray(value, dtype=float)
    if matrix.shape != (4, 4) or not np.isfinite(matrix).all():
        raise ValueError(f"{label}: expected finite 4x4 matrix")
    if not np.allclose(matrix[3], [0, 0, 0, 1], atol=1e-8, rtol=0):
        raise ValueError(f"{label}: invalid affine bottom row")
    if rigid:
        rotation = matrix[:3, :3]
        if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-6, rtol=0) or not math.isclose(
            float(np.linalg.det(rotation)), 1.0, abs_tol=1e-6
        ):
            raise ValueError(f"{label}: body pose is not a proper rigid transform")
    elif abs(float(np.linalg.det(matrix[:3, :3]))) < 1e-12:
        raise ValueError(f"{label}: singular visual transform")
    return matrix


def rigid_visual_matrix(body_now: object, body_initial: object, visual_initial: object) -> np.ndarray:
    """Preserve the imported root's scale/origin; apply only the body-frame delta."""
    now = checked_matrix(body_now, "body_now", rigid=True)
    initial = checked_matrix(body_initial, "body_initial", rigid=True)
    visual = checked_matrix(visual_initial, "visual_initial")
    return now @ np.linalg.inv(initial) @ visual


def validate_inputs(scene_path: Path, trajectory_path: Path, binding_path: Path) -> tuple[dict, dict, dict]:
    sources = {name: file_evidence(path) for name, path in (
        ("scene_glb", scene_path), ("trajectory", trajectory_path), ("binding", binding_path)
    )}
    binding = json.loads(binding_path.read_text())
    trajectory = json.loads(trajectory_path.read_text())
    verify_evidence(sources["scene_glb"], binding.get("scene_glb"), "physics scene")
    verify_evidence(sources["scene_glb"], trajectory.get("scene_glb"), "trajectory scene")
    verify_evidence(sources["binding"], trajectory.get("binding"), "trajectory physics binding")
    objects = binding.get("objects")
    if not isinstance(objects, dict) or not objects or any(not isinstance(key, str) or not key for key in objects):
        raise ValueError("physics binding requires nonempty exact object IDs")
    for object_id, row in objects.items():
        checked_matrix(row["initial_body_matrix_z_up"], f"{object_id} initial body", rigid=True)
    frames = trajectory.get("frames")
    if not isinstance(frames, list) or not frames:
        raise ValueError("trajectory frames missing")
    previous = -math.inf
    for index, frame in enumerate(frames + trajectory.get('diagnostic_frames', [])):
        timestamp = float(frame["time_s"])
        if index == len(frames):
            previous = -math.inf
        if not math.isfinite(timestamp) or timestamp < previous - 1e-8:
            raise ValueError("trajectory timestamps must be finite and chronological")
        previous = timestamp
        if set(frame.get("bodies", {})) != set(objects):
            raise ValueError(f"frame {index}: missing/extra body IDs")
        for object_id, body in frame["bodies"].items():
            checked_matrix(body["matrix_world_z_up"], f"frame {index} {object_id}", rigid=True)
            for name in ("linear_velocity_m_s", "angular_velocity_rad_s"):
                velocity = np.asarray(body.get(name), dtype=float)
                if velocity.shape != (3,) or not np.isfinite(velocity).all():
                    raise ValueError(f"frame {index} {object_id}: invalid {name}")
    initial, _, final = capture_frames(trajectory)
    if trajectory.get('schema') == 'p021-physics-trajectory/v2':
        dense_record = trajectory['dense_state']
        verify_evidence(file_evidence(Path(dense_record['path'])), dense_record, 'dense state')
        sources['dense_state'] = dense_record
        spec_record = trajectory['spec']
        verify_evidence(file_evidence(Path(spec_record['path'])), spec_record, 'physics spec')
        sources['spec'] = spec_record
        simulation = json.loads(Path(spec_record['path']).read_text())['simulation']
        count = round(simulation['action_s']/simulation['sample_interval_s'])
        expected = np.arange(count+1)*simulation['sample_interval_s']
        declared = trajectory['render_sampling']['base_action_times_s']
        if len(expected)!=len(declared) or not np.allclose(expected, declared, atol=1e-9, rtol=0):
            raise ValueError('render schedule differs from physics spec')
        with np.load(dense_record['path'], allow_pickle=False) as dense:
            identifiers = dense['object_ids'].tolist()
            for frame in frames + trajectory.get('diagnostic_frames', []):
                if frame['phase']=='initial':
                    index=0
                else:
                    matches=np.flatnonzero(np.isclose(dense['action_time_s'],frame['action_time_s'],atol=1e-9,rtol=0))
                    if len(matches)!=1:
                        raise ValueError('frame lacks unique dense timestamp')
                    index=int(matches[0])
                if ('dense_sample_index' in frame and frame['dense_sample_index']!=index
                        or abs(frame['time_s']-dense['time_s'][index])>1e-9):
                    raise ValueError('frame dense index/time differs')
                for i, identifier in enumerate(identifiers):
                    body=frame['bodies'][identifier]
                    for key in ('matrix_world_z_up','linear_velocity_m_s','angular_velocity_rad_s'):
                        if not np.allclose(body[key],dense[key][index,i],atol=1e-9,rtol=0):
                            raise ValueError('render frame differs from dense physics state')
    for object_id, row in objects.items():
        if not np.allclose(initial["bodies"][object_id]["matrix_world_z_up"],
                           row["initial_body_matrix_z_up"], atol=1e-7, rtol=0):
            raise ValueError(f"{object_id}: initial trajectory differs from geometry body frame")
        if not np.allclose(final["bodies"][object_id]["matrix_world_z_up"],
                           capture_frames(trajectory)[1][-1]["bodies"][object_id]["matrix_world_z_up"],
                           atol=1e-7, rtol=0):
            raise ValueError(f"{object_id}: final pose differs from action t=2")
    return binding, trajectory, sources


def capture_frames(trajectory: dict) -> tuple[dict, list[dict], dict]:
    frames = trajectory["frames"]
    initial = [row for row in frames if row.get("phase") == "initial"]
    final = [row for row in frames if row.get("phase") == "final"]
    actions = [row for row in frames if row.get("phase") == "action"]
    sampling = trajectory.get('render_sampling', {})
    expected_times = sampling.get('base_action_times_s', ACTION_TIMES)
    if (len(expected_times) < 2 or not np.isfinite(expected_times).all()
            or expected_times[0] != 0 or not np.all(np.diff(expected_times) > 0)):
        raise ValueError('invalid base action schedule')
    if len(initial) != 1 or len(final) != 1 or len(actions) != len(expected_times):
        raise ValueError("require one initial, complete declared action samples and one final frame")
    for expected, row in zip(expected_times, actions):
        actual = float(row["action_time_s"])
        if not math.isfinite(actual) or abs(actual - expected) > 1e-7:
            raise ValueError("action samples must match the declared schedule (legacy: 0,.1,...,2 seconds)")
    diagnostics = trajectory.get('diagnostic_frames', [])
    diagnostic_times = sampling.get('diagnostic_times_s', [])
    if (len(diagnostics) != len(diagnostic_times)
            or len(diagnostics) > sampling.get('maximum_diagnostic_frames', 0)
            or not np.isfinite(diagnostic_times).all()
            or (len(diagnostic_times) > 1 and not np.all(np.diff(diagnostic_times) > 0))):
        raise ValueError('diagnostic frame schedule incomplete')
    for expected, row in zip(diagnostic_times, diagnostics):
        if (row.get('phase') != 'diagnostic' or not row.get('events') or not 0 <= expected <= expected_times[-1]
                or abs(float(row['action_time_s'])-expected) > 1e-9):
            raise ValueError('diagnostic event frame mismatch')
    return initial[0], actions, final[0]


def read_glb_nodes(path: Path) -> list[dict]:
    """Read source node identities and source world transforms independently of bpy."""
    with path.open("rb") as handle:
        header = handle.read(12)
        if len(header) != 12:
            raise ValueError("truncated GLB header")
        magic, version, length = struct.unpack("<4sII", header)
        if magic != b"glTF" or version != 2 or length != path.stat().st_size:
            raise ValueError("invalid GLB v2 header/length")
        chunk_length, chunk_type = struct.unpack("<II", handle.read(8))
        if chunk_type != 0x4E4F534A:
            raise ValueError("GLB first chunk is not JSON")
        document = json.loads(handle.read(chunk_length))
    nodes = document.get("nodes", [])
    scene = document.get("scenes", [])[document.get("scene", 0)]
    found: dict[int, dict] = {}

    def visit(index: int, parent: np.ndarray, ancestors: tuple[int, ...]) -> None:
        if index in ancestors or index in found:
            raise ValueError("GLB node graph contains cycle or multiple parents")
        node = nodes[index]
        if "matrix" in node:
            local = np.asarray(node["matrix"], dtype=float).reshape(4, 4).T
        else:
            x, y, z, w = node.get("rotation", [0, 0, 0, 1])
            quat = np.asarray([x, y, z, w], dtype=float)
            if not np.isfinite(quat).all() or not math.isclose(float(quat @ quat), 1.0, abs_tol=1e-5):
                raise ValueError("invalid source GLB quaternion")
            local = np.eye(4)
            local[:3, :3] = np.array([
                [1 - 2*(y*y + z*z), 2*(x*y - z*w), 2*(x*z + y*w)],
                [2*(x*y + z*w), 1 - 2*(x*x + z*z), 2*(y*z - x*w)],
                [2*(x*z - y*w), 2*(y*z + x*w), 1 - 2*(x*x + y*y)],
            ]) @ np.diag(node.get("scale", [1, 1, 1]))
            local[:3, 3] = node.get("translation", [0, 0, 0])
        world = parent @ checked_matrix(local, f"source GLB node {index}")
        found[index] = {
            "node_index": index, "name": node.get("name"), "extras": node.get("extras", {}),
            "mesh_index": node.get("mesh"), "parent_index": ancestors[-1] if ancestors else None,
            "world_matrix_z_up": (GLTF_TO_Z @ world @ GLTF_TO_Z.T).tolist(),
        }
        for child in node.get("children", []):
            visit(child, world, (*ancestors, index))

    for root in scene["nodes"]:
        visit(root, np.eye(4), ())
    return [found[index] for index in sorted(found)]


def validate_source_ids(nodes: list[dict], expected_ids: set[str]) -> None:
    actual = {str(node["extras"]["scene_object_id"]) for node in nodes
              if "scene_object_id" in node["extras"]}
    if actual != expected_ids:
        raise ValueError(f"source GLB missing/extra object IDs: expected={sorted(expected_ids)}, actual={sorted(actual)}")


def array_digest(array: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()


def mesh_snapshot(obj) -> dict:
    vertices = np.empty(len(obj.data.vertices) * 3, dtype=np.float32)
    obj.data.vertices.foreach_get("co", vertices)
    loops = np.empty(len(obj.data.loops), dtype=np.int32)
    obj.data.loops.foreach_get("vertex_index", loops)
    polygon_material = np.empty(len(obj.data.polygons), dtype=np.int32)
    obj.data.polygons.foreach_get("material_index", polygon_material)
    return {"vertices": len(obj.data.vertices), "polygons": len(obj.data.polygons),
            "local_vertex_sha256": array_digest(vertices), "loop_vertex_sha256": array_digest(loops),
            "polygon_material_sha256": array_digest(polygon_material),
            "material_slots": [slot.material.name if slot.material else None for slot in obj.material_slots]}


def world_vertices(obj) -> np.ndarray:
    vertices = np.empty(len(obj.data.vertices) * 3, dtype=np.float64)
    obj.data.vertices.foreach_get("co", vertices)
    vertices = vertices.reshape(-1, 3)
    matrix = np.array(obj.matrix_world, dtype=float)
    return vertices @ matrix[:3, :3].T + matrix[:3, 3]


def validate_visual_mass_frame(vertices, obj, schema):
    body = checked_matrix(obj['initial_body_matrix_z_up'], 'initial body', rigid=True)
    if schema in ('p021-physics-binding/v2', 'p021-physics-binding/v3'):
        local = (vertices-body[:3,3]) @ body[:3,:3]
        center = (local.min(axis=0)+local.max(axis=0))/2
        expected_center = np.zeros(3)
        if schema == 'p021-physics-binding/v3':
            record = obj['mass_properties_artifact']
            verify_evidence(file_evidence(Path(record['path'])), record, 'mass properties')
            props = json.loads(Path(record['path']).read_text())
            expected_center = -np.asarray(props['center_of_mass_m'])
        if (not np.allclose(center,expected_center,atol=MATRIX_ATOL,rtol=0)
                or not np.allclose(np.ptp(local,axis=0),obj['metric_box_extents_m'],atol=MATRIX_ATOL,rtol=0)):
            raise ValueError('initial body differs from actual visual metric box')
    elif (not np.allclose(body[:3,:3],np.eye(3),atol=1e-7,rtol=0)
            or not np.allclose((vertices.min(axis=0)+vertices.max(axis=0))/2,body[:3,3],atol=MATRIX_ATOL,rtol=0)):
        raise ValueError('legacy initial body differs from actual visual world box')
    return body


def import_bound_visuals(scene_path: Path, binding: dict, nodes: list[dict]) -> tuple[dict, dict, list, dict]:
    import bpy

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(scene_path))
    bpy.context.view_layer.update()
    objects = list(bpy.context.scene.objects)
    expected_ids = set(binding["objects"])
    actual_ids = {str(obj["scene_object_id"]) for obj in objects if "scene_object_id" in obj}
    if actual_ids != expected_ids:
        raise ValueError("imported GLB has missing/extra scene_object_id extras")
    roots, meshes, audit = {}, {}, {}
    source_by_name = {node["name"]: node for node in nodes}
    if len(source_by_name) != len(nodes) or None in source_by_name:
        raise ValueError("source GLB requires unique explicit node names for correspondence")
    for object_id in sorted(expected_ids):
        members = [obj for obj in objects if obj.get("scene_object_id") == object_id]
        candidates = [obj for obj in members if not obj.parent or obj.parent.get("scene_object_id") != object_id]
        if len(candidates) != 1:
            raise ValueError(f"{object_id}: expected one exact tagged visual root")
        root = candidates[0]
        root_descendants = set(root.children_recursive) | {root}
        if not set(members).issubset(root_descendants):
            raise ValueError(f"{object_id}: detached furniture nodes")
        if any(obj.get("scene_object_id") not in (None, object_id) for obj in root_descendants):
            raise ValueError(f"{object_id}: root includes a different furniture ID")
        object_meshes = [obj for obj in root_descendants if obj.type == "MESH"]
        if not object_meshes or any(obj.modifiers for obj in object_meshes):
            raise ValueError(f"{object_id}: missing visual mesh or unsupported modifiers")
        node_audit = []
        for obj in members:
            source = source_by_name.get(obj.name)
            if not source or source["extras"].get("scene_object_id") != object_id:
                raise ValueError(f"{object_id}: imported node has no exact source node: {obj.name}")
            actual = np.array(obj.matrix_world)
            if not np.allclose(actual, source["world_matrix_z_up"], atol=MATRIX_ATOL, rtol=0):
                raise ValueError(f"{object_id}/{obj.name}: imported source world transform/axes differ")
            node_audit.append({"name": obj.name, "source_node_index": source["node_index"],
                               "actual_initial_world_matrix_z_up": actual.tolist()})
        vertices = np.concatenate([world_vertices(obj) for obj in object_meshes])
        bounds = np.array([vertices.min(axis=0), vertices.max(axis=0)])
        expected_bounds = np.asarray(binding["objects"][object_id]["world_bounds_z_up"], dtype=float)
        if expected_bounds.shape != (2, 3) or not np.allclose(bounds, expected_bounds, atol=MATRIX_ATOL, rtol=0):
            raise ValueError(f"{object_id}: imported geometry bounds differ from physics binding")
        initial_body = validate_visual_mass_frame(vertices,binding['objects'][object_id],binding.get('schema'))
        roots[object_id], meshes[object_id] = root, object_meshes
        audit[object_id] = {"root_name": root.name, "source_nodes": node_audit,
                            "initial_visual_root_matrix_z_up": np.array(root.matrix_world).tolist(),
                            "initial_body_matrix_z_up": initial_body.tolist(),
                            "actual_world_bounds_z_up": bounds.tolist(),
                            "visual_meshes": {obj.name: mesh_snapshot(obj) for obj in object_meshes}}
    architecture = [obj for obj in objects if obj.type == "MESH" and not obj.get("scene_object_id")]
    return roots, meshes, architecture, audit


def floor_and_cutaway(architecture: list, binding: dict) -> tuple[np.ndarray, list[dict]]:
    floor = [obj for obj in architecture if obj.name == "floor"]
    if len(floor) != 1:
        raise ValueError("require exact imported architecture floor mesh")
    points = world_vertices(floor[0])
    bounds = np.array([points.min(axis=0), points.max(axis=0)])
    if not np.allclose(bounds, binding["floor"]["world_bounds_z_up"], atol=MATRIX_ATOL, rtol=0):
        raise ValueError("imported floor bounds differ from simulator floor binding")
    hidden = []
    for obj in architecture:
        if obj != floor[0]:
            # Only architectural shell is omitted. Unknown untagged furniture
            # cannot silently become a cutaway object.
            if not obj.name.startswith(("wall_", "ceiling")):
                raise ValueError(f"unsupported untagged architecture node: {obj.name}")
            obj.hide_render = True
            hidden.append({"name": obj.name, "reason": "architecture cutaway", "original_world_matrix_z_up": np.array(obj.matrix_world).tolist()})
    return bounds, hidden


def camera_envelope(floor_bounds: np.ndarray, object_bounds: list) -> np.ndarray:
    """Frozen framing input uses initial geometry, never treatment/trajectory data."""
    bounds = np.asarray(object_bounds, dtype=float)
    minimum = np.minimum(floor_bounds[0], bounds[:, 0].min(axis=0) - [1.5, 1.5, 0])
    maximum = np.maximum(floor_bounds[1], bounds[:, 1].max(axis=0) + [1.5, 1.5, .3])
    return np.array([minimum, maximum])


def camera_snapshot(camera) -> dict:
    return {"name": camera.name, "matrix_world_z_up": np.array(camera.matrix_world).tolist(),
            "type": camera.data.type, "ortho_scale": float(camera.data.ortho_scale),
            "clip_start": float(camera.data.clip_start), "clip_end": float(camera.data.clip_end),
            "lens_mm": float(camera.data.lens), "shift_x": float(camera.data.shift_x),
            "shift_y": float(camera.data.shift_y)}


def make_camera(envelope: np.ndarray, view: str, floor_z: float):
    import bpy
    from mathutils import Vector

    center = envelope.mean(axis=0)
    span = float(max(envelope[1, :2] - envelope[0, :2]))
    target = center.copy()
    if view == "corner":
        location = center + np.array([1.25 * span, -.85 * span, .85 * span])
    else:
        target[2] = floor_z + .75
        location = np.array([center[0] + 1.5 * span, center[1] - .55 * span, floor_z + .55])
    data = bpy.data.cameras.new(f"P021_{view}")
    data.type = "ORTHO"
    data.clip_start, data.clip_end = .01, 250.0
    camera = bpy.data.objects.new(data.name, data)
    bpy.context.scene.collection.objects.link(camera)
    camera.location = location
    camera.rotation_euler = (Vector(target) - camera.location).to_track_quat("-Z", "Y").to_euler()
    bpy.context.view_layer.update()
    corners = np.array(list(product(*zip(envelope[0], envelope[1]))))
    inverse = np.linalg.inv(np.array(camera.matrix_world))
    projected = corners @ inverse[:3, :3].T + inverse[:3, 3]
    # Center the geometry in the image plane without changing viewing angle or
    # low-view eye height. Shift is dimensionless relative to orthographic scale.
    extent = projected[:, :2].max(axis=0) - projected[:, :2].min(axis=0)
    data.ortho_scale = float(max(extent) / .84)
    offset = (projected[:, :2].min(axis=0) + projected[:, :2].max(axis=0)) / 2
    data.shift_x = float(offset[0] / data.ortho_scale)
    data.shift_y = float(offset[1] / data.ortho_scale)
    bpy.context.view_layer.update()
    return camera


def validate_cpu_mesa_environment(environ: dict) -> dict:
    required = {
        "LIBGL_ALWAYS_SOFTWARE": {"1", "true"},
        "GALLIUM_DRIVER": {"llvmpipe", "softpipe"},
        "CUDA_VISIBLE_DEVICES": {""},
        "NVIDIA_VISIBLE_DEVICES": {"void", "none"},
        "EGL_PLATFORM": {"surfaceless"},
        "__GLX_VENDOR_LIBRARY_NAME": {"mesa"},
        "__EGL_VENDOR_LIBRARY_FILENAMES": {"/usr/share/glvnd/egl_vendor.d/50_mesa.json"},
    }
    actual = {key: environ.get(key) for key in required}
    invalid = [key for key, allowed in required.items() if actual[key] not in allowed]
    loader_override = environ.get("MESA_LOADER_DRIVER_OVERRIDE")
    if loader_override not in (None, "", "llvmpipe", "softpipe", "swrast"):
        invalid.append("MESA_LOADER_DRIVER_OVERRIDE")
    actual["MESA_LOADER_DRIVER_OVERRIDE"] = loader_override
    if invalid:
        raise ValueError(f"CPU Mesa environment missing/conflicting settings: {', '.join(invalid)}")
    return {"configured_cpu_mesa": True, "environment": actual,
            "scope": "launcher environment validated; does not identify the runtime graphics renderer"}


def graphics_diagnostics(platform) -> dict:
    """Drawing API unavailability in background Blender is diagnostic, not fatal."""
    diagnostics = {"renderer": None, "vendor": None, "version": None, "errors": {},
                   "runtime_software_renderer_verified": False}
    for label in ("renderer", "vendor", "version"):
        try:
            value = getattr(platform, f"{label}_get")()
            if isinstance(value, str) and value.strip():
                diagnostics[label] = value
            else:
                diagnostics["errors"][label] = {"error_type": "UnavailableDiagnostic",
                                                "error": "graphics API returned no nonempty string"}
        except Exception as error:
            diagnostics["errors"][label] = {"error_type": type(error).__name__, "error": str(error)}
    renderer = diagnostics["renderer"]
    if renderer is not None:
        if not any(marker in renderer.lower() for marker in ("llvmpipe", "softpipe", "software", "lavapipe")):
            raise ValueError(f"CPU-only P021 configuration contradicted by actual renderer={renderer}")
        diagnostics["runtime_software_renderer_verified"] = True
    diagnostics["runtime_renderer_status"] = "verified_software" if renderer else "unverified"
    return diagnostics


def setup_render(resolution: int, samples: int, envelope: np.ndarray) -> dict:
    import bpy
    import gpu
    from mathutils import Vector

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.eevee.taa_render_samples = samples
    configuration = validate_cpu_mesa_environment(os.environ)
    diagnostics = graphics_diagnostics(gpu.platform)
    scene.render.resolution_x = scene.render.resolution_y = resolution
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.image_settings.color_depth = "8"
    scene.render.film_transparent = False
    scene.render.use_file_extension = True
    scene.render.use_compositing = False
    scene.render.use_sequencer = False
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"
    scene.view_settings.exposure = 0
    scene.view_settings.gamma = 1
    world = bpy.data.worlds.new("P021World")
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    background.inputs[0].default_value = (.18, .18, .18, 1)
    background.inputs[1].default_value = .6
    scene.world = world
    center = envelope.mean(axis=0)
    lights = []
    for name, offset, energy, size in (
        ("Key", (3, -4, 7), 1500, 5), ("Fill", (-4, -1, 5), 900, 5), ("Top", (0, 3, 7), 1200, 4)
    ):
        data = bpy.data.lights.new(f"P021{name}", "AREA")
        data.energy, data.shape, data.size = energy, "DISK", size
        light = bpy.data.objects.new(data.name, data)
        scene.collection.objects.link(light)
        light.location = center + offset
        light.rotation_euler = (Vector(center) - light.location).to_track_quat("-Z", "Y").to_euler()
        bpy.context.view_layer.update()
        lights.append({"name": light.name, "energy": data.energy, "size": data.size,
                       "matrix_world_z_up": np.array(light.matrix_world).tolist()})
    return {"engine": scene.render.engine, "samples": int(scene.eevee.taa_render_samples),
            "resolution": [resolution, resolution], "resolution_percentage": 100,
            "device": "CPU software Mesa" if diagnostics["runtime_software_renderer_verified"] else None,
            "device_configuration": "CPU software Mesa", "cpu_mesa_configuration": configuration,
            "graphics_renderer": diagnostics["renderer"], "graphics_vendor": diagnostics["vendor"],
            "graphics_version": diagnostics["version"], "graphics_diagnostics": diagnostics,
            "blender_version": bpy.app.version_string, "blender_build_hash": bpy.app.build_hash.decode(),
            "view_transform": scene.view_settings.view_transform, "look": scene.view_settings.look,
            "exposure": scene.view_settings.exposure, "gamma": scene.view_settings.gamma,
            "image_format": "PNG", "image_color_mode": "RGB", "image_color_depth": "8",
            "original_materials_preserved": True, "world_background": [.18, .18, .18, 1],
            "world_strength": .6, "lights": lights,
            "cpu_affinity": sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None}


def projection(meshes: list, camera) -> dict:
    import bpy
    from bpy_extras.object_utils import world_to_camera_view
    from mathutils import Vector

    coordinates = [world_to_camera_view(bpy.context.scene, camera, obj.matrix_world @ Vector(corner))
                   for obj in meshes for corner in obj.bound_box]
    array = np.array([tuple(point) for point in coordinates])
    if not len(array) or not np.isfinite(array).all():
        raise ValueError("non-finite/empty visual projection")
    minimum, maximum = array.min(axis=0), array.max(axis=0)
    inside = bool(np.all(minimum[:2] >= .02) and np.all(maximum[:2] <= .98)
                  and minimum[2] > camera.data.clip_start and maximum[2] < camera.data.clip_end)
    return {"bbox_normalized_xy": [*minimum[:2].tolist(), *maximum[:2].tolist()],
            "camera_depth_range_m": [float(minimum[2]), float(maximum[2])],
            "complete_projection_with_2pct_margin": inside, "mesh_count": len(meshes),
            "occlusion_tested": False}


def render_frame(frame: dict, output: Path, camera, roots: dict, meshes: dict, audit: dict) -> dict:
    import bpy
    from mathutils import Matrix

    started = time.monotonic()
    scene = bpy.context.scene
    scene.camera = camera
    transforms = {}
    for object_id, root in roots.items():
        target = rigid_visual_matrix(frame["bodies"][object_id]["matrix_world_z_up"],
                                     audit[object_id]["initial_body_matrix_z_up"],
                                     audit[object_id]["initial_visual_root_matrix_z_up"])
        root.matrix_world = Matrix(target.tolist())
        transforms[object_id] = {"root_name": root.name, "target_visual_root_matrix_z_up": target.tolist(),
                                 "body_matrix_world_z_up": frame["bodies"][object_id]["matrix_world_z_up"]}
    bpy.context.view_layer.update()
    for object_id, root in roots.items():
        actual = np.array(root.matrix_world)
        target = np.array(transforms[object_id]["target_visual_root_matrix_z_up"])
        error = float(np.abs(actual - target).max())
        if not np.allclose(actual, target, atol=MATRIX_ATOL, rtol=0):
            raise ValueError(f"{object_id}: actual applied visual root differs from rigid delta")
        projected = projection(meshes[object_id], camera)
        if not projected["complete_projection_with_2pct_margin"]:
            raise ValueError(f"{object_id}: incomplete fixed-camera framing at t={frame['time_s']}: {projected}")
        transforms[object_id].update(actual_visual_root_matrix_z_up=actual.tolist(),
                                      maximum_matrix_abs_error=error, projection=projected)
    scene.render.filepath = str(output)
    bpy.ops.render.render(write_still=True)
    evidence = file_evidence(output)
    with output.open("rb") as handle:
        if handle.read(8) != b"\x89PNG\r\n\x1a\n":
            raise ValueError(f"render output is not PNG: {output}")
    return {"phase": frame["phase"], "time_s": frame["time_s"], "action_time_s": frame.get("action_time_s"),
            "events":frame.get("events", []), "dense_sample_index":frame.get("dense_sample_index"),
            "image": evidence, "camera": camera_snapshot(camera), "objects": transforms,
            "wall_time_s": time.monotonic() - started,
            "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024}


def write_json(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(path)


def run(args: argparse.Namespace) -> dict:
    started = time.monotonic()
    output = args.output_dir.resolve()
    if output.exists() and (list(output.glob("*.png")) or (output / "render_manifest.json").exists()
                            or (output / "render_failure.json").exists()):
        raise FileExistsError(f"refusing to overwrite existing render evidence: {output}")
    output.mkdir(parents=True, exist_ok=True)
    manifest = {"schema": SCHEMA, "ok": False, "frames": [], "stage": "validate_inputs"}
    try:
        binding, trajectory, sources = validate_inputs(args.scene, args.trajectory, args.binding)
        manifest.update(sources=sources, renderer_script=file_evidence(Path(__file__)),
                        rigid_delta_rule="body(t) @ inverse(initial_body) @ initial_visual_root",
                        timing_started_unix_s=time.time(), projection_scope="entire visual bounds in frame; occlusion not certified")
        nodes = read_glb_nodes(args.scene)
        validate_source_ids(nodes, set(binding["objects"]))
        manifest["stage"] = "import_exact_visual_geometry"
        roots, meshes, architecture, audit = import_bound_visuals(args.scene, binding, nodes)
        manifest["visual_binding"] = audit
        floor_bounds, hidden = floor_and_cutaway(architecture, binding)
        envelope = camera_envelope(floor_bounds, [row["actual_world_bounds_z_up"] for row in audit.values()])
        manifest.update(hidden_architecture_nodes=hidden, floor_world_bounds_z_up=floor_bounds.tolist(),
                        camera_envelope_z_up=envelope.tolist(),
                        camera_policy="initial geometry only; fixed 1.5m xy and .3m upper margin; 84% envelope framing")
        manifest["stage"] = "configure_software_render"
        manifest["settings"] = setup_render(args.resolution, args.samples, envelope)
        main_camera = make_camera(envelope, "corner", float(floor_bounds[1, 2]))
        low_camera = make_camera(envelope, "low_front", float(floor_bounds[1, 2]))
        manifest["cameras"] = {"corner": camera_snapshot(main_camera), "low_front": camera_snapshot(low_camera)}
        comparison = {"cameras": manifest["cameras"], "settings": manifest["settings"]}
        # Hardware/affinity may be logged separately without changing image setup.
        comparison["settings"] = {key: value for key, value in manifest["settings"].items()
                                  if key not in {"cpu_affinity", "device", "graphics_renderer", "graphics_vendor",
                                                 "graphics_version", "graphics_diagnostics"}}
        manifest["camera_and_settings_sha256"] = hashlib.sha256(json.dumps(comparison, sort_keys=True).encode()).hexdigest()
        manifest["setup_wall_time_s"] = time.monotonic() - started
        manifest["stage"] = "render_sequence"
        initial, actions, final = capture_frames(trajectory)
        jobs = [(initial, "initial_static.png", main_camera)]
        jobs += [(frame, f"action_{index:03d}.png", main_camera) for index, frame in enumerate(actions)]
        jobs += [(frame, f"diagnostic_{index:03d}.png", main_camera)
                 for index, frame in enumerate(trajectory.get('diagnostic_frames', []))]
        jobs += [(final, "final_corner.png", main_camera), (final, "final_low_front.png", low_camera)]
        for frame, name, camera in jobs:
            print(f"P021 rendering {name} action_time_s={frame.get('action_time_s')}", flush=True)
            manifest["frames"].append(render_frame(frame, output / name, camera, roots, meshes, audit))
            if len(manifest["frames"]) == 1:
                import gpu
                manifest["graphics_diagnostics_after_first_render"] = graphics_diagnostics(gpu.platform)
            write_json(output / "render_progress.json", manifest)
        manifest["stage"] = "verify_immutable_meshes_and_sources"
        for object_id, object_meshes in meshes.items():
            for obj in object_meshes:
                if mesh_snapshot(obj) != audit[object_id]["visual_meshes"][obj.name]:
                    raise ValueError(f"renderer changed source local mesh or material slots: {obj.name}")
        for name, source in sources.items():
            verify_evidence(file_evidence(Path(source["path"])), source, f"post-render {name}")
        manifest.update(ok=True, stage="complete", rendered_png_count=len(manifest["frames"]),
                        action_frame_count=len(actions), wall_time_s=time.monotonic() - started,
                        diagnostic_frame_count=len(trajectory.get('diagnostic_frames', [])),
                        peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
                        original_mesh_snapshots_unchanged=True)
        write_json(output / "render_manifest.json", manifest)
        return manifest
    except Exception as error:
        manifest.update(error_type=type(error).__name__, error=str(error),
                        wall_time_s=time.monotonic() - started,
                        peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)
        write_json(output / "render_failure.json", manifest)
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", type=Path, required=True)
    parser.add_argument("--trajectory", type=Path, required=True)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--resolution", type=int, default=640)
    parser.add_argument("--samples", type=int, default=16)
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    args = parser.parse_args(argv)
    if args.resolution < 32 or args.samples < 1:
        parser.error("resolution must be >=32 and samples >=1")
    return args


if __name__ == "__main__":
    result = run(parse_args())
    print(json.dumps({"ok": result["ok"], "rendered_png_count": result["rendered_png_count"],
                      "wall_time_s": result["wall_time_s"]}), flush=True)
