from __future__ import annotations

import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

import numpy as np
import trimesh

from sage.experiments.codex_trellis_scene_v2.capabilities import (
    load_capability_registry,
    require_free_space,
    validate_asset_capability,
)
from sage.experiments.codex_trellis_scene_v2.collision_proxy import (
    VoxelSDF,
    build_capability_proxy,
    build_voxel_sdf,
    load_normalized_asset_mesh,
    sha256_file,
)
from sage.experiments.codex_trellis_scene_v2.sdf_pilot import (
    _aabb_footprint_ok,
    _bottom_sample_mask,
    _surface_footprint_ok,
    compare_support_strategies,
)
from sage.experiments.codex_trellis_scene_v2.under_desk_pilot import (
    classify_under_desk_points,
    compare_dense_and_sparse,
    free_space_footprint_overlap_fraction,
    footprint_overlap_fraction,
    optimize_tucked_under_pose,
)


class CapabilitySchemaTest(unittest.TestCase):
    def test_checked_in_pilot_registry_is_valid(self) -> None:
        registry_path = (
            Path(__file__).resolve().parents[1]
            / "capabilities"
            / "pilot_desk_mug_v1.json"
        )
        registry = load_capability_registry(registry_path)
        self.assertTrue(registry["validation"]["ok"])
        self.assertEqual(registry["validation"]["asset_count"], 2)

    def test_support_surface_must_stay_inside_canonical_dimensions(self) -> None:
        registry_path = (
            Path(__file__).resolve().parents[1]
            / "capabilities"
            / "pilot_desk_mug_v1.json"
        )
        registry = load_capability_registry(registry_path)
        desk = deepcopy(registry["assets"][0])
        desk["support_surfaces"][0]["half_extents_m"][0] = 1.0
        validation = validate_asset_capability(desk)
        self.assertFalse(validation["ok"])
        self.assertIn(
            "support_surfaces[0] exceeds canonical width",
            validation["errors"],
        )

    def test_duplicate_support_surface_ids_are_rejected(self) -> None:
        registry_path = (
            Path(__file__).resolve().parents[1]
            / "capabilities"
            / "pilot_desk_mug_v1.json"
        )
        registry = load_capability_registry(registry_path)
        desk = deepcopy(registry["assets"][0])
        desk["support_surfaces"].append(deepcopy(desk["support_surfaces"][0]))
        validation = validate_asset_capability(desk)
        self.assertFalse(validation["ok"])
        self.assertIn("duplicate support surface id: top", validation["errors"])

    def test_checked_in_desk_chair_registry_is_valid(self) -> None:
        registry_path = (
            Path(__file__).resolve().parents[1]
            / "capabilities"
            / "pilot_desk_chair_v1.json"
        )
        registry = load_capability_registry(registry_path)
        self.assertTrue(registry["validation"]["ok"])
        self.assertEqual(registry["validation"]["asset_count"], 2)
        desk = registry["assets"][0]
        free_space = require_free_space(desk, "under_desk")
        self.assertEqual(free_space["allowed_categories"], ["office_chair"])
        self.assertEqual(
            free_space["entry_pose"]["yaw_tolerance_degrees"], 15.0
        )

    def test_duplicate_free_space_ids_are_rejected(self) -> None:
        registry_path = (
            Path(__file__).resolve().parents[1]
            / "capabilities"
            / "pilot_desk_chair_v1.json"
        )
        registry = load_capability_registry(registry_path)
        desk = deepcopy(registry["assets"][0])
        desk["free_space_volumes"].append(
            deepcopy(desk["free_space_volumes"][0])
        )
        validation = validate_asset_capability(desk)
        self.assertFalse(validation["ok"])
        self.assertIn(
            "duplicate free-space volume id: under_desk",
            validation["errors"],
        )

    def test_free_space_must_stay_inside_canonical_dimensions(self) -> None:
        registry_path = (
            Path(__file__).resolve().parents[1]
            / "capabilities"
            / "pilot_desk_chair_v1.json"
        )
        registry = load_capability_registry(registry_path)
        desk = deepcopy(registry["assets"][0])
        desk["free_space_volumes"][0]["max_m"][0] = 0.8
        validation = validate_asset_capability(desk)
        self.assertFalse(validation["ok"])
        self.assertIn(
            "free_space_volumes[0] lies outside canonical dimensions",
            validation["errors"],
        )


