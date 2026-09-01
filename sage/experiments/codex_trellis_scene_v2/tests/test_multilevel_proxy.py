from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import trimesh

from sage.experiments.codex_trellis_scene_v2.multilevel_proxy import (
    ProxyLevelSpec,
    build_component_aware_sdf,
    compile_multilevel_proxy,
    load_multilevel_proxy,
    save_multilevel_proxy,
)
from sage.experiments.codex_trellis_scene_v2.compile_collision_proxies import (
    parse_level_specs,
)


def open_shelf_mesh() -> trimesh.Trimesh:
    parts = []
    for extents, translation in [
        ((1.0, 0.4, 0.08), (0, 0, 0.04)),
        ((1.0, 0.4, 0.08), (0, 0, 0.96)),
        ((0.08, 0.4, 0.84), (-0.46, 0, 0.5)),
        ((0.08, 0.4, 0.84), (0.46, 0, 0.5)),
        ((0.84, 0.08, 0.84), (0, 0.16, 0.5)),
    ]:
        part = trimesh.creation.box(extents=extents)
        part.apply_translation(translation)
        parts.append(part)
    return trimesh.util.concatenate(parts)


class ComponentAwareProxyTest(unittest.TestCase):
    def test_open_shelf_cavity_and_front_portal_remain_free(self) -> None:
        proxy = build_component_aware_sdf(
            open_shelf_mesh(),
            pitch=0.025,
            padding_voxels=3,
            surface_dilation_voxels=1,
        )
        distances = proxy.query(
            np.asarray(
                [
                    [0.0, 0.0, 0.5],
                    [0.0, -0.24, 0.5],
                    [0.0, 0.18, 0.5],
                ]
            )
        )
        self.assertGreater(distances[0], 0.05)
        self.assertGreater(distances[1], 0.0)
        self.assertLess(distances[2], 0.0)
        self.assertEqual(proxy.metadata["component_count"], 5)
        self.assertEqual(
            proxy.metadata["component_strategy"], "connected_components_streaming"
        )
        self.assertTrue(all(item["interior_filled"] for item in proxy.metadata["components"]))

    def test_nonwatertight_component_is_not_interior_filled(self) -> None:
        panel = trimesh.Trimesh(
            vertices=[[-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0]],
            faces=[[0, 1, 2], [0, 2, 3]],
            process=False,
        )
        proxy = build_component_aware_sdf(panel, pitch=0.1, padding_voxels=2)
        self.assertFalse(proxy.metadata["components"][0]["interior_filled"])

    def test_component_budget_falls_back_without_sealing_whole_asset(self) -> None:
        parts = []
        for x in (-1.0, 0.0, 1.0):
            part = trimesh.creation.box(extents=(0.2, 0.2, 0.2))
            part.apply_translation((x, 0, 0))
            parts.append(part)
        proxy = build_component_aware_sdf(
            trimesh.util.concatenate(parts),
            pitch=0.05,
            maximum_split_components=2,
        )
        self.assertEqual(proxy.metadata["source_component_count"], 3)
        self.assertEqual(
            proxy.metadata["component_strategy"], "global_surface_budget_fallback"
        )
        self.assertFalse(proxy.metadata["components"][0]["interior_filled"])

    def test_multilevel_roundtrip_and_error_bounds(self) -> None:
        proxy = compile_multilevel_proxy(
            open_shelf_mesh(),
            [
                ProxyLevelSpec("coarse", 0.05, 1),
                ProxyLevelSpec("fine", 0.025, 1),
            ],
        )
        levels = proxy.manifest["levels"]
        self.assertEqual(proxy.manifest["coarsest_level"], "coarse")
        self.assertEqual(proxy.manifest["finest_level"], "fine")
        self.assertGreater(
            levels[0]["max_discretization_error_m"],
            levels[1]["max_discretization_error_m"],
        )
        with tempfile.TemporaryDirectory() as temporary:
            manifest = save_multilevel_proxy(proxy, Path(temporary))
            restored = load_multilevel_proxy(manifest)
            query = np.asarray([[0.0, 0.0, 0.5]])
            np.testing.assert_allclose(restored.query(query), proxy.query(query))

    def test_cli_level_spec_is_explicit_and_validated(self) -> None:
        specs = parse_level_specs("search:0.05:2,verify:0.01:1")
        self.assertEqual([spec.name for spec in specs], ["search", "verify"])
        self.assertEqual(specs[0].surface_dilation_voxels, 2)


if __name__ == "__main__":
    unittest.main()
