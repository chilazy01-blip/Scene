from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "sage/scripts/run_codex_prompt_scene.py"
SPEC = importlib.util.spec_from_file_location("run_codex_prompt_scene", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def template(width: float, length: float) -> dict:
    return {"dimensions": {"width": width, "length": length, "height": 1.0}}


class ClampPlanTest(unittest.TestCase):
    def test_centered_coordinates_are_translated_before_clamping(self) -> None:
        plan = {
            "room": {"width": 6.0, "length": 4.0},
            "objects": [
                {"type": "desk", "id": "left", "x": -2.0, "y": 1.0, "rotation_z": 0},
                {"type": "desk", "id": "right", "x": 2.0, "y": -1.0, "rotation_z": 0},
            ],
        }
        result = MODULE.clamp_plan(plan, {"desk": template(1.0, 0.6)})
        self.assertEqual(result["_input_coordinate_frame"], "centered_origin_translated_to_southwest")
        self.assertAlmostEqual(result["objects"][0]["x"], 1.0)
        self.assertAlmostEqual(result["objects"][0]["y"], 3.0)
        self.assertAlmostEqual(result["objects"][1]["x"], 5.0)
        self.assertAlmostEqual(result["objects"][1]["y"], 1.0)

    def test_quarter_turn_swaps_footprint_for_boundary_clamp(self) -> None:
        plan = {
            "room": {"width": 6.0, "length": 4.0},
            "objects": [
                {"type": "shelf", "id": "west", "x": 0.1, "y": 2.0, "rotation_z": 90},
            ],
        }
        result = MODULE.clamp_plan(plan, {"shelf": template(1.4, 0.4)})
        self.assertAlmostEqual(result["objects"][0]["x"], 0.25)


if __name__ == "__main__":
    unittest.main()
