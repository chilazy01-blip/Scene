from __future__ import annotations

import hashlib
import json
import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

from ..p020_requirement_scoring import (
    RUNNER_SCHEMA, AtomicSiglipScorer, RunnerEvidence, consensus,
    legacy_visual_candidate_score, load_runner_evidence, select_candidate,
    standardized_white_image, validate_contract,
)


def requirement(key="identity", *, expected=True, depends_on=None):
    return {"id": key, "question": f"Is {key} present?", "expected": expected, "positive": f"object with {key}", "negative": f"object without {key}", "hard": True, "depends_on": depends_on or []}


def branch(verdict="pass", key="identity", contrast=0.9):
    return {"requirements": [{"id": key, "verdict": verdict, "contrast_score": contrast}]}


def evidence(source=True, alpha=True):
    return RunnerEvidence("0" * 64, source, alpha, {"runner": "synthetic_cpu_test"})


class RequirementScoringTests(unittest.TestCase):
    def image(self, root: Path):
        pixels = np.full((8, 8, 4), [170, 95, 60, 255], dtype=np.uint8)
        pixels[3, 3] = [255, 0, 255, 0]  # A full-frame alpha hole is not semantic proof.
        path = root / "source.png"
        Image.fromarray(pixels, "RGBA").save(path)
        return path

    def test_atomic_one_batch_false_expected_polarity_and_immutable_white_image(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self.image(root)
            before = path.read_bytes()
            requirements = [requirement(), requirement("platform", expected=False), requirement("leg_count", expected=4), requirement("material", expected="oak")]
            scorer = Mock()
            scorer._logits.return_value = [4, 0, 0, 4, 4, 0, 4, 0]
            report = AtomicSiglipScorer(scorer=scorer).score(path, {"requirements": requirements}, output_dir=root / "normalized")
            scorer._logits.assert_called_once()
            image, prompts = scorer._logits.call_args.args
            self.assertEqual(prompts, [row[key] for row in requirements for key in ("positive", "negative")])
            self.assertEqual(image.getpixel((3, 3)), (255, 255, 255))
            self.assertEqual(image.size, (8, 8))
            self.assertEqual(path.read_bytes(), before)
            self.assertTrue(all(row["verdict"] == "pass" for row in report["requirements"]))
            platform = report["requirements"][1]
            self.assertEqual(platform["raw_margin"], -4)
            self.assertEqual(platform["margin"], 4)
            self.assertFalse(platform["contrast_score_calibrated"])
            self.assertEqual(report["verdict"], "unknown")  # No source/alpha runner evidence.
            self.assertFalse(report["asset_accepted"])
            self.assertEqual(report["source_rules"][1]["verdict"], "unknown")

    def test_fixed_thresholds_and_missing_logits_are_unknown(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self.image(root)
            for logits, expected in [([math.log(4), 0], "pass"), ([-math.log(4), 0], "fail"), ([0, 0], "unknown"), ([None, None], "unknown"), ([float("nan"), 0], "unknown"), ([], "unknown"), (None, "unknown")]:
                with self.subTest(logits=logits):
                    scorer = Mock()
                    scorer._logits.return_value = logits
                    report = AtomicSiglipScorer(scorer=scorer).score(path, {"requirements": [requirement()]}, output_dir=root / "normalized")
                    self.assertEqual(report["requirements"][0]["verdict"], expected)
                    self.assertEqual(report["verdict_kind"], "uncalibrated_prediction")

    def test_exif_orientation_is_applied_only_to_local_display_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "oriented.png"
            exif = Image.Exif()
            exif[274] = 6
            Image.new("RGBA", (3, 5), (100, 80, 60, 128)).save(path, exif=exif)
            before = path.read_bytes()
            image, binding = standardized_white_image(path, root / "normalized")
            self.assertEqual(image.size, (5, 3))
            self.assertEqual(binding["original_size"], [3, 5])
            self.assertEqual(binding["source_exif_orientation"], 6)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(binding["display_pixel_sha256"], hashlib.sha256(image.tobytes()).hexdigest())

    def test_trusted_runner_source_fail_cannot_be_overridden_by_atomic_pass(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self.image(root)
            runner = RunnerEvidence(hashlib.sha256(path.read_bytes()).hexdigest(), False, True, {"runner": "cpu_test"})
            scorer = Mock()
            scorer._logits.return_value = [20, 0]
            report = AtomicSiglipScorer(scorer=scorer).score(path, {"requirements": [requirement()]}, output_dir=root / "normalized", runner_evidence=runner)
            self.assertEqual(report["requirements"][0]["verdict"], "pass")
            self.assertEqual(report["source_rules"][0]["verdict"], "fail")
            self.assertEqual(report["verdict"], "fail")
            self.assertFalse(report["accepted"])

    def test_runner_manifest_needs_independent_hash_and_matching_source_image(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = self.image(root)
            path = root / "runner.json"
            raw = json.dumps({"schema": RUNNER_SCHEMA, "image_sha256": hashlib.sha256(image.read_bytes()).hexdigest(), "rules": {"source": False, "alpha": None}}).encode()
            path.write_bytes(raw)
            loaded = load_runner_evidence(path, expected_sha256=hashlib.sha256(raw).hexdigest(), image_path=image)
            self.assertIs(loaded.source, False)
            self.assertIsNone(loaded.alpha)
            with self.assertRaises(ValueError):
                load_runner_evidence(path, expected_sha256="0" * 64, image_path=image)
            Image.new("RGB", (9, 9)).save(image)
            with self.assertRaises(ValueError):
                load_runner_evidence(path, expected_sha256=hashlib.sha256(raw).hexdigest(), image_path=image)
        with self.assertRaises(TypeError):
            consensus({"requirements": [requirement()]}, branch(), branch(), runner_evidence={"trusted": True, "source": True})

    def test_consensus_fixed_matrix_preserves_conflicts_and_failure_evidence(self):
        matrix = {("pass", "pass"): "pass", ("pass", "fail"): "unknown", ("fail", "pass"): "unknown", ("fail", "fail"): "fail", ("fail", "unknown"): "fail", ("unknown", "fail"): "fail", ("pass", "unknown"): "unknown", ("unknown", "pass"): "unknown", ("unknown", "unknown"): "unknown"}
        for pair, expected in matrix.items():
            with self.subTest(pair=pair):
                report = consensus({"requirements": [requirement()]}, branch(pair[0]), branch(pair[1]), runner_evidence=evidence())
                row = report["requirements"][0]
                self.assertEqual(row["verdict"], expected)
                self.assertEqual(row["observed_failures"], [label for label, verdict in zip(("A", "B"), pair) if verdict == "fail"])
                if set(pair) == {"pass", "fail"}:
                    self.assertTrue(row["conflict"])
                    self.assertIsNotNone(row["conflict_reason"])

    def test_blocked_dependencies_remain_unknown_without_duplicate_failure(self):
        contract = {"requirements": [requirement("child", depends_on=["parent"]), requirement("parent")]}
        a = {"requirements": [{"id": "child", "verdict": "fail"}, {"id": "parent", "verdict": "fail"}]}
        b = {"requirements": [{"id": "child", "verdict": "fail"}, {"id": "parent", "verdict": "unknown"}]}
        report = consensus(contract, a, b, runner_evidence=evidence())
        child, parent = report["requirements"]
        self.assertEqual(child["verdict"], "unknown")
        self.assertEqual(child["raw_verdict"], "fail")
        self.assertEqual(child["blocked_by"], ["parent"])
        self.assertEqual(parent["verdict"], "fail")
        selection = select_candidate([{"candidate_id": "candidate", "reports": {"C": report}, "runner_evidence": evidence(), "legacy_style": 0.5}], "C", contract=contract)
        self.assertEqual(selection["candidates"][0]["predicted_fail_count"], 1)
        self.assertEqual(selection["candidates"][0]["unknown_count"], 1)
        self.assertEqual(selection["candidates"][0]["coverage"]["blocked_hard_requirement_count"], 1)
        self.assertEqual(selection["candidates"][0]["selection_requirements"][0]["raw_verdict"], "fail")
        missing = consensus({"requirements": [requirement()]}, branch("pass"), None)
        self.assertEqual(missing["requirements"][0]["verdict"], "unknown")

    def test_contract_rejects_cycles_missing_dependency_and_wrong_expected_type(self):
        for rows in [[requirement("a", depends_on=["b"]), requirement("b", depends_on=["a"])], [requirement("a", depends_on=["missing"])], [requirement(expected=1.0)], [requirement(), requirement()]]:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                validate_contract({"requirements": rows})

    def test_source_and_alpha_failures_survive_selection_and_failure_denominator(self):
        rows = [{"candidate_id": "source-fail", "reports": {"A": branch()}, "runner_evidence": evidence(False, True), "legacy_style": 999}, {"candidate_id": "alpha-fail", "reports": {"A": branch()}, "runner_evidence": evidence(True, False), "legacy_style": 999}, {"candidate_id": "eligible", "reports": {"A": branch("unknown", contrast=0.4)}, "runner_evidence": evidence(), "legacy_style": 0.01}]
        selected = select_candidate(rows, "A")
        self.assertEqual(selected["selected"], "eligible")
        self.assertEqual(selected["failure_denominator"], 3)
        self.assertEqual(selected["source_hard_fail_count"], 2)
        self.assertEqual(len(selected["candidates"]), 3)
        self.assertEqual(selected["status"], "provisional_for_3d")
        self.assertFalse(selected["asset_accepted"])
        rejected = select_candidate(rows[:2], "A")
        self.assertIsNone(rejected["selected"])
        self.assertEqual(rejected["status"], "reject_batch")
        self.assertEqual(rejected["failure_denominator"], 2)

    def test_conflicting_semantics_do_not_override_deterministic_source_failure(self):
        report = consensus({"requirements": [requirement()]}, branch("pass"), branch("fail"), runner_evidence=evidence(False))
        self.assertEqual(report["requirements"][0]["verdict"], "unknown")
        self.assertEqual(report["verdict"], "fail")
        selected = select_candidate([{"candidate_id": "conflict", "reports": {"C": report}, "runner_evidence": evidence(False), "legacy_style": 1}], "C")
        self.assertIsNone(selected["selected"])

    def test_previous_runner_veto_is_sticky_through_consensus_and_selection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self.image(root)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            failed = RunnerEvidence(digest, False, True, {"runner": "original_source_failure"})
            replacement = RunnerEvidence(digest, True, True, {"runner": "later_soft_acceptance"})
            fake = Mock()
            fake._logits.return_value = [5, 0]
            a = AtomicSiglipScorer(scorer=fake).score(path, {"requirements": [requirement()]}, output_dir=root / "normalized", runner_evidence=failed)
            c = consensus({"requirements": [requirement()]}, a, branch(), runner_evidence=replacement)
            self.assertEqual(c["source_rules"][0]["verdict"], "fail")
            self.assertEqual(c["retained_runner_evidence"][0]["source"], False)
            selection = select_candidate([{"candidate_id": "sticky", "reports": {"C": c}, "runner_evidence": replacement, "legacy_style": 1}], "C")
            self.assertIsNone(selection["selected"])
            with self.assertRaises(ValueError):
                select_candidate([{"candidate_id": "wrong-image", "reports": {"C": c}, "runner_evidence": evidence(), "legacy_style": 1}], "C")

    def test_duplicate_ids_and_changed_expected_values_cannot_silently_pass(self):
        contract = {"requirements": [requirement(expected=False)]}
        a = {"requirements": [{"id": "identity", "verdict": "pass", "expected": False}]}
        for b in [{"requirements": [{"id": "identity", "verdict": "pass", "expected": True}]}, {"requirements": [{"id": "identity", "verdict": "pass"}, {"id": "identity", "verdict": "fail"}]}]:
            with self.subTest(b=b):
                c = consensus(contract, a, b)
                self.assertEqual(c["requirements"][0]["verdict"], "unknown")

    def test_soft_requirements_do_not_add_hard_fail_or_unknown_penalties(self):
        soft = {**requirement("style"), "hard": False}
        contract = {"requirements": [requirement(), soft]}
        a = {"requirements": [{**requirement(), "verdict": "pass", "contrast_score": 0.95}, {**soft, "verdict": "fail", "contrast_score": 0.05}]}
        c = consensus(contract, a, a, runner_evidence=evidence())
        self.assertEqual(c["requirements"][1]["verdict"], "fail")
        self.assertEqual(c["verdict"], "pass")
        selected = select_candidate([{"candidate_id": "soft-fail", "reports": {"A": a, "C": c}, "runner_evidence": evidence(), "legacy_style": 0.5}], "C", contract=contract)
        row = selected["candidates"][0]
        self.assertEqual(row["predicted_fail_count"], 0)
        self.assertEqual(row["unknown_count"], 0)

    def test_consensus_rejects_cross_image_and_contract_bindings(self):
        contract = {"requirements": [requirement()]}
        a = {**branch(), "image_binding": {"source_sha256": "0" * 64}}
        b = {**branch(), "image": {"sha256": "1" * 64}}
        with self.assertRaises(ValueError):
            consensus(contract, a, b)
        with self.assertRaises(ValueError):
            consensus(contract, branch(), b, runner_evidence=evidence())
        with self.assertRaises(ValueError):
            consensus(contract, {**branch(), "contract_hash": "invalid"}, branch())

    def test_B_ranking_is_independent_of_A_scores_and_accepts_explicit_style_pair_rank(self):
        rows = [{"candidate_id": "a", "reports": {"A": branch(contrast=0.01), "B": branch()}, "runner_evidence": evidence(), "legacy_style": 0.9}, {"candidate_id": "b", "reports": {"A": branch(contrast=0.99), "B": branch()}, "runner_evidence": evidence(), "legacy_style": 0.2}]
        selected = select_candidate(rows, "B")
        self.assertEqual(selected["selected"], "a")
        self.assertIsNone(selected["candidates"][0]["exact_rank_inputs"]["weakest_atomic_contrast_score"])
        for row, rank in zip(rows, (1, 0)):
            row["style_pair_rank"] = {"schema": "scene-v2-p020-runner-style-rank/v1", "rank": rank, "comparison_id": "pair", "order_swap_checked": True, "candidate_ids": ["a", "b"]}
        self.assertEqual(select_candidate(rows, "B")["selected"], "b")
        rows[0]["style_pair_rank"]["order_swap_checked"] = False
        with self.assertRaises(ValueError):
            select_candidate(rows, "B")

    def test_formal_selection_contract_counts_all_missing_ids_and_blocks_dependent_missing(self):
        contract = {"requirements": [requirement("parent"), requirement("child", depends_on=["parent"]), requirement("other"), {**requirement("soft"), "hard": False}]}
        selected = select_candidate([{"candidate_id": "missing-all", "reports": {}, "runner_evidence": evidence(), "legacy_style": 0.5}], "B", contract=contract)
        row = selected["candidates"][0]
        self.assertEqual(len(row["selection_requirements"]), 4)
        self.assertEqual(row["unknown_count"], 3)
        self.assertTrue(selected["canonical_contract_provided"])

    def test_unknown_root_cannot_gain_rank_by_hiding_all_dependent_evidence(self):
        requirements = [requirement("visible_root"), *[requirement(key, depends_on=["visible_root"]) for key in ("detail_a", "detail_b", "detail_c")]]
        contract = {"requirements": requirements}
        def report(verdicts, contrasts):
            return {"requirements": [{**req, "verdict": verdict, "contrast_score": contrast} for req, verdict, contrast in zip(requirements, verdicts, contrasts)]}
        mostly_verified = report(["pass", "pass", "pass", "unknown"], [0.9, 0.9, 0.85, 0.4])
        unknown_root = report(["unknown", "fail", "pass", "pass"], [0.7, 0.1, 0.95, 0.95])
        rows = [{"candidate_id": "mostly_verified", "reports": {"A": mostly_verified}, "runner_evidence": evidence(), "legacy_style": 0.5}, {"candidate_id": "unknown_root", "reports": {"A": unknown_root}, "runner_evidence": evidence(), "legacy_style": 0.5}]
        result = select_candidate(rows, "A", contract=contract)
        self.assertEqual(result["selected"], "mostly_verified")
        first, second = result["candidates"]
        self.assertEqual(first["unknown_count"], 1)
        self.assertEqual(second["unknown_count"], 4)
        self.assertEqual(second["predicted_fail_count"], 0)  # Child counterexample is blocked.
        self.assertEqual(second["coverage"]["observed_hard_fraction"], 0)
        self.assertEqual(second["coverage"]["blocked_hard_requirement_count"], 3)
        self.assertEqual(second["weakest_atomic_contrast_score"], 0.1)
        self.assertIn("including_blocked", second["atomic_soft_aggregation"])

    def test_rank_is_fail_unknown_weakest_atomic_legacy_then_stable_id(self):
        def row(key, verdict, contrast, style=0.5):
            return {"candidate_id": key, "reports": {"A": branch(verdict, contrast=contrast)}, "runner_evidence": evidence(), "legacy_style": style}
        rows = [row("b", "pass", 0.9), row("a", "pass", 0.9), row("higher-style", "pass", 0.9, 0.6), row("lower-soft", "pass", 0.85, 1), row("unknown", "unknown", 1, 100), row("fail", "fail", 1, 100)]
        first = select_candidate(rows, "A")
        second = select_candidate(list(reversed(rows)), "A")
        expected = ["higher-style", "a", "b", "lower-soft", "unknown", "fail"]
        self.assertEqual(first["ranked_eligible_ids"], expected)
        self.assertEqual(second["ranked_eligible_ids"], expected)
        self.assertEqual(first["selected"], "higher-style")

    def test_missing_method_report_is_not_ranked_as_zero_unknown(self):
        rows = [{"candidate_id": "missing-B", "reports": {"A": branch()}, "runner_evidence": evidence(), "legacy_style": 1}, {"candidate_id": "complete-B", "reports": {"A": branch(), "B": branch()}, "runner_evidence": evidence(), "legacy_style": 0.1}]
        selection = select_candidate(rows, "B")
        self.assertEqual(selection["selected"], "complete-B")
        self.assertEqual(selection["candidates"][0]["unknown_count"], 1)

    def test_baseline_executes_original_function_and_keeps_original_weights(self):
        from sage.server.trellis2_flux_bridge_server import Trellis2BridgeRuntime
        with tempfile.TemporaryDirectory() as temporary:
            image = self.image(Path(temporary))
            alpha = {"alpha_quality": {"score": 0.73}}
            scene = {"global_tags": ["oak", "warm"], "individuality_tags": ["brass"]}
            with patch.object(Trellis2BridgeRuntime, "_pipeline_instance", side_effect=AssertionError("must not load a model")):
                actual = legacy_visual_candidate_score(image, alpha, scene)
                expected = Trellis2BridgeRuntime(SimpleNamespace(alpha_bbox_threshold=24))._scene_dna_visual_candidate_score(image, alpha, scene)
            self.assertEqual(actual, expected)
            self.assertEqual(actual["weights"], {"alpha_structure": 0.55, "palette": 0.25, "temperature": 0.10, "detail": 0.10})
            self.assertFalse(actual["semantic_embedding_evaluated"])
        selected = select_candidate([{"candidate_id": "legacy-high", "reports": {"A": branch("fail")}, "runner_evidence": evidence(), "legacy_style": 0.9}, {"candidate_id": "semantic-high", "reports": {"A": branch("pass")}, "runner_evidence": evidence(), "legacy_style": 0.3}], "baseline")
        self.assertEqual(selected["selected"], "legacy-high")


if __name__ == "__main__":
    unittest.main()
