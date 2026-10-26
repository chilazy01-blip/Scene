from __future__ import annotations

import unittest

from sage.experiments.codex_trellis_scene_v2.book_arrangement import (
    audit_upright_book_row,
    compose_upright_book_row,
)


class BookArrangementTests(unittest.TestCase):
    def test_five_separate_books_form_one_upright_depth_row(self) -> None:
        row = compose_upright_book_row(
            row_id="lower_books",
            container_id="bookcase",
            slot_id="lower_bay",
            dimensions={"width": 0.34, "length": 0.14, "height": 0.37},
            count=5,
            palette_id="warm_jewel",
            seed=42,
        )
        self.assertTrue(row["audit"]["ok"])
        self.assertEqual(len(row["books"]), 5)
        self.assertEqual(len({item["component_id"] for item in row["books"]}), 5)
        self.assertEqual(row["audit"]["depth_layer_count"], 1)
        self.assertEqual(row["audit"]["upright_count"], 5)

    def test_overlap_is_rejected(self) -> None:
        row = compose_upright_book_row(
            row_id="bad_books",
            container_id="bookcase",
            slot_id="middle_bay",
            dimensions={"width": 0.34, "length": 0.14, "height": 0.37},
            count=5,
        )
        row["books"][1]["local_pose"]["x"] = row["books"][0]["local_pose"]["x"]
        self.assertFalse(audit_upright_book_row(row)["ok"])

    def test_tilt_is_rejected_until_physics_is_modeled(self) -> None:
        row = compose_upright_book_row(
            row_id="tilted_books",
            container_id="bookcase",
            slot_id="upper_bay",
            dimensions={"width": 0.34, "length": 0.14, "height": 0.37},
            count=5,
        )
        row["books"][2]["local_pose"]["roll_degrees"] = 7.0
        report = audit_upright_book_row(row)
        self.assertFalse(report["ok"])
        self.assertIn("not_upright", {item["type"] for item in report["violations"]})


if __name__ == "__main__":
    unittest.main()
