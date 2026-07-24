"""Local MuJoCo proxy for SAGE room-layout stability checks.

The proxy intentionally uses axis-aligned object dimensions instead of loading
the visual meshes.  It is a fast physics sanity check for gravity, collisions,
and grossly unstable placement; it is not a replacement for final Isaac Sim
validation.
"""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import mujoco
import numpy as np


@dataclass
class _SimulationState:
    model: mujoco.MjModel
    data: mujoco.MjData
    initial_positions: dict[str, np.ndarray]
    body_names: dict[str, str]
    room_path: str
    object_count: int


_STATE: _SimulationState | None = None


def _positive(value: Any, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return number if math.isfinite(number) and number > 0.0 else fallback


def _finite(value: Any, fallback: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return number if math.isfinite(number) else fallback


def _safe_name(value: Any, index: int) -> str:
    name = re.sub(r"[^a-zA-Z0-9_]+", "_", str(value or f"object_{index}")).strip("_")
    return f"object_{index:03d}_{name or 'unnamed'}"


def _vec(values: tuple[float, ...]) -> str:
    return " ".join(f"{value:.9g}" for value in values)


def _load_room(room_dict_save_path: str) -> dict[str, Any]:
    path = Path(room_dict_save_path).expanduser().resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("rooms"), list):
        rooms = payload["rooms"]
        if not rooms:
            raise ValueError(f"layout contains no rooms: {path}")
        payload = rooms[0]
    if not isinstance(payload, dict):
        raise ValueError(f"room JSON must contain an object: {path}")
    return payload


def _build_model(room: dict[str, Any]) -> tuple[mujoco.MjModel, mujoco.MjData, dict[str, str]]:
    dimensions = room.get("dimensions") if isinstance(room.get("dimensions"), dict) else {}
    width = _positive(dimensions.get("width"), 4.0)
    length = _positive(dimensions.get("length"), 4.0)
    height = _positive(dimensions.get("height"), 2.7)

    root = ElementTree.Element("mujoco", model="sage_room_proxy")
    ElementTree.SubElement(root, "compiler", angle="degree", coordinate="local")
    ElementTree.SubElement(
        root,
        "option",
        timestep=os.environ.get("SAGE_MUJOCO_TIMESTEP", "0.005"),
        gravity="0 0 -9.81",
        integrator="RK4",
    )
    ElementTree.SubElement(root, "size", nconmax="2000", njmax="5000")
    default = ElementTree.SubElement(root, "default")
    ElementTree.SubElement(
        default,
        "geom",
        friction="0.9 0.05 0.001",
        condim="3",
        solref="0.01 1",
        solimp="0.9 0.95 0.001",
    )
    world = ElementTree.SubElement(root, "worldbody")
    ElementTree.SubElement(
        world,
        "geom",
        name="floor",
        type="box",
        pos=_vec((width / 2.0, length / 2.0, -0.05)),
        size=_vec((width / 2.0, length / 2.0, 0.05)),
        rgba="0.8 0.8 0.8 1",
    )

    wall_thickness = 0.05
    wall_specs = [
        ("wall_south", (width / 2.0, -wall_thickness, height / 2.0), (width / 2.0, wall_thickness, height / 2.0)),
        ("wall_north", (width / 2.0, length + wall_thickness, height / 2.0), (width / 2.0, wall_thickness, height / 2.0)),
        ("wall_west", (-wall_thickness, length / 2.0, height / 2.0), (wall_thickness, length / 2.0, height / 2.0)),
        ("wall_east", (width + wall_thickness, length / 2.0, height / 2.0), (wall_thickness, length / 2.0, height / 2.0)),
    ]
    for name, position, size in wall_specs:
        ElementTree.SubElement(
            world,
            "geom",
            name=name,
            type="box",
            pos=_vec(position),
            size=_vec(size),
            rgba="0.7 0.7 0.75 1",
        )

    body_names: dict[str, str] = {}
    for index, obj in enumerate(room.get("objects", [])):
        if not isinstance(obj, dict):
            continue
        object_id = str(obj.get("id") or f"object_{index}")
        body_name = _safe_name(object_id, index)
        dims = obj.get("dimensions") if isinstance(obj.get("dimensions"), dict) else {}
        obj_width = _positive(dims.get("width"), 0.05)
        obj_length = _positive(dims.get("length"), 0.05)
        obj_height = _positive(dims.get("height"), 0.05)
        position = obj.get("position") if isinstance(obj.get("position"), dict) else {}
        x = _finite(position.get("x"))
        y = _finite(position.get("y"))
        z_bottom = _finite(position.get("z"))
        rotation = obj.get("rotation") if isinstance(obj.get("rotation"), dict) else {}
        yaw = _finite(rotation.get("z"))
        place_id = str(obj.get("place_id") or "floor").strip().lower()
        is_static = place_id == "wall"

        body = ElementTree.SubElement(
            world,
            "body",
            name=body_name,
            pos=_vec((x, y, z_bottom + obj_height / 2.0)),
            euler=_vec((0.0, 0.0, yaw)),
        )
        if not is_static:
            ElementTree.SubElement(body, "freejoint", name=f"joint_{body_name}")
        geom_args = {
            "name": f"geom_{body_name}",
            "type": "box",
            "size": _vec((obj_width / 2.0, obj_length / 2.0, obj_height / 2.0)),
            "rgba": "0.3 0.55 0.8 1" if not is_static else "0.55 0.55 0.6 1",
        }
        if not is_static:
            geom_args["mass"] = f"{_positive(obj.get('mass'), max(obj_width * obj_length * obj_height * 80.0, 0.05)):.9g}"
        ElementTree.SubElement(body, "geom", **geom_args)
        if not is_static:
            body_names[object_id] = body_name

    xml = ElementTree.tostring(root, encoding="unicode")
    model = mujoco.MjModel.from_xml_string(xml)
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    return model, data, body_names


def create_single_room_layout_scene_from_room(scene_save_dir: str, room_dict_save_path: str) -> dict[str, Any]:
    """Build an in-memory MuJoCo proxy scene from a SAGE room JSON."""

    del scene_save_dir  # Kept for compatibility with the official function.
    global _STATE
    room_path = str(Path(room_dict_save_path).expanduser().resolve())
    room = _load_room(room_path)
    model, data, body_names = _build_model(room)
    initial_positions = {
        object_id: data.xpos[model.body(body_name).id].copy()
        for object_id, body_name in body_names.items()
    }
    _STATE = _SimulationState(
        model=model,
        data=data,
        initial_positions=initial_positions,
        body_names=body_names,
        room_path=room_path,
        object_count=len(room.get("objects", [])),
    )
    return {
        "status": "success",
        "backend": "mujoco",
        "proxy_model": "axis_aligned_box_room",
        "room_path": room_path,
        "object_count": _STATE.object_count,
        "dynamic_object_count": len(body_names),
    }


def simulate_the_scene() -> dict[str, Any]:
    """Run the current proxy scene and report per-object displacement."""

    if _STATE is None:
        return {
            "status": "error",
            "backend": "mujoco",
            "error": "No room has been created; call create_single_room_layout_scene_from_room first.",
        }

    duration = _positive(os.environ.get("SAGE_MUJOCO_DURATION"), 2.0)
    unstable_threshold = _positive(os.environ.get("SAGE_MUJOCO_UNSTABLE_THRESHOLD"), 0.18)
    steps = max(1, min(int(math.ceil(duration / _STATE.model.opt.timestep)), 10000))
    for _ in range(steps):
        mujoco.mj_step(_STATE.model, _STATE.data)

    displacements: list[dict[str, Any]] = []
    for object_id, body_name in _STATE.body_names.items():
        body_id = _STATE.model.body(body_name).id
        final_position = _STATE.data.xpos[body_id].copy()
        displacement = float(np.linalg.norm(final_position - _STATE.initial_positions[object_id]))
        displacements.append(
            {
                "body": object_id,
                "displacement": round(displacement, 6),
                "initial_position": _STATE.initial_positions[object_id].round(6).tolist(),
                "final_position": final_position.round(6).tolist(),
            }
        )
    displacements.sort(key=lambda item: float(item["displacement"]), reverse=True)
    unstable_objects = [
        str(item["body"])
        for item in displacements
        if float(item["displacement"]) > unstable_threshold
    ]
    max_displacement = float(displacements[0]["displacement"]) if displacements else 0.0
    return {
        "status": "success",
        "backend": "mujoco",
        "proxy_model": "axis_aligned_box_room",
        "next_step": "unstable" if unstable_objects else "stable",
        "simulation_seconds": round(steps * float(_STATE.model.opt.timestep), 6),
        "unstable_threshold": unstable_threshold,
        "unstable_objects": unstable_objects,
        "mujoco_reports": [
            {
                "room_path": _STATE.room_path,
                "max_displacement": round(max_displacement, 6),
                "top_displacements": displacements[:20],
            }
        ],
    }


def simulate_the_scene_groups() -> dict[str, Any]:
    """Compatibility alias used by some official SAGE call sites."""

    return simulate_the_scene()
