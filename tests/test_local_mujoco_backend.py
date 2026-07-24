from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


SERVER_ROOT = Path(__file__).resolve().parents[1] / "sage/server"
sys.path.insert(0, str(SERVER_ROOT))
os.environ["SAGE_SIM_BACKEND"] = "mujoco"

from isaacsim.isaac_mcp.server import (  # noqa: E402
    create_single_room_layout_scene_from_room,
    simulate_the_scene,
)


def room_with_object(z: float) -> dict:
    return {
        "id": "test_room",
        "dimensions": {"width": 4.0, "length": 4.0, "height": 2.7},
        "objects": [
            {
                "id": "box",
                "type": "box",
                "position": {"x": 2.0, "y": 2.0, "z": z},
                "rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
                "dimensions": {"width": 0.5, "length": 0.5, "height": 0.5},
                "place_id": "floor",
                "mass": 1.0,
            }
        ],
    }


class LocalMujocoBackendTest(unittest.TestCase):
    def run_room(self, z: float) -> dict:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "room.json"
            path.write_text(json.dumps(room_with_object(z)), encoding="utf-8")
            created = create_single_room_layout_scene_from_room(temp_dir, str(path))
            self.assertEqual(created["status"], "success")
            return simulate_the_scene()

    def test_floor_object_is_stable(self) -> None:
        result = self.run_room(0.0)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["unstable_objects"], [])

    def test_elevated_object_is_reported_unstable(self) -> None:
        result = self.run_room(1.0)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["unstable_objects"], ["box"])


if __name__ == "__main__":
    unittest.main()
