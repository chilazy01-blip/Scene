from __future__ import annotations

import unittest

import numpy as np
import trimesh

from sage.experiments.codex_trellis_scene_v2.capability_proposer import (
    propose_geometry_capabilities,
)
from sage.experiments.codex_trellis_scene_v2.multilevel_proxy import (
    build_component_aware_sdf,
)
from sage.experiments.codex_trellis_scene_v2.tests.test_multilevel_proxy import (
    open_shelf_mesh,
)


class CapabilityProposerTest(unittest.TestCase):
    def test_open_shelf_proposes_reviewable_free_space_with_entry(self) -> None:
        mesh = open_shelf_mesh()
        proxy = build_component_aware_sdf(mesh, pitch=0.025)
        proposal = propose_geometry_capabilities(mesh, proxy, asset_id="synthetic_shelf")
        self.assertTrue(proposal["automatic_approval_forbidden"])
        free_spaces = proposal["free_space_volumes"]
        self.assertTrue(free_spaces)
        cavity = max(free_spaces, key=lambda item: item["volume_m3"])
        self.assertTrue(cavity["review_required"])
        self.assertTrue(cavity["entry_axis_candidates"])
        minimum = np.asarray(cavity["min_m"])
        maximum = np.asarray(cavity["max_m"])
        self.assertTrue(np.all(minimum < maximum))

    def test_box_proposes_top_support_and_generic_anchors(self) -> None:
        mesh = trimesh.creation.box(extents=(1.0, 0.6, 0.2))
        mesh.apply_translation((0, 0, 0.1))
        proxy = build_component_aware_sdf(mesh, pitch=0.025)
        proposal = propose_geometry_capabilities(mesh, proxy, asset_id="box")
        self.assertTrue(proposal["support_surfaces"])
        self.assertGreaterEqual(len(proposal["contact_surfaces"]), 4)
        highest = proposal["support_surfaces"][0]
        self.assertAlmostEqual(highest["center_m"][2], 0.2, places=2)
        self.assertEqual(
            {item["id"] for item in proposal["semantic_anchors"]},
            {"bottom_center", "top_center", "negative_y_center", "positive_y_center"},
        )


if __name__ == "__main__":
    unittest.main()
