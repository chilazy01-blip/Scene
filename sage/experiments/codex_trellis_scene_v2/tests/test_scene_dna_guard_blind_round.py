from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from ..scene_dna_guard_blind_round import build_guard_blind_comparisons


class SceneDNAGuardBlindRoundTest(unittest.TestCase):
    def test_extracts_only_changed_hard_eligible_control_guard_pair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path = root / "plan.json"
            candidate_root = root / "candidates"
            case_dir = candidate_root / "cases" / "case_one"
            case_dir.mkdir(parents=True)
            control = case_dir / "candidate_00.png"
            treatment = case_dir / "candidate_01.png"
            Image.new("RGBA", (32, 32), "red").save(control)
            Image.new("RGBA", (32, 32), "blue").save(treatment)
            plan_path.write_text(
                json.dumps(
                    {
                        "frozen_before_generation": True,
                        "category_set": "heldout_round2",
                        "form_guard_threshold_frozen_before_generation": 0.08,
                        "batches": [
                            {
                                "case_id": "case_one",
                                "category": "dining_chair",
                                "style_condition": "warm_modern",
                                "batch_seed": 17,
                                "object_prompt": "one dining chair",
                                "semantic_form_contract": {
                                    "shape_profile": "skeletal_support"
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (case_dir / "candidate_batch_result.json").write_text(
                json.dumps(
                    {
                        "reference_attempts": [
                            {
                                "reference_job_id": "control",
                                "attempt": 0,
                                "prepared_image_path": str(control),
                            },
                            {
                                "reference_job_id": "treatment",
                                "attempt": 1,
                                "prepared_image_path": str(treatment),
                            },
                        ],
                        "scene_dna_candidate_selection": {
                            "combined_selector_reference_job_id": "control",
                            "selected_reference_job_id": "treatment",
                            "selection_guard": {
                                "enabled": True,
                                "decision": "fallback_to_legacy_control",
                                "form_score_delta": 0.01,
                                "category_specific_branching": False,
                            },
                            "ranking": [
                                {"reference_job_id": "control", "eligible": True},
                                {"reference_job_id": "treatment", "eligible": True},
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )
            report = build_guard_blind_comparisons(
                plan_path, candidate_root, root / "output"
            )
            comparisons = json.loads(
                (root / "output" / "blind_comparisons.json").read_text(
                    encoding="utf-8"
                )
            )["comparisons"]
        self.assertEqual(report["blind_independent_case_count"], 1)
        self.assertTrue(report["all_compared_candidates_hard_eligible"])
        self.assertEqual(comparisons[0]["baseline"]["asset_id"], "control")
        self.assertEqual(comparisons[0]["proposed"]["asset_id"], "treatment")


if __name__ == "__main__":
    unittest.main()