class VoxelSdfTest(unittest.TestCase):
    def _box_proxy(self) -> VoxelSDF:
        mesh = trimesh.creation.box(extents=(1.0, 0.6, 0.2))
        mesh.apply_translation((0.0, 0.0, 0.1))
        return build_voxel_sdf(
            mesh,
            pitch=0.025,
            padding_voxels=3,
            fill_interior=True,
        )

    def test_voxel_sdf_has_stable_inside_and_outside_signs(self) -> None:
        proxy = self._box_proxy()
        distances = proxy.query(
            np.asarray(
                [
                    [0.0, 0.0, 0.1],
                    [0.0, 0.0, 0.25],
                    [0.8, 0.0, 0.1],
                ]
            )
        )
        self.assertLess(distances[0], 0.0)
        self.assertGreater(distances[1], 0.0)
        self.assertGreater(distances[2], 0.0)

    def test_voxel_sdf_cache_roundtrip_preserves_queries(self) -> None:
        proxy = self._box_proxy()
        points = np.asarray([[0.0, 0.0, 0.1], [0.0, 0.0, 0.25]])
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "box.npz"
            proxy.save(path)
            restored = VoxelSDF.load(path)
        np.testing.assert_allclose(
            restored.query(points),
            proxy.query(points),
            atol=1e-7,
        )

    def test_capability_proxy_reuses_matching_cache(self) -> None:
        mesh = trimesh.creation.box(extents=(1.0, 0.6, 0.2))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "box.glb"
            source.write_bytes(mesh.export(file_type="glb"))
            capability = {
                "asset_id": "box",
                "category": "box",
                "source_asset": {"sha256": sha256_file(source)},
                "coordinate_frame": {
                    "canonical_dimensions": {
                        "width": 1.0,
                        "length": 0.6,
                        "height": 0.2,
                    },
                    "source_mesh_up_axis": "z",
                    "source_mesh_up_sign": 1.0,
                },
                "collision_proxy": {
                    "source_glb": "box.glb",
                    "voxel_pitch_m": 0.025,
                    "padding_voxels": 3,
                    "fill_interior": True,
                    "surface_dilation_voxels": 0,
                },
            }
            cache = root / "box.npz"
            first, _, first_report = build_capability_proxy(
                capability, root, cache
            )
            second, _, second_report = build_capability_proxy(
                capability, root, cache
            )
        self.assertFalse(first_report["cache_hit"])
        self.assertTrue(second_report["cache_hit"])
        np.testing.assert_allclose(first.sdf, second.sdf)

    def test_raw_y_up_mesh_is_normalized_to_canonical_z_up(self) -> None:
        mesh = trimesh.creation.box(extents=(1.0, 2.0, 0.5))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "y_up.glb"
            source.write_bytes(mesh.export(file_type="glb"))
            capability = {
                "asset_id": "y_up",
                "category": "fixture",
                "source_asset": {"sha256": sha256_file(source)},
                "coordinate_frame": {
                    "canonical_dimensions": {
                        "width": 1.0,
                        "length": 0.5,
                        "height": 2.0,
                    },
                    "source_mesh_up_axis": "y",
                    "source_mesh_up_sign": 1.0,
                },
                "collision_proxy": {"source_glb": "y_up.glb"},
            }
            normalized, report = load_normalized_asset_mesh(capability, root)
        np.testing.assert_allclose(normalized.extents, [1.0, 0.5, 2.0])
        np.testing.assert_allclose(normalized.bounds[0], [-0.5, -0.25, 0.0])
        np.testing.assert_allclose(normalized.bounds[1], [0.5, 0.25, 2.0])
        self.assertEqual(report["source_mesh_up_axis"], "y")

    def test_capability_surface_reduces_aabb_support_gap(self) -> None:
        desk_proxy = self._box_proxy()
        mug = trimesh.creation.box(extents=(0.1, 0.08, 0.1))
        mug.apply_translation((0.0, 0.0, 0.05))
        mug_points, _ = trimesh.sample.sample_surface(mug, 2000, seed=11)
        mug_points = np.asarray(mug_points)
        bottom_mask = _bottom_sample_mask(mug_points, 0.1, desk_proxy.pitch)
        surface = {
            "id": "top",
            "center_m": [0.0, 0.0, 0.2],
            "normal": [0.0, 0.0, 1.0],
            "u_axis": [1.0, 0.0, 0.0],
            "v_axis": [0.0, 1.0, 0.0],
            "half_extents_m": [0.45, 0.25],
            "contact_tolerance_m": 0.025,
        }
        comparison = compare_support_strategies(
            desk_proxy,
            mug_points,
            bottom_mask,
            surface,
            desk_aabb_top_z=0.25,
            mug_dimensions={"width": 0.1, "length": 0.08, "height": 0.1},
            x=0.0,
            y=0.0,
        )
        self.assertEqual(
            [result["method"] for result in comparison["placements"]],
            ["aabb_only", "generic_mesh_sdf", "capability_aware_sdf"],
        )
        by_method = {
            result["method"]: result for result in comparison["placements"]
        }
        self.assertGreater(
            by_method["aabb_only"]["absolute_support_gap_m"],
            by_method["capability_aware_sdf"]["absolute_support_gap_m"],
        )
        self.assertLessEqual(
            by_method["capability_aware_sdf"]["absolute_support_gap_m"],
            surface["contact_tolerance_m"],
        )
        self.assertTrue(
            by_method["capability_aware_sdf"]["dimension_policy_preserved"]
        )

    def test_capability_surface_rejects_parent_aabb_edge_false_positive(
        self,
    ) -> None:
        surface = {
            "center_m": [0.0, 0.0, 0.75],
            "u_axis": [1.0, 0.0, 0.0],
            "v_axis": [0.0, 1.0, 0.0],
            "half_extents_m": [0.65, 0.30],
        }
        self.assertTrue(
            _aabb_footprint_ok(
                {"width": 1.4, "length": 0.72},
                x=0.64,
                y=0.0,
                object_width=0.12,
                object_length=0.09,
            )
        )
        self.assertFalse(
            _surface_footprint_ok(
                surface,
                x=0.64,
                y=0.0,
                object_width=0.12,
                object_length=0.09,
            )
        )


