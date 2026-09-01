from __future__ import annotations

import unittest

from sage.experiments.codex_trellis_scene_v2.delivery_status import (
    PROFILE_REQUIREMENTS,
    evaluate_terminal_status,
)


class DeliveryStatusTests(unittest.TestCase):
    def test_only_complete_production_is_deliverable(self) -> None:
        stages = {name: True for name in PROFILE_REQUIREMENTS["production"]}
        report = evaluate_terminal_status("production", stages)
        self.assertTrue(report["deliverable"])
        self.assertEqual(report["terminal_status"], "production_deliverable")
        for missing in PROFILE_REQUIREMENTS["production"]:
            incomplete = dict(stages)
            incomplete[missing] = False
            report = evaluate_terminal_status("production", incomplete)
            self.assertFalse(report["deliverable"], missing)
            self.assertEqual(report["terminal_status"], "diagnostic_failure_preserved")
            self.assertIn(missing, report["missing_required_stages"])

    def test_plan_completion_is_explicitly_non_deliverable(self) -> None:
        stages = {name: True for name in PROFILE_REQUIREMENTS["plan"]}
        report = evaluate_terminal_status("plan", stages)
        self.assertTrue(report["profile_complete"])
        self.assertFalse(report["deliverable"])
        self.assertEqual(report["terminal_status"], "plan_complete_non_deliverable")


if __name__ == "__main__":
    unittest.main()
