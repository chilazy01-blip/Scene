from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from ..brief import build_asset_generation_spec
from ..scene_dna_benchmark import build_benchmark_plan
from ..scene_dna_blind_review import (
    analyze_responses,
    audit_bundle_chroma_spill,
    export_offline_bundle,
    prepare_blind_bundle,
)
from ..scene_dna_review_audit import _experiment_context, replay_form_guard_on_candidate_root
from ..scene_dna_semantic import (
    Siglip2SemanticScorer,
    form_improvement_guard,
    score_form_contract,
    selection_uncertainty,
)


class SceneDNASemanticFormTest(unittest.TestCase):
    def test_review_audit_uses_guard_round_method_semantics(self) -> None:
        context = _experiment_context(
            {
                "schema": "scene_dna_guard_blind_comparisons_v1",
                "control_method": "current_selector",
                "proposed_method": "form_guard_0.08",
                "conditional_estimand": "changed_cases_only",
            }
        )
        self.assertTrue(context["is_guard_round"])
        self.assertEqual(context["control_label"], "current_selector")
        self.assertEqual(context["treatment_label"], "form_guard_0.08")
        self.assertEqual(context["conditional_estimand"], "changed_cases_only")

    def test_siglip_scores_all_hypotheses_in_one_forward_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "object.png"
            Image.new("RGBA", (32, 32), "white").save(image_path)
            scorer = Siglip2SemanticScorer("unused")
            calls: list[list[str]] = []

            def fake_logits(_image, prompts):
                calls.append(list(prompts))
                return [float(index) for index in range(len(prompts))]

            scorer._logits = fake_logits  # type: ignore[method-assign]
            report = scorer.score(
                image_path,
                {
                    "identity": "chair",
                    "required_parts": ["seat", "backrest"],
                    "hard_negative_identities": ["stool"],
                    "forbidden_parts": ["platform"],
                },
            )
        self.assertTrue(report["evaluated"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(calls[0]), 7)
        self.assertEqual(
            report["gate_thresholds"]["minimum_required_part_score"], 0.0
        )

    def test_generation_spec_contains_auditable_bookcase_contract(self) -> None:
        spec = build_asset_generation_spec(
            {
                "id": "shelf",
                "category": "bookcase",
                "dimensions": {"width": 0.9, "length": 0.3, "height": 1.6},
            },
            ["warm", "modern"],
            "A warm modern room with one open bookcase.",
        )
        contract = spec["semantic_form_contract"]
        self.assertEqual(contract["shape_profile"], "open_repeated_frame")
        self.assertIn("multiple horizontal shelves", contract["required_parts"])
        self.assertIn("closed wardrobe", contract["hard_negative_identities"])

    def test_form_profiles_distinguish_closed_box_and_open_shelf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            box = Image.new("RGBA", (128, 128))
            ImageDraw.Draw(box).rectangle((20, 30, 108, 100), fill="white")
            box_path = root / "box.png"
            box.save(box_path)
            shelf = Image.new("RGBA", (128, 128))
            draw = ImageDraw.Draw(shelf)
            draw.rectangle((20, 10, 28, 118), fill="white")
            draw.rectangle((100, 10, 108, 118), fill="white")
            for y in (10, 45, 80, 110):
                draw.rectangle((20, y, 108, y + 7), fill="white")
            shelf_path = root / "shelf.png"
            shelf.save(shelf_path)
            box_as_box = score_form_contract(
                box_path, {"shape_profile": "compact_orthogonal"}
            )
            box_as_shelf = score_form_contract(
                box_path, {"shape_profile": "open_repeated_frame"}
            )
            shelf_as_shelf = score_form_contract(
                shelf_path, {"shape_profile": "open_repeated_frame"}
            )
        self.assertTrue(box_as_box["gate_passed"])
        self.assertFalse(box_as_shelf["gate_passed"])
        self.assertTrue(shelf_as_shelf["gate_passed"])
        self.assertGreater(shelf_as_shelf["score"], box_as_shelf["score"])

    def test_open_back_footwear_profile_rejects_tall_closed_heel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            slide = Image.new("RGBA", (128, 96))
            draw = ImageDraw.Draw(slide)
            draw.rectangle((10, 68, 116, 84), fill="white")
            draw.polygon(((18, 68), (34, 26), (78, 34), (84, 68)), fill="white")
            slide_path = root / "slide.png"
            slide.save(slide_path)
            closed = Image.new("RGBA", (128, 96))
            draw = ImageDraw.Draw(closed)
            draw.rectangle((10, 68, 116, 84), fill="white")
            draw.polygon(((18, 68), (34, 26), (100, 32), (112, 68)), fill="white")
            closed_path = root / "closed.png"
            closed.save(closed_path)
            slide_report = score_form_contract(
                slide_path, {"shape_profile": "open_back_footwear"}
            )
            closed_report = score_form_contract(
                closed_path, {"shape_profile": "open_back_footwear"}
            )
        self.assertTrue(slide_report["gate_passed"], slide_report)
        self.assertFalse(closed_report["gate_passed"], closed_report)
        self.assertLess(
            slide_report["features"]["maximum_end_height_ratio"],
            closed_report["features"]["maximum_end_height_ratio"],
        )

    def test_uncertainty_promotes_top_two_for_small_margin_or_conflict(self) -> None:
        small = selection_uncertainty([0.81, 0.80], margin_threshold=0.03)
        conflict = selection_uncertainty(
            [0.90, 0.80], margin_threshold=0.03, scorer_conflict=True
        )
        clear = selection_uncertainty([0.90, 0.80], margin_threshold=0.03)
        self.assertEqual(small["recommended_promotion_count"], 2)
        self.assertEqual(conflict["recommended_promotion_count"], 2)
        self.assertEqual(clear["recommended_promotion_count"], 1)

    def test_development_form_guard_requires_measured_category_independent_gain(self) -> None:
        accepted = form_improvement_guard(
            {"form": {"evaluated": True, "score": 0.91}},
            {"form": {"evaluated": True, "score": 0.80}},
            minimum_form_improvement=0.08,
        )
        rejected = form_improvement_guard(
            {"form": {"evaluated": True, "score": 0.85}},
            {"form": {"evaluated": True, "score": 0.80}},
            minimum_form_improvement=0.08,
        )
        missing = form_improvement_guard(
            {"form": {"evaluated": False, "score": None}},
            {"form": {"evaluated": True, "score": 0.80}},
        )
        self.assertTrue(accepted["accepted_proposed_selection"])
        self.assertFalse(rejected["accepted_proposed_selection"])
        self.assertFalse(missing["accepted_proposed_selection"])
        self.assertFalse(accepted["category_specific_branching"])
        self.assertEqual(
            accepted["calibration_status"],
            "development_only_requires_heldout_validation",
        )

    def test_form_guard_candidate_replay_never_selects_ineligible_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "cases"
            case = root / "case_one"
            case.mkdir(parents=True)
            (case / "candidate_batch_result.json").write_text(
                json.dumps(
                    {
                        "scene_dna_candidate_selection": {
                            "ranking": [
                                {
                                    "reference_job_id": "combined",
                                    "eligible": True,
                                    "score": {
                                        "score": 0.9,
                                        "legacy_pixel_score": 0.6,
                                        "form": {"evaluated": True, "score": 0.85},
                                    },
                                },
                                {
                                    "reference_job_id": "legacy",
                                    "eligible": True,
                                    "score": {
                                        "score": 0.7,
                                        "legacy_pixel_score": 0.9,
                                        "form": {"evaluated": True, "score": 0.80},
                                    },
                                },
                                {
                                    "reference_job_id": "ineligible",
                                    "eligible": False,
                                    "score": {
                                        "score": 1.0,
                                        "legacy_pixel_score": 1.0,
                                        "form": {"evaluated": True, "score": 1.0},
                                    },
                                },
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            replay = replay_form_guard_on_candidate_root(root)
        self.assertEqual(replay["decision_counts"]["fallback_to_legacy"], 1)
        self.assertTrue(replay["all_guarded_candidates_eligible"])
        self.assertEqual(
            replay["cases"][0]["guarded_reference_job_id"], "legacy"
        )

    def test_benchmark_plan_has_seven_families_and_168_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = build_benchmark_plan(Path(tmp))
        self.assertEqual(report["category_count"], 7)
        self.assertEqual(report["batch_count"], 42)
        self.assertEqual(report["candidate_image_count"], 168)
        self.assertGreaterEqual(len(report["shape_profiles"]), 7)

    def test_round_two_plan_adds_heldout_categories_and_freezes_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = build_benchmark_plan(
                Path(tmp),
                base_seed=2026082401,
                category_set="heldout_round2",
            )
        self.assertEqual(report["category_count"], 10)
        self.assertEqual(report["batch_count"], 60)
        self.assertEqual(report["candidate_image_count"], 240)
        self.assertTrue(report["heldout_from_form_guard_calibration"])
        self.assertEqual(report["form_guard_threshold_frozen_before_generation"], 0.08)
        self.assertIn("accent_chair", report["categories"])
        self.assertIn("dining_chair", report["categories"])
        self.assertIn("floor_lamp", report["categories"])

    def test_blind_bundle_hides_methods_and_analysis_unseals_choices(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            left = root / "left.png"
            right = root / "right.png"
            Image.new("RGB", (16, 16), "red").save(left)
            Image.new("RGB", (16, 16), "blue").save(right)
            comparisons = root / "comparisons.json"
            comparisons.write_text(
                json.dumps(
                    {
                        "comparisons": [
                            {
                                "case_id": "case",
                                "category": "storage_box",
                                "shape_profile": "compact_orthogonal",
                                "object_requirement": "one storage box",
                                "style_requirement": "warm modern",
                                "baseline": {"asset_id": "old", "image_path": str(left)},
                                "proposed": {"asset_id": "new", "image_path": str(right)},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            bundle = root / "bundle"
            key = root / "sealed.json"
            public = prepare_blind_bundle(
                comparisons, bundle, sealed_key_path=key, random_seed=3
            )
            serialized = json.dumps(public)
            self.assertNotIn('"baseline"', serialized)
            self.assertNotIn('"proposed"', serialized)
            sealed = json.loads(key.read_text(encoding="utf-8"))
            self.assertEqual(len(public["trials"]), 2)
            self.assertEqual(sealed["hidden_repeat_count"], 1)
            responses = root / "responses.jsonl"
            response_rows = []
            for trial in sealed["trials"]:
                proposed_side = next(
                    side
                    for side in ("left", "right")
                    if trial["assets"][side]["method"] == "proposed"
                )
                response_rows.append(
                    {
                        "trial_id": trial["trial_id"],
                        "reviewer_id": "reviewer",
                        **{
                            f"{axis}_choice": proposed_side
                            for axis in ("semantic", "form", "style", "overall")
                        },
                    }
                )
            responses.write_text(
                "\n".join(json.dumps(row) for row in response_rows) + "\n",
                encoding="utf-8",
            )
            analysis = analyze_responses(
                responses, key, root / "analysis.json"
            )
        self.assertEqual(analysis["primary_semantic_form_preference_rate"], 1.0)
        self.assertEqual(analysis["axes"]["semantic"]["independent_trial_count"], 1)
        self.assertEqual(analysis["reviewer_repeat_exact_agreement_rate"], 1.0)

    def test_blind_bundle_randomizes_but_balances_independent_sides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            left = root / "left.png"
            right = root / "right.png"
            Image.new("RGB", (16, 16), "red").save(left)
            Image.new("RGB", (16, 16), "blue").save(right)
            comparisons = root / "comparisons.json"
            comparisons.write_text(
                json.dumps(
                    {
                        "comparisons": [
                            {
                                "case_id": f"case_{index}",
                                "category": "storage_box",
                                "shape_profile": "compact_orthogonal",
                                "object_requirement": "one storage box",
                                "style_requirement": "warm modern",
                                "baseline": {"asset_id": f"old_{index}", "image_path": str(left)},
                                "proposed": {"asset_id": f"new_{index}", "image_path": str(right)},
                            }
                            for index in range(6)
                        ]
                    }
                ),
                encoding="utf-8",
            )
            key_path = root / "sealed.json"
            prepare_blind_bundle(
                comparisons,
                root / "bundle",
                sealed_key_path=key_path,
                random_seed=11,
                duplicate_fraction=0.34,
            )
            key = json.loads(key_path.read_text(encoding="utf-8"))
        independent = [
            item for item in key["trials"] if item["duplicate_of_trial_id"] is None
        ]
        proposed_sides = [
            side
            for item in independent
            for side in ("left", "right")
            if item["assets"][side]["method"] == "proposed"
        ]
        self.assertEqual(proposed_sides.count("left"), 3)
        self.assertEqual(proposed_sides.count("right"), 3)
        positions = {
            item["trial_id"]: index for index, item in enumerate(key["trials"])
        }
        repeat_distances = [
            abs(positions[item["trial_id"]] - positions[item["duplicate_of_trial_id"]])
            for item in key["trials"]
            if item["duplicate_of_trial_id"] is not None
        ]
        self.assertTrue(repeat_distances)
        self.assertGreaterEqual(min(repeat_distances), 3)

    def test_blind_bundle_precomposites_alpha_on_fixed_neutral_background(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cutout = np.zeros((64, 64, 4), dtype=np.uint8)
            cutout[:, :, :3] = (230, 10, 105)
            cutout[20:44, 20:44, :3] = (190, 160, 120)
            cutout[20:44, 20:44, 3] = 255
            source = root / "cutout.png"
            Image.fromarray(cutout, mode="RGBA").save(source)
            comparisons = root / "comparisons.json"
            comparisons.write_text(
                json.dumps(
                    {
                        "comparisons": [
                            {
                                "case_id": "case",
                                "category": "storage_box",
                                "baseline": {
                                    "asset_id": "old",
                                    "image_path": str(source),
                                },
                                "proposed": {
                                    "asset_id": "new",
                                    "image_path": str(source),
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            bundle = root / "bundle"
            key_path = root / "sealed.json"
            public = prepare_blind_bundle(
                comparisons,
                bundle,
                sealed_key_path=key_path,
                random_seed=7,
                duplicate_fraction=0.0,
            )
            output = Image.open(
                bundle / public["trials"][0]["assets"]["left"]["image_path"]
            )
            sealed = json.loads(key_path.read_text(encoding="utf-8"))
        self.assertEqual(output.mode, "RGB")
        self.assertEqual(output.getpixel((0, 0)), (224, 224, 224))
        self.assertTrue(
            public["review_image_standardization"]["chroma_spill_qa_required"]
        )
        self.assertTrue(
            sealed["trials"][0]["assets"]["left"]["review_image_qa"][
                "alpha_renderer_independent"
            ]
        )

    def test_blind_bundle_uses_private_recorded_background_without_leaking_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "warm_cutout.png"
            rgba = np.zeros((64, 64, 4), dtype=np.uint8)
            rgba[12:52, 12:52, :3] = (250, 225, 145)
            rgba[12:52, 12:52, 3] = 4
            rgba[16:48, 16:48, :3] = (210, 165, 95)
            rgba[16:48, 16:48, 3] = 255
            Image.fromarray(rgba, mode="RGBA").save(source)
            asset = {
                "asset_id": "asset",
                "image_path": str(source),
                "alpha_hygiene_background_rgb": [224, 224, 224],
            }
            comparisons = root / "comparisons.json"
            comparisons.write_text(
                json.dumps(
                    {
                        "comparisons": [
                            {
                                "case_id": "case",
                                "category": "storage_box",
                                "baseline": asset,
                                "proposed": asset,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            key_path = root / "sealed.json"
            public = prepare_blind_bundle(
                comparisons,
                root / "bundle",
                sealed_key_path=key_path,
                duplicate_fraction=0.0,
            )
            sealed = json.loads(key_path.read_text(encoding="utf-8"))
        self.assertNotIn("alpha_hygiene_background_rgb", json.dumps(public))
        qa = sealed["trials"][0]["assets"]["left"]["review_image_qa"]
        self.assertEqual(qa["hygiene_mode"], "recorded_background_non_mutating_audit")
        self.assertTrue(qa["chroma_spill_hygiene"]["ok"], qa)

    def test_blind_bundle_recorded_background_rejects_true_residual_spill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "spill.png"
            rgba = np.zeros((64, 64, 4), dtype=np.uint8)
            rgba[10:54, 10:54, :3] = (230, 10, 105)
            rgba[10:54, 10:54, 3] = 96
            rgba[18:46, 18:46, :3] = (190, 160, 120)
            rgba[18:46, 18:46, 3] = 255
            Image.fromarray(rgba, mode="RGBA").save(source)
            asset = {
                "asset_id": "asset",
                "image_path": str(source),
                "alpha_hygiene_background_rgb": [230, 10, 105],
            }
            comparisons = root / "comparisons.json"
            comparisons.write_text(
                json.dumps(
                    {
                        "comparisons": [
                            {
                                "case_id": "case",
                                "category": "storage_box",
                                "baseline": asset,
                                "proposed": asset,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "chroma-spill QA"):
                prepare_blind_bundle(
                    comparisons,
                    root / "bundle",
                    sealed_key_path=root / "key.json",
                    duplicate_fraction=0.0,
                )

    def test_bundle_chroma_audit_passes_standardized_review_images(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.png"
            rgba = np.zeros((32, 32, 4), dtype=np.uint8)
            rgba[8:24, 8:24] = (180, 150, 110, 255)
            Image.fromarray(rgba, mode="RGBA").save(source)
            comparisons = root / "comparisons.json"
            comparisons.write_text(
                json.dumps(
                    {
                        "comparisons": [
                            {
                                "case_id": "case",
                                "category": "storage_box",
                                "baseline": {"asset_id": "a", "image_path": str(source)},
                                "proposed": {"asset_id": "b", "image_path": str(source)},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            bundle = root / "bundle"
            key = root / "key.json"
            prepare_blind_bundle(
                comparisons,
                bundle,
                sealed_key_path=key,
                duplicate_fraction=0.0,
            )
            report = audit_bundle_chroma_spill(
                bundle, root / "audit.json", sealed_key_path=key
            )
        self.assertTrue(report["strict_bundle_passed"], report)
        self.assertEqual(report["independent_image_count"], 2)
        self.assertEqual(report["failed_image_count"], 0)

    def test_blind_bundle_rejects_residual_chroma_contamination(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "contaminated.png"
            rgba = np.zeros((64, 64, 4), dtype=np.uint8)
            rgba[:, :, :3] = (230, 10, 105)
            rgba[12:52, 12:52, 3] = 255
            Image.fromarray(rgba, mode="RGBA").save(source)
            comparisons = root / "comparisons.json"
            comparisons.write_text(
                json.dumps(
                    {
                        "comparisons": [
                            {
                                "case_id": "case",
                                "category": "storage_box",
                                "baseline": {"asset_id": "a", "image_path": str(source)},
                                "proposed": {"asset_id": "b", "image_path": str(source)},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "chroma-spill QA"):
                prepare_blind_bundle(
                    comparisons,
                    root / "bundle",
                    sealed_key_path=root / "key.json",
                    duplicate_fraction=0.0,
                )

    def test_blind_analysis_reports_neither_but_excludes_it_from_preference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            left = root / "left.png"
            right = root / "right.png"
            Image.new("RGB", (16, 16), "red").save(left)
            Image.new("RGB", (16, 16), "blue").save(right)
            comparisons = root / "comparisons.json"
            comparisons.write_text(
                json.dumps(
                    {
                        "comparisons": [
                            {
                                "case_id": "case",
                                "category": "storage_box",
                                "shape_profile": "compact_orthogonal",
                                "object_requirement": "one storage box",
                                "style_requirement": "warm modern",
                                "baseline": {"asset_id": "old", "image_path": str(left)},
                                "proposed": {"asset_id": "new", "image_path": str(right)},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            bundle = root / "bundle"
            key = root / "sealed.json"
            prepare_blind_bundle(
                comparisons,
                bundle,
                sealed_key_path=key,
                random_seed=3,
                duplicate_fraction=0.0,
            )
            trial = json.loads(key.read_text(encoding="utf-8"))["trials"][0]
            proposed_side = next(
                side
                for side in ("left", "right")
                if trial["assets"][side]["method"] == "proposed"
            )
            responses = root / "responses.jsonl"
            rows = [
                {
                    "trial_id": trial["trial_id"],
                    "reviewer_id": "reviewer_01",
                    **{f"{axis}_choice": proposed_side for axis in ("semantic", "form", "style", "overall")},
                },
                {
                    "trial_id": trial["trial_id"],
                    "reviewer_id": "reviewer_02",
                    **{f"{axis}_choice": "neither" for axis in ("semantic", "form", "style", "overall")},
                },
            ]
            responses.write_text(
                "\n".join(json.dumps(row) for row in rows) + "\n",
                encoding="utf-8",
            )
            analysis = analyze_responses(responses, key, root / "analysis.json")
        semantic = analysis["axes"]["semantic"]
        self.assertEqual(analysis["schema"], "scene_dna_blind_review_analysis_v2")
        self.assertEqual(semantic["outcome_counts"]["neither"], 1)
        self.assertEqual(semantic["preference_rating_count"], 1)
        self.assertEqual(semantic["neither_excluded_from_preference_count"], 1)
        self.assertEqual(semantic["proposed_preference_rate_ties_half"], 1.0)

    def test_offline_blind_bundle_is_self_contained_and_stays_blind(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline_image = root / "old.png"
            proposed_image = root / "new.png"
            Image.new("RGB", (16, 16), "red").save(baseline_image)
            Image.new("RGB", (16, 16), "blue").save(proposed_image)
            comparisons = root / "comparisons.json"
            comparisons.write_text(
                json.dumps(
                    {
                        "comparisons": [
                            {
                                "case_id": "offline-case",
                                "category": "storage_box",
                                "shape_profile": "compact_orthogonal",
                                "object_requirement": "one storage box",
                                "style_requirement": "warm modern",
                                "baseline": {
                                    "asset_id": "old",
                                    "image_path": str(baseline_image),
                                },
                                "proposed": {
                                    "asset_id": "new",
                                    "image_path": str(proposed_image),
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            bundle = root / "bundle"
            prepare_blind_bundle(
                comparisons,
                bundle,
                sealed_key_path=root / "sealed.json",
                random_seed=5,
            )
            output = root / "offline.html"
            report = export_offline_bundle(bundle, output, label="2d")
            page = output.read_text(encoding="utf-8")
        self.assertEqual(report["trial_count"], 2)
        self.assertEqual(report["embedded_image_count"], 4)
        self.assertFalse(report["sealed_key_embedded"])
        self.assertIn("data:image/png;base64,", page)
        self.assertIn("responses.jsonl", page)
        self.assertIn("物体要求：", page)
        self.assertIn("一个完整的封闭式长方形布面收纳箱", page)
        self.assertIn("温暖现代风格", page)
        self.assertIn("拖鞋题按单只鞋本身评价，不要求生成一双", page)
        self.assertIn("图片异常，跳过本题", page)
        self.assertIn("trial_quality_status:'flagged'", page)
        self.assertIn("返回上一题重做", page)
        self.assertNotIn("fetch('trials.json')", page)
        self.assertNotIn("/api/response", page)
        self.assertNotIn('"baseline"', page)
        self.assertNotIn('"proposed"', page)

    def test_blind_analysis_excludes_quality_flagged_trial_from_preference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            key = root / "key.json"
            key.write_text(
                json.dumps(
                    {
                        "trials": [
                            {
                                "trial_id": "ok",
                                "independent_case_id": "ok",
                                "assets": {
                                    "left": {"method": "proposed"},
                                    "right": {"method": "baseline"},
                                },
                            },
                            {
                                "trial_id": "bad-image",
                                "independent_case_id": "bad-image",
                                "assets": {
                                    "left": {"method": "baseline"},
                                    "right": {"method": "proposed"},
                                },
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            responses = root / "responses.jsonl"
            responses.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "trial_id": "ok",
                                "reviewer_id": "r",
                                "trial_quality_status": "ok",
                                **{
                                    f"{axis}_choice": "left"
                                    for axis in ("semantic", "form", "style", "overall")
                                },
                            }
                        ),
                        json.dumps(
                            {
                                "trial_id": "bad-image",
                                "reviewer_id": "r",
                                "trial_quality_status": "flagged",
                                "quality_issue_side": "B",
                                "quality_issue_reason": "下半部分缺失",
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            report = analyze_responses(responses, key, root / "analysis.json")
        self.assertEqual(report["quality_flagged_response_count"], 1)
        self.assertEqual(report["axes"]["semantic"]["rating_count"], 1)
        self.assertEqual(report["primary_semantic_form_preference_rate"], 1.0)
