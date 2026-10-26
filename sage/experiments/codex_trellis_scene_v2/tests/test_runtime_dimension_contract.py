import math
import unittest

from sage.scripts.mesh_dimension_contract import runtime_mesh_fit_audit
from sage.experiments.codex_trellis_scene_v2.dimensions import (
    dimension_policy_for_category, resolve_dimension_adaptation,
)


class RuntimeDimensionContractTests(unittest.TestCase):
    def test_exact_metadata_still_requires_real_bounds(self):
        dims = dict(width=.2858, length=.5681, height=1.5)
        policy = dimension_policy_for_category("floor_lamp")
        resolution = resolve_dimension_adaptation(dims, dims, policy)
        self.assertTrue(resolution["requires_runtime_bounds_check"])
        self.assertFalse(runtime_mesh_fit_audit([.666864, 1.285447, 1.494449], policy, resolution)["passes"])
        self.assertTrue(runtime_mesh_fit_audit([1.494449] * 3, policy, resolution)["passes"])

    def test_missing_policy_is_unassessed(self):
        report = runtime_mesh_fit_audit([1, 1, 1], {})
        self.assertFalse(report["evaluated"])
        self.assertIsNone(report["passes"])

    def test_declared_axis_adaptation_is_not_source_deformation(self):
        policy = dimension_policy_for_category("desk")
        source = dict(width=1, length=.6, height=.75)
        requested = dict(source, width=1.2)
        resolution = resolve_dimension_adaptation(source, requested, policy)
        self.assertTrue(resolution["accepted"])
        self.assertTrue(runtime_mesh_fit_audit([2.4, 2, 2], policy, resolution)["passes"])
        self.assertFalse(runtime_mesh_fit_audit([4, 2, 2], policy, {})["passes"])
        # Opting out of nonuniform source calibration restores a strict
        # comparison to the declared physical source proportions.
        policy.pop("mesh_normalization")
        self.assertFalse(runtime_mesh_fit_audit([4, 2, 2], policy, resolution)["passes"])

    def test_nonfinite_or_degenerate_scale_is_rejected(self):
        policy = dimension_policy_for_category("floor_lamp")
        for scale in ([0, 1, 1], [-1, 1, 1], [math.nan, 1, 1], [math.inf, 1, 1], [1, 1]):
            with self.subTest(scale=scale):
                self.assertFalse(runtime_mesh_fit_audit(scale, policy)["passes"])

    def test_threshold_cannot_be_disabled_by_nan(self):
        for maximum in (math.nan, math.inf, 0):
            with self.subTest(maximum=maximum), self.assertRaises(ValueError):
                runtime_mesh_fit_audit([1, 1, 1], {"runtime_mesh_fit": {"maximum_axis_scale_anisotropy": maximum}})

    def test_axis_adaptation_cannot_bypass_explicit_limit(self):
        policy = dimension_policy_for_category("desk")
        policy["runtime_mesh_fit"] = {"maximum_axis_scale_anisotropy": 1.1}
        dims = dict(width=1, length=.6, height=.75)
        resolution = resolve_dimension_adaptation(dims, dims, policy)
        self.assertFalse(runtime_mesh_fit_audit([2, 1, 1], policy, resolution)["passes"])
        self.assertTrue(runtime_mesh_fit_audit([1, 1, 1], policy, resolution)["passes"])

    def test_axis_adaptation_requires_finite_complete_target(self):
        policy = dimension_policy_for_category("desk")
        for target in ({}, dict(width=1, length=1, height=math.nan)):
            resolution = dict(accepted=True, policy_mode=policy["mode"], effective_dimensions=target)
            self.assertFalse(runtime_mesh_fit_audit([1, 1, 1], policy, resolution)["passes"])


if __name__ == "__main__":
    unittest.main()
