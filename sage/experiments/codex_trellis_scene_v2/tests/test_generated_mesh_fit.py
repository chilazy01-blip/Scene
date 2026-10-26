from __future__ import annotations

import unittest

from sage.experiments.codex_trellis_scene_v2.brief import (
    build_asset_generation_spec,
)
from sage.experiments.codex_trellis_scene_v2.dimensions import (
    dimension_policy_for_category,
    runtime_mesh_fit_audit,
)


class GeneratedMeshFitTests(unittest.TestCase):
    def test_living_room_sofa_regression_is_rejected(self) -> None:
        policy = dimension_policy_for_category("sofa")
        report = runtime_mesh_fit_audit(
            [2.192961, 0.917064, 3.162375], policy
        )
        self.assertTrue(report["evaluated"])
        self.assertFalse(report["passes"])
        self.assertAlmostEqual(report["axis_scale_anisotropy"], 3.448369, places=5)
        self.assertEqual(report["maximum_axis_scale_anisotropy"], 2.0)

    def test_living_room_accent_chair_regression_is_rejected(self) -> None:
        policy = dimension_policy_for_category("accent_chair")
        report = runtime_mesh_fit_audit(
            [0.816941, 0.816998, 2.492108], policy
        )
        self.assertFalse(report["passes"])
        self.assertEqual(report["maximum_axis_scale_anisotropy"], 2.25)

    def test_fixed_physical_object_cannot_silently_deform(self) -> None:
        report = runtime_mesh_fit_audit(
            [1.0, 1.0, 7.5], dimension_policy_for_category("tv")
        )
        self.assertTrue(report["evaluated"])
        self.assertFalse(report["passes"])

    def test_proportionate_seating_passes(self) -> None:
        report = runtime_mesh_fit_audit(
            [1.15, 0.98, 1.08], dimension_policy_for_category("sofa")
        )
        self.assertTrue(report["passes"])

    def test_sofa_generation_contract_is_not_general_object(self) -> None:
        spec = build_asset_generation_spec(
            {
                "id": "sofa",
                "category": "sofa",
                "dimensions": {"width": 2.2, "length": 0.92, "height": 0.9},
            },
            ["modern", "warm"],
            "a warm modern living room with one cream sofa",
        )
        form = spec["semantic_form_contract"]
        self.assertEqual(form["shape_profile"], "upholstered_seating")
        self.assertEqual(form["maximum_axis_scale_anisotropy"], 2.0)
        self.assertIn("extra floor platform", form["forbidden_parts"])


if __name__ == "__main__":
    unittest.main()
