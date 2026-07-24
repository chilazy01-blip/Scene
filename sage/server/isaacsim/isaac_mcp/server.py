"""Expose the SAGE Isaac MCP validation calls through a local backend.

The official SAGE server talks to an Isaac Sim extension over a socket.  This
reproduction uses the same two function names with a local MuJoCo proxy when
``SAGE_SIM_BACKEND=mujoco``.
"""

from __future__ import annotations

import os


if os.environ.get("SAGE_SIM_BACKEND", "").strip().lower() != "mujoco":
    raise RuntimeError(
        "This lightweight compatibility module only supports "
        "SAGE_SIM_BACKEND=mujoco. Use the official NVlabs/SAGE server for "
        "the Isaac Sim socket backend."
    )

from .local_mujoco_backend import (  # noqa: E402
    create_single_room_layout_scene_from_room,
    simulate_the_scene,
    simulate_the_scene_groups,
)

__all__ = [
    "create_single_room_layout_scene_from_room",
    "simulate_the_scene",
    "simulate_the_scene_groups",
]
