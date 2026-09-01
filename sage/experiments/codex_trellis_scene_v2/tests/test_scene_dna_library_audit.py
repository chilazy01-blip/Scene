from __future__ import annotations

import unittest

from ..scene_dna_library_audit import audit_asset_library


class SceneDnaLibraryAuditTest(unittest.TestCase):
    def test_reports_real_choice_coverage(self) -> None:
        assets = []
        for index, styles in enumerate((["warm", "wood"], ["warm", "wood"], ["cool", "metal"])):
            assets.append(
                {
                    "asset_id": f"desk_{index}",
                    "category": "desk",
                    "qa_status": "approved",
                    "styles": styles,
                    "dimensions": {"width": 1},
                    "asset_canonical_front": {"axis": "-y"},
                    "source": {"id": index},
                    "glb_path": f"desk_{index}.glb",
                }
            )
        report = audit_asset_library({"assets": assets}, required_categories=["desk"])
        self.assertTrue(report["ready_for_choice_reranking"])
        self.assertEqual(report["categories"]["desk"]["style_signature_count"], 2)

    def test_does_not_count_unapproved_or_invent_missing_categories(self) -> None:
        report = audit_asset_library(
            {
                "assets": [
                    {
                        "asset_id": "bookcase_1",
                        "category": "bookcase",
                        "qa_status": "pending",
                        "styles": ["wood"],
                    }
                ]
            },
            required_categories=["bookcase"],
        )
        self.assertFalse(report["ready_for_choice_reranking"])
        self.assertEqual(report["categories"]["bookcase"]["approved_asset_count"], 0)
        self.assertEqual(len(report["gaps"]), 2)


if __name__ == "__main__":
    unittest.main()
