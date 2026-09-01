from __future__ import annotations

import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

from ..scene_dna_candidate_benchmark_runner import (
    _wait_json,
    is_retryable_infrastructure_failure,
)
from ..scene_dna_vnext import assess_2d_generability, select_vnext_candidate
from ..scene_dna_vnext_pilot import analyze_vnext_pilot, build_vnext_pilot_plan
from ..scene_dna_vnext_round3 import (
    build_round3_plan,
    extract_round3_comparisons,
    freeze_round3_artifacts,
)
from ..scene_dna_vnext_round4 import (
    build_round4_plan,
    build_round4_preflight_plan,
    freeze_round4_artifacts,
)


def _alpha_metadata(*, ok: bool = True) -> dict:
    return {
        "alpha_quality": {
            "ok": ok,
            "score": 1.0 if ok else 0.0,
            "chroma_spill_hygiene": {"ok": ok},
        }
    }


class SceneDNAVNextTest(unittest.TestCase):
    def test_round4_freeze_wrapper_uses_round4_artifact_namespace(self) -> None:
        with patch(
            "sage.experiments.codex_trellis_scene_v2.scene_dna_vnext_round4.freeze_vnext_artifacts",
            return_value={"frozen": True},
        ) as freeze:
            report = freeze_round4_artifacts(Path("/tmp/round4"))
        self.assertTrue(report["frozen"])
        freeze.assert_called_once_with(
            Path("/tmp/round4"),
            round_label="round4",
            previous_public_trials=(),
            previous_plan_paths=(),
        )

    def test_candidate_wait_tolerates_one_slow_poll_within_batch_deadline(self) -> None:
        class Response:
            status = 200
            headers = {"Content-Type": "application/json"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"status":"done"}'

        class Opener:
            calls = 0

            def open(self, *_args, **_kwargs):
                self.calls += 1
                if self.calls == 1:
                    raise TimeoutError("model cold start")
                return Response()

        opener = Opener()
        with patch(
            "sage.experiments.codex_trellis_scene_v2.scene_dna_candidate_benchmark_runner._opener",
            return_value=opener,
        ), patch(
            "sage.experiments.codex_trellis_scene_v2.scene_dna_candidate_benchmark_runner.time.sleep"
        ):
            result = _wait_json("http://127.0.0.1/job/id", timeout=10.0)
        self.assertEqual(result["status"], "done")
        self.assertEqual(opener.calls, 2)

    def test_candidate_resume_retries_only_infrastructure_failures(self) -> None:
        self.assertTrue(
            is_retryable_infrastructure_failure("TimeoutError: timed out")
        )
        self.assertTrue(
            is_retryable_infrastructure_failure("Connection refused by bridge")
        )
        self.assertTrue(
            is_retryable_infrastructure_failure(
                "ModuleNotFoundError: No module named 'diffusers'"
            )
        )
        self.assertFalse(
            is_retryable_infrastructure_failure(
                "All SceneDNA reference candidates failed the required semantic contract"
            )
        )

    def test_clean_coherent_reference_outranks_detached_platform(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            clean = Image.new("RGBA", (160, 160))
            draw = ImageDraw.Draw(clean)
            draw.rounded_rectangle((42, 32, 118, 126), radius=8, fill="white")
            clean_path = root / "clean.png"
            clean.save(clean_path)

            platform = clean.copy()
            draw = ImageDraw.Draw(platform)
            draw.rectangle((14, 135, 146, 145), fill="white")
            platform_path = root / "platform.png"
            platform.save(platform_path)

            clean_report = assess_2d_generability(
                clean_path,
                alpha_metadata=_alpha_metadata(),
                semantic_report={
                    "evaluated": True,
                    "category_margin_score": 0.8,
                    "minimum_required_part_score": 0.8,
                    "forbidden_probability": 0.05,
                },
                form_report={"evaluated": True, "score": 0.8},
            )
            platform_report = assess_2d_generability(
                platform_path,
                alpha_metadata=_alpha_metadata(),
                semantic_report={
                    "evaluated": True,
                    "category_margin_score": 0.8,
                    "minimum_required_part_score": 0.8,
                    "forbidden_probability": 0.05,
                },
                form_report={"evaluated": True, "score": 0.8},
            )
        self.assertTrue(clean_report["hard_gate_passed"])
        self.assertGreater(clean_report["score"], platform_report["score"])
        self.assertGreater(
            clean_report["evidence_scores"]["structure_coherence"],
            platform_report["evidence_scores"]["structure_coherence"],
        )

    def test_frame_crop_and_failed_hygiene_are_hard_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cropped.png"
            rgba = np.zeros((96, 96, 4), dtype=np.uint8)
            rgba[0:80, 18:78] = (200, 170, 140, 255)
            Image.fromarray(rgba, mode="RGBA").save(path)
            report = assess_2d_generability(
                path,
                alpha_metadata=_alpha_metadata(ok=False),
            )
        self.assertFalse(report["hard_gate_passed"])
        self.assertIn("foreground_touches_frame", report["hard_failures"])
        self.assertIn("alpha_quality_failed", report["hard_failures"])
        self.assertIn("chroma_spill_hygiene_failed", report["hard_failures"])

    def test_missing_semantic_evidence_is_uncertainty_not_fake_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "object.png"
            image = Image.new("RGBA", (128, 128))
            ImageDraw.Draw(image).rectangle((32, 24, 96, 104), fill="white")
            image.save(path)
            report = assess_2d_generability(
                path,
                alpha_metadata=_alpha_metadata(),
            )
        self.assertTrue(report["hard_gate_passed"])
        self.assertEqual(report["uncertainty_penalty"], 0.06)
        self.assertFalse(report["evidence"]["semantic_evaluated"])

    def test_forbidden_part_evidence_is_a_category_independent_hard_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "object.png"
            image = Image.new("RGBA", (128, 128))
            ImageDraw.Draw(image).rectangle((32, 24, 96, 104), fill="white")
            image.save(path)
            report = assess_2d_generability(
                path,
                alpha_metadata=_alpha_metadata(),
                semantic_report={
                    "evaluated": True,
                    "category_margin_score": 0.9,
                    "minimum_required_part_score": 0.8,
                    "forbidden_probability": 0.7,
                },
            )
        self.assertFalse(report["hard_gate_passed"])
        self.assertIn(
            "forbidden_part_probability_too_high", report["hard_failures"]
        )
        self.assertFalse(report["category_specific_branching"])

    def test_selector_uses_weakest_evidence_before_average_score(self) -> None:
        fragile = {
            "reference_job_id": "fragile",
            "attempt": 0,
            "scene_dna_candidate_score": {
                "score": 0.95,
                "generability": {
                    "hard_gate_passed": True,
                    "score": 0.82,
                    "reliability_floor": 0.31,
                },
            },
        }
        balanced = {
            "reference_job_id": "balanced",
            "attempt": 1,
            "scene_dna_candidate_score": {
                "score": 0.79,
                "generability": {
                    "hard_gate_passed": True,
                    "score": 0.77,
                    "reliability_floor": 0.72,
                },
            },
        }
        selected, report = select_vnext_candidate([fragile, balanced])
        self.assertEqual(selected["reference_job_id"], "balanced")
        self.assertTrue(report["selection_changed"])
        self.assertFalse(report["category_specific_branching"])

    def test_selector_reports_all_hard_failures_instead_of_best_failure(self) -> None:
        candidate = {
            "reference_job_id": "failed",
            "attempt": 0,
            "scene_dna_candidate_score": {
                "score": 0.9,
                "generability": {
                    "hard_gate_passed": False,
                    "score": 0.8,
                    "reliability_floor": 0.7,
                },
            },
        }
        _, report = select_vnext_candidate([candidate])
        self.assertTrue(report["all_candidates_failed_generability_gate"])
        self.assertEqual(
            report["decision"],
            "no_generability_eligible_candidate_reject_batch",
        )

    def test_pilot_plan_freezes_new_seed_multicategory_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = build_vnext_pilot_plan(Path(tmp), base_seed=987654321)
        self.assertTrue(report["frozen_before_generation"])
        self.assertEqual(report["batch_count"], 8)
        self.assertEqual(report["candidate_image_count"], 32)
        self.assertEqual(len({row["batch_seed"] for row in report["batches"]}), 8)
        self.assertFalse(
            report["selection_comparison"]["category_specific_branching"]
        )

    def test_pilot_analysis_requires_clean_gray_nontrivial_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_root = root / "plan"
            plan = build_vnext_pilot_plan(plan_root, candidate_count=1)
            candidate_root = root / "candidates"
            for index, batch in enumerate(plan["batches"]):
                case_dir = candidate_root / "cases" / batch["case_id"]
                case_dir.mkdir(parents=True)
                image_path = case_dir / "candidate.png"
                image = Image.new("RGBA", (64, 64))
                ImageDraw.Draw(image).rectangle((16, 12, 48, 52), fill="white")
                image.save(image_path)
                current = f"current-{index}"
                vnext = f"vnext-{index}" if index == 0 else current
                payload = {
                    "reference_attempts": [
                        {
                            "reference_job_id": vnext,
                            "prepared_image_path": str(image_path),
                            "background": "simple solid light gray background",
                        }
                    ],
                    "scene_dna_candidate_selection": {
                        "combined_selector_reference_job_id": current,
                        "vnext_selector_reference_job_id": vnext,
                        "selected_reference_job_id": vnext,
                        "vnext_selection": {
                            "selection_changed": index == 0,
                            "hard_eligible_candidate_count": 1,
                            "all_candidates_failed_generability_gate": False,
                        },
                    },
                }
                (case_dir / "candidate_batch_result.json").write_text(
                    json.dumps(payload), encoding="utf-8"
                )
            report = analyze_vnext_pilot(
                plan_root / "scene_dna_vnext_pilot_plan.json",
                candidate_root,
                root / "analysis.json",
            )
        self.assertTrue(report["engineering_gates_passed"])
        self.assertEqual(report["gates"]["selector_change_count"], 1)
        self.assertEqual(
            report["gates"][
                "review_eligible_alpha_chroma_hygiene_pass_fraction"
            ],
            1.0,
        )

    def test_round3_plan_preregisters_one_hundred_new_batches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = build_round3_plan(Path(tmp), base_seed=314159265)
        self.assertEqual(report["batch_count"], 100)
        self.assertEqual(report["candidate_image_count"], 400)
        self.assertEqual(report["category_count"], 10)
        self.assertEqual(report["seeds_per_category_style"], 5)
        all_seeds = [
            seed for batch in report["batches"] for seed in batch["candidate_seeds"]
        ]
        self.assertEqual(len(set(all_seeds)), 400)
        self.assertEqual(report["globally_unique_candidate_seed_count"], 400)
        self.assertFalse(report["comparison"]["category_specific_branching"])
        self.assertFalse(report["comparison"]["old_form_guard_used"])

    def test_round4_requires_passing_isolated_preflight_and_new_seeds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            previous_root = root / "previous"
            build_round3_plan(previous_root, base_seed=101_000_001)
            previous_path = previous_root / "scene_dna_vnext_round3_plan.json"
            preflight_root = root / "preflight"
            preflight = build_round4_preflight_plan(
                preflight_root,
                base_seed=202_000_001,
                previous_plan_paths=[previous_path],
            )
            self.assertEqual(preflight["batch_count"], 10)
            self.assertEqual(preflight["candidate_image_count"], 40)
            self.assertEqual(
                preflight["seed_isolation"]["previous_seed_overlap_count"], 0
            )
            report_path = preflight_root / "analysis.json"
            report_path.write_text(
                json.dumps({"engineering_gates_passed": False}), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "preflight gates did not pass"):
                build_round4_plan(
                    root / "formal",
                    preflight_report_path=report_path,
                    previous_plan_paths=[previous_path],
                )
            report_path.write_text(
                json.dumps({"engineering_gates_passed": True}), encoding="utf-8"
            )
            preflight_plan_path = (
                preflight_root / "scene_dna_vnext_round4_preflight_plan.json"
            )
            formal = build_round4_plan(
                root / "formal",
                preflight_report_path=report_path,
                base_seed=303_000_001,
                previous_plan_paths=[previous_path, preflight_plan_path],
            )
        self.assertEqual(formal["batch_count"], 100)
        self.assertEqual(formal["candidate_image_count"], 400)
        self.assertEqual(formal["seed_isolation"]["previous_seed_overlap_count"], 0)
        self.assertTrue(formal["independent_preflight_passed_before_freeze"])

    def test_round3_extraction_keeps_only_clean_changed_comparisons(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_root = root / "plan"
            plan = build_round3_plan(
                plan_root,
                seeds_per_category_style=1,
                candidate_count=2,
            )
            plan["batches"] = plan["batches"][:1]
            plan["batch_count"] = 1
            plan["freeze_gates"]["completed_independent_batch_count"] = 1
            plan["freeze_gates"]["minimum_changed_comparable_cases"] = 1
            plan_path = plan_root / "small.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            candidate_root = root / "candidates"
            case = candidate_root / "cases" / plan["batches"][0]["case_id"]
            case.mkdir(parents=True)
            attempts = []
            for index, identifier in enumerate(("current", "vnext")):
                image_path = case / f"{identifier}.png"
                image = Image.new("RGBA", (64, 64))
                ImageDraw.Draw(image).rectangle(
                    (16 + index, 12, 48, 52), fill="white"
                )
                image.save(image_path)
                attempts.append(
                    {
                        "reference_job_id": identifier,
                        "prepared_image_path": str(image_path),
                        "background": "simple solid light gray background",
                    }
                )
            result = {
                "reference_attempts": attempts,
                "scene_dna_candidate_selection": {
                    "combined_selector_reference_job_id": "current",
                    "vnext_selector_reference_job_id": "vnext",
                },
            }
            (case / "candidate_batch_result.json").write_text(
                json.dumps(result), encoding="utf-8"
            )
            report = extract_round3_comparisons(
                plan_path, candidate_root, root / "extracted"
            )
        self.assertTrue(report["freeze_gates_passed"])
        self.assertEqual(report["frozen_independent_case_count"], 1)
        self.assertEqual(report["selected_pair_image_hygiene_pass_fraction"], 1.0)

    def test_round3_extraction_counts_recorded_rejection_as_completed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_root = root / "plan"
            plan = build_round3_plan(
                plan_root,
                seeds_per_category_style=1,
                candidate_count=2,
            )
            plan["batches"] = plan["batches"][:1]
            plan["batch_count"] = 1
            plan["freeze_gates"]["completed_independent_batch_count"] = 1
            plan["freeze_gates"]["minimum_changed_comparable_cases"] = 0
            plan_path = plan_root / "small.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            candidate_root = root / "candidates"
            case = candidate_root / "cases" / plan["batches"][0]["case_id"]
            case.mkdir(parents=True)
            (case / "candidate_batch_failure.json").write_text(
                json.dumps(
                    {
                        "schema": "scene_dna_candidate_batch_failure_v1",
                        "case_id": plan["batches"][0]["case_id"],
                        "error": "all candidates rejected by semantic hard gate",
                    }
                ),
                encoding="utf-8",
            )
            report = extract_round3_comparisons(
                plan_path, candidate_root, root / "extracted"
            )
        self.assertFalse(report["freeze_gates_passed"])
        self.assertEqual(report["completed_batch_count"], 1)
        self.assertEqual(report["rejected_batch_count"], 1)
        self.assertEqual(report["missing_case_ids"], [])

    def test_round3_freeze_validates_public_private_separation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = {
                "freeze_gates": {"minimum_hidden_repeat_fraction": 0.10},
                "batches": [{"candidate_seeds": [101, 102]}],
            }
            (root / "scene_dna_vnext_round3_plan.json").write_text(
                json.dumps(plan), encoding="utf-8"
            )
            extraction_dir = root / "round3_extraction"
            extraction_dir.mkdir()
            extraction = {
                "freeze_gates_passed": True,
                "frozen_independent_case_count": 1,
                "completed_batch_count": 1,
                "rejected_batch_count": 0,
                "changed_comparable_case_count_before_cap": 1,
                "selected_pair_image_hygiene_pass_fraction": 1.0,
                "fixed_neutral_background_fraction": 1.0,
            }
            (extraction_dir / "extraction_report.json").write_text(
                json.dumps(extraction), encoding="utf-8"
            )
            (extraction_dir / "blind_comparisons.json").write_text(
                json.dumps({"comparisons": []}), encoding="utf-8"
            )
            bundle = root / "blind_review_bundle_2d_round3"
            images = bundle / "images"
            images.mkdir(parents=True)
            public_trials = []
            key_trials = []
            for index, trial_id in enumerate(("trial_original", "trial_repeat")):
                assets = {}
                key_assets = {}
                for side, method in (("left", "proposed"), ("right", "baseline")):
                    image_name = f"{trial_id}_{side}.png"
                    Image.new("RGB", (256, 256), (224, 224, 224)).save(
                        images / image_name
                    )
                    assets[side] = {"image_path": f"images/{image_name}"}
                    key_assets[side] = {"method": method}
                public_trials.append(
                    {
                        "trial_id": trial_id,
                        "case_id": "case_1",
                        "category": "chair",
                        "assets": assets,
                    }
                )
                key_trials.append(
                    {
                        "trial_id": trial_id,
                        "case_id": "case_1",
                        "duplicate_of_trial_id": (
                            "trial_original" if index else None
                        ),
                        "assets": key_assets,
                    }
                )
            (bundle / "trials.json").write_text(
                json.dumps({"trials": public_trials}), encoding="utf-8"
            )
            (root / "sealed_blind_key_2d_round3.json").write_text(
                json.dumps({"trials": key_trials}), encoding="utf-8"
            )
            (root / "SceneDNA_blind_review_2D_round3_offline.html").write_text(
                "<html>frozen</html>", encoding="utf-8"
            )
            (root / "round3_image_audit.json").write_text(
                json.dumps({"strict_bundle_passed": True}), encoding="utf-8"
            )
            manifest = freeze_round3_artifacts(root)
        self.assertTrue(manifest["frozen"])
        self.assertEqual(manifest["independent_trial_count"], 1)
        self.assertEqual(manifest["hidden_repeat_count"], 1)
        self.assertEqual(manifest["previous_round_candidate_seed_overlap_count"], 0)


if __name__ == "__main__":
    unittest.main()