class UnderDeskSparseConsistencyTest(unittest.TestCase):
    @staticmethod
    def _desk_proxy() -> VoxelSDF:
        desktop = trimesh.creation.box(extents=(1.4, 0.72, 0.12))
        desktop.apply_translation((0.0, 0.0, 0.69))
        return build_voxel_sdf(
            desktop,
            pitch=0.025,
            padding_voxels=3,
            fill_interior=True,
        )

    def test_footprint_overlap_is_measured_against_child_area(self) -> None:
        parent = {"width": 1.4, "length": 0.72}
        child = {"width": 0.62, "length": 0.62}
        self.assertAlmostEqual(
            footprint_overlap_fraction(parent, child, x=0.0, y=-0.55),
            0.193548,
            places=5,
        )
        self.assertEqual(
            footprint_overlap_fraction(parent, child, x=0.0, y=-0.75),
            0.0,
        )

    def test_dense_and_sparse_proxies_agree_on_under_desk_cases(self) -> None:
        proxy = self._desk_proxy()
        child = trimesh.creation.box(extents=(0.4, 0.4, 0.4))
        child.apply_translation((0.0, 0.0, 0.2))
        for _ in range(4):
            child = child.subdivide()
        placements = (
            {
                "id": "outside",
                "translation_m": [0.0, -0.65, 0.0],
                "yaw_degrees": 0.0,
            },
            {
                "id": "tucked",
                "translation_m": [0.0, -0.42, 0.0],
                "yaw_degrees": 0.0,
            },
            {
                "id": "collision",
                "translation_m": [0.0, -0.20, 0.30],
                "yaw_degrees": 0.0,
            },
        )
        comparison = compare_dense_and_sparse(
            proxy,
            child,
            parent_dimensions={"width": 1.4, "length": 0.72, "height": 0.75},
            child_dimensions={"width": 0.4, "length": 0.4, "height": 0.4},
            placements=placements,
            sparse_point_count=256,
            seed=17,
        )
        self.assertTrue(comparison["ok"], comparison)
        self.assertEqual(
            [
                case["dense_reference"]["classification"]
                for case in comparison["cases"]
            ],
            ["outside", "valid_under", "collision"],
        )
        self.assertTrue(
            all(case["classification_matches"] for case in comparison["cases"])
        )

    def test_penetration_beyond_one_voxel_is_collision(self) -> None:
        proxy = self._desk_proxy()
        points = np.asarray(
            [
                [-0.1, -0.1, 0.0],
                [0.1, 0.1, 0.0],
                [0.0, 0.0, 0.69],
            ],
            dtype=np.float64,
        )
        result = classify_under_desk_points(
            proxy,
            points,
            parent_dimensions={"width": 1.4, "length": 0.72, "height": 0.75},
            child_dimensions={"width": 0.2, "length": 0.2, "height": 0.7},
            translation_m=[0.0, 0.0, 0.0],
            yaw_degrees=0.0,
        )
        self.assertEqual(result["classification"], "collision")
        self.assertGreater(result["deep_penetration_point_count"], 0)

    def test_named_free_space_overlap_accounts_for_yaw(self) -> None:
        free_space = {
            "min_m": [-0.55, -0.36, 0.0],
            "max_m": [0.55, 0.25, 0.63],
        }
        dimensions = {"width": 0.6, "length": 0.4, "height": 1.0}
        straight = free_space_footprint_overlap_fraction(
            free_space,
            dimensions,
            x=0.0,
            y=-0.55,
            yaw_degrees=0.0,
        )
        turned = free_space_footprint_overlap_fraction(
            free_space,
            dimensions,
            x=0.0,
            y=-0.55,
            yaw_degrees=90.0,
        )
        self.assertNotEqual(straight, turned)
        self.assertGreater(straight, 0.0)
        self.assertGreater(turned, 0.0)

    def test_reference_target_is_soft_but_sdf_and_facing_are_hard(self) -> None:
        class _ThresholdSdf:
            pitch = 0.01

            @staticmethod
            def query(points: np.ndarray) -> np.ndarray:
                result = np.full(len(points), 0.05, dtype=np.float64)
                result[points[:, 1] > -0.45] = -0.05
                return result

        points = np.asarray(
            [
                [-0.2, 0.0, 0.0],
                [0.2, 0.0, 0.0],
                [0.0, 0.0, 0.5],
            ],
            dtype=np.float64,
        )
        free_space = {
            "id": "under_desk",
            "min_m": [-0.55, -0.36, 0.0],
            "max_m": [0.55, 0.25, 0.63],
            "allowed_categories": ["office_chair"],
            "minimum_footprint_overlap": 0.15,
            "entry_pose": {
                "translation_bounds_m": {
                    "x": [-0.3, 0.3],
                    "y": [-0.68, -0.38],
                    "z": [0.0, 0.0],
                },
                "yaw_degrees": 180.0,
                "yaw_tolerance_degrees": 15.0,
            },
        }
        result = optimize_tucked_under_pose(
            _ThresholdSdf(),
            points,
            parent_dimensions={
                "width": 1.4,
                "length": 0.72,
                "height": 0.75,
            },
            child_dimensions={
                "width": 0.4,
                "length": 0.4,
                "height": 1.0,
            },
            free_space=free_space,
            reference_target={
                "source": "test_image_observation",
                "translation_m": [0.03, -0.40, 0.0],
                "yaw_degrees": 160.0,
                "confidence": 0.95,
            },
            baseline_pose={
                "translation_m": [0.0, -0.75, 0.0],
                "yaw_degrees": 180.0,
            },
        )
        selected = result["selected"]
        self.assertEqual(
            selected["classification"]["classification"], "valid_under"
        )
        self.assertLessEqual(float(selected["pose"]["y"]), -0.45)
        self.assertLessEqual(
            abs((float(selected["pose"]["yaw"]) - 180.0 + 180.0) % 360.0 - 180.0),
            15.0,
        )
        self.assertGreater(result["search_totals"]["collision"], 0)
        self.assertEqual(
            result["reference_target"]["source"], "test_image_observation"
        )


if __name__ == "__main__":
    unittest.main()
