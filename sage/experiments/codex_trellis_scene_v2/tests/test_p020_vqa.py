from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image

from sage.experiments.codex_trellis_scene_v2.content_chain import content_hash
from sage.experiments.codex_trellis_scene_v2.p020_vqa import (
    QwenAtomicScorer,
    build_atomic_prompt,
    parse_atomic_response,
    parse_style_response,
    prepare_image,
    reconcile_style,
    validate_contract,
)


def requirement(identifier="category", expected=True, depends_on=None, hard=True):
    return {"id": identifier, "question": f"Question for {identifier}?", "expected": expected,
            "positive": "PRIVATE_POSITIVE", "negative": "PRIVATE_NEGATIVE", "hard": hard,
            "depends_on": depends_on or []}


def observation(identifier="category", answer=True, observability="visible", box=(0, 0, 1000, 1000)):
    return {"id": identifier, "answer": answer, "observability": observability,
            "evidence_bbox": list(box) if isinstance(box, tuple) else box,
            "evidence": "The entire relevant region is visible."}


def parsed(items, rows):
    return parse_atomic_response(json.dumps({"answers": rows}), {"requirements": items})


class AtomicParserTests(unittest.TestCase):
    def test_prompt_hides_expected_contrasts_and_other_metadata(self):
        item = requirement(expected="PRIVATE_EXPECTED")
        contract = {"requirements": [item], "description": "PRIVATE_PROMPT"}
        prompt = build_atomic_prompt(contract)
        for secret in ("PRIVATE_EXPECTED", "PRIVATE_POSITIVE", "PRIVATE_NEGATIVE", "PRIVATE_PROMPT"):
            self.assertNotIn(secret, prompt)
        self.assertIn(item["question"], prompt)

    def test_semantic_ids_are_opaque_on_wire_and_do_not_hint_expected_answer(self):
        item = requirement("NoFooExpectedFalse", False)
        item["question"] = "Is a handle visible?"
        prompt = build_atomic_prompt({"requirements": [item]})
        self.assertNotIn("NoFooExpectedFalse", prompt)
        self.assertIn('"id": "q000"', prompt)
        renamed = {**item, "id": "YesFooExpectedTrue", "expected": True}
        self.assertEqual(prompt, build_atomic_prompt({"requirements": [renamed]}))

    def test_batch_prompt_demonstrates_full_wrapper_and_requires_every_row(self):
        for count in (1, 19):
            with self.subTest(count=count):
                items = [requirement(f"hidden_semantic_id_{index}") for index in range(count)]
                for item in items:
                    item["question"] = "Is a handle visible?"
                prompt = build_atomic_prompt({"requirements": items})
                self.assertIn(f"BATCH SIZE: {count} questions", prompt)
                self.assertIn(f"exactly {count} rows", prompt)
                example = json.loads(prompt.split("BEGIN FORMAT EXAMPLE\n", 1)[1].split("\nEND FORMAT EXAMPLE", 1)[0])
                self.assertEqual(set(example), {"answers"})
                self.assertGreater(len(example["answers"]), 1)
                self.assertIn("at most 12 words", prompt)
                self.assertIn("Counts are unquoted numbers, never strings", prompt)
                self.assertIn("Include null answers when unknown", prompt)
                ending = prompt.split("Required IDs in order: ", 1)[1]
                for index in range(count):
                    self.assertIn(f"q{index:03d}", ending)
                    self.assertNotIn(f"hidden_semantic_id_{index}", prompt)

    def test_single_answer_v1_failure_is_not_repaired_or_filled_in(self):
        items = [requirement("q000", 1), requirement("q001")]
        raw = json.dumps(observation("q000", "1"))
        result = parse_atomic_response(raw, {"requirements": items})
        self.assertFalse(result["parse_ok"])
        self.assertEqual(result["counts"], {"pass": 0, "fail": 0, "unknown": 2})

    def test_negative_boolean_is_not_coerced_or_inverted(self):
        item = requirement(expected=False)
        for answer, verdict in ((False, "pass"), (True, "fail"), (0, "unknown"), ("false", "unknown")):
            with self.subTest(answer=answer):
                result = parsed([item], [observation(answer=answer)])
                self.assertEqual(result["requirements"][0]["verdict"], verdict)

    def test_count_requires_integer_complete_visibility_and_localization(self):
        item = requirement("count", 3)
        for answer, visibility, box, verdict in (
            (3, "visible", [0, 0, 1000, 1000], "pass"),
            (4, "visible", [0, 0, 1000, 1000], "fail"),
            (3, "partial", [0, 0, 1000, 1000], "unknown"),
            (4, "not_visible", [0, 0, 1000, 1000], "unknown"),
            (3, "visible", None, "unknown"),
            (3.0, "visible", [0, 0, 1000, 1000], "unknown"),
            (True, "visible", [0, 0, 1000, 1000], "unknown"),
            (-1, "visible", [0, 0, 1000, 1000], "unknown"),
            ("three", "visible", [0, 0, 1000, 1000], "unknown"),
        ):
            with self.subTest(answer=answer, visibility=visibility, box=box):
                result = parsed([item], [observation("count", answer, visibility, box)])
                self.assertEqual(result["requirements"][0]["verdict"], verdict)
        zero = parsed([requirement("count", 0)], [observation("count", 0, box=[0, 0, 1000, 1000])])
        self.assertEqual(zero["verdict"], "pass")

    def test_partial_absence_has_only_explicit_localized_positive_counterexamples(self):
        for quantifier in (None, "inferred", "exact_count", "absence"):
            for expected in (False, True):
                for answer in (False, True):
                    for visibility in ("partial", "not_visible", "uncertain"):
                        with self.subTest(quantifier=quantifier, expected=expected,
                                          answer=answer, visibility=visibility):
                            item = {**requirement(expected=expected), "quantifier": quantifier}
                            row = observation(answer=answer, observability=visibility)
                            result = parsed([item], [row])["requirements"][0]
                            is_counterexample = (quantifier == "absence" and expected is False
                                                 and answer is True and visibility == "partial")
                            self.assertEqual(result["verdict"], "fail" if is_counterexample else "unknown")
                            self.assertEqual(result["reason"], "visible_counterexample" if is_counterexample
                                             else "insufficient_observability")
                            self.assertIs(result["answer"], answer)
                            self.assertEqual(result["observability"], visibility)

    def test_partial_exact_count_can_only_fail_from_a_visible_excess_lower_bound(self):
        for quantifier in (None, "inferred", "absence", "exact_count"):
            for expected in (0, 3):
                for answer in (0, 2, 3, 4):
                    for visibility in ("partial", "not_visible", "uncertain"):
                        with self.subTest(quantifier=quantifier, expected=expected,
                                          answer=answer, visibility=visibility):
                            item = {**requirement("count", expected), "quantifier": quantifier}
                            result = parsed([item], [observation("count", answer, visibility)])["requirements"][0]
                            excess = quantifier == "exact_count" and answer > expected and visibility == "partial"
                            self.assertEqual(result["verdict"], "fail" if excess else "unknown")
                            self.assertEqual(result["reason"], "observed_count_lower_bound_exceeds_expected" if excess
                                             else "insufficient_observability")
                            self.assertEqual(result["answer"], answer)
                            self.assertEqual(result["observability"], visibility)

    def test_partial_counterexamples_still_require_valid_localization_evidence_and_types(self):
        for item, answer in (({**requirement(expected=False), "quantifier": "absence"}, True),
                             ({**requirement(expected=3), "quantifier": "exact_count"}, 4)):
            for hard in (False, True):
                item = {**item, "hard": hard}
                mutations = ({"evidence_bbox": None}, {"evidence_bbox": [0, 0, 0, 10]},
                             {"evidence_bbox": [0, 0, 1001, 1000]}, {"evidence": " "},
                             {"evidence": None}, {"answer": None}, {"answer": str(answer)},
                             {"answer": 1.5}, {"answer": -1})
                for mutation in mutations:
                    with self.subTest(quantifier=item["quantifier"], hard=hard, mutation=mutation):
                        row = {**observation(answer=answer, observability="partial"), **mutation}
                        self.assertEqual(parsed([item], [row])["requirements"][0]["verdict"], "unknown")
            if item["quantifier"] == "exact_count":
                boolean_count = observation(answer=True, observability="partial")
                self.assertEqual(parsed([item], [boolean_count])["requirements"][0]["verdict"], "unknown")

    def test_partial_counterexamples_remain_blocked_by_nonpassing_parent(self):
        for quantifier, expected, answer, reason in (
            ("absence", False, True, "visible_counterexample"),
            ("exact_count", 3, 4, "observed_count_lower_bound_exceeds_expected"),
        ):
            for parent_answer in (False, None):
                with self.subTest(quantifier=quantifier, parent_answer=parent_answer):
                    item = {**requirement("child", expected, ["category"]), "quantifier": quantifier}
                    result = parsed([item, requirement()], [observation("child", answer, "partial"),
                                                           observation(answer=parent_answer)])
                    child = result["requirements"][0]
                    self.assertEqual(child["verdict"], "unknown")
                    self.assertEqual(child["reason"], "blocked_unknown")
                    self.assertEqual(child["blocked_by"], ["category"])
                    self.assertEqual(child["unblocked_verdict"], "fail")
                    self.assertEqual(child["unblocked_reason"], reason)
                    self.assertEqual(child["answer"], answer)
                    self.assertEqual(child["observability"], "partial")

    def test_quantifier_changes_parser_metadata_only_and_never_model_prompt(self):
        item = requirement("no_forbidden_parts", False)
        original_prompt = build_atomic_prompt({"requirements": [item]})
        tagged = {**item, "quantifier": "absence"}
        self.assertEqual(original_prompt, build_atomic_prompt({"requirements": [tagged]}))
        for answer, verdict in ((False, "pass"), (True, "fail")):
            result = parsed([tagged], [observation("no_forbidden_parts", answer)])
            self.assertEqual(result["requirements"][0]["verdict"], verdict)
            self.assertEqual(result["requirements"][0]["quantifier"], "absence")

    def test_invalid_boxes_and_empty_evidence_never_pass(self):
        for box in ([0, 0, 1001, 1000], [0, 0, 0, 1], [2, 3, 1, 4], [True, 0, 10, 10],
                    [0, 0, "100", 100], [1, 2], {"x": 1}):
            with self.subTest(box=box):
                result = parsed([requirement()], [observation(box=box)])
                self.assertEqual(result["verdict"], "unknown")
                self.assertFalse(result["parse_ok"])
        row = observation()
        row["evidence"] = " "
        self.assertEqual(parsed([requirement()], [row])["verdict"], "unknown")

    def test_all_hard_atoms_require_localization_even_boolean_absence(self):
        for expected in (True, False, "oak"):
            with self.subTest(expected=expected):
                result = parsed([requirement(expected=expected)], [observation(answer=expected, box=None)])
                self.assertEqual(result["verdict"], "unknown")
                self.assertEqual(result["requirements"][0]["reason"], "hard_requirement_requires_localized_evidence")
        soft = parsed([requirement(hard=False)], [observation(box=None)])
        self.assertEqual(soft["requirements"][0]["verdict"], "pass")

    def test_missing_duplicate_extra_and_invalid_rows_are_unknown(self):
        cases = ([], [observation(), observation()], [observation("extra")], [None],
                 [{"id": "category", "answer": True}])
        for rows in cases:
            with self.subTest(rows=rows):
                result = parsed([requirement()], rows)
                self.assertEqual(result["verdict"], "unknown")
                self.assertFalse(result["parse_ok"])

    def test_no_prose_extraction_truncation_duplicate_keys_or_nonfinite_json(self):
        contract = {"requirements": [requirement()]}
        valid = json.dumps({"answers": [observation()]})
        for raw in ("Here is the answer: " + valid, valid[:-2], valid + valid,
                    '{"answers":[],"answers":[]}',
                    '{"answers":[{"id":"category","answer":NaN}]}'):
            with self.subTest(raw=raw):
                result = parse_atomic_response(raw, contract)
                self.assertEqual(result["verdict"], "unknown")
                self.assertFalse(result["parse_ok"])
        self.assertEqual(parse_atomic_response("```json\n" + valid + "\n```", contract)["verdict"], "pass")

    def test_unknown_partial_and_wrong_answer_type_preserve_unknown(self):
        for answer, visibility in ((None, "visible"), (True, "uncertain"), (True, "partial"),
                                   ({"value": True}, "visible"), (True, "probably")):
            with self.subTest(answer=answer, visibility=visibility):
                self.assertEqual(parsed([requirement()], [observation(answer=answer, observability=visibility)])["verdict"], "unknown")
        self.assertEqual(parsed([requirement(expected="oak")], [observation(answer="unknown")])["verdict"], "unknown")
        self.assertEqual(parsed([requirement(expected="oak")], [observation(answer=" OAK ")])["verdict"], "pass")
        self.assertEqual(parsed([requirement(expected="oak")], [observation(answer="pine")])["verdict"], "fail")

    def test_dependency_is_order_independent_and_retains_blocked_observation(self):
        items = [requirement("material", "oak", ["lid"]), requirement("lid", True, ["category"]), requirement()]
        rows = [observation("material", "pine"), observation("lid", True), observation(answer=False)]
        result = parsed(items, rows)
        self.assertEqual(result["verdict"], "fail")
        self.assertEqual(result["counts"], {"pass": 0, "fail": 1, "unknown": 2})
        material = result["requirements"][0]
        self.assertEqual(material["reason"], "blocked_unknown")
        self.assertEqual(material["answer"], "pine")
        self.assertEqual(material["unblocked_verdict"], "fail")
        rows[-1]["answer"] = None
        self.assertEqual(parsed(items, rows)["verdict"], "unknown")

    def test_soft_failure_does_not_become_hard_failure_and_empty_hard_set_cannot_pass(self):
        result = parsed([requirement(), requirement("style", hard=False)], [observation(), observation("style", False)])
        self.assertEqual(result["verdict"], "pass")
        self.assertEqual(parsed([requirement(hard=False)], [observation()])["verdict"], "unknown")

    def test_contract_cycles_missing_parents_and_invalid_expectations_rejected(self):
        bad_contracts = ({}, {"requirements": []}, {"requirements": [requirement(), requirement()]},
                         {"requirements": [requirement(expected=1.5)]},
                         {"requirements": [requirement(depends_on=["missing"])]},
                         {"requirements": [requirement(depends_on=["category"])]},
                         {"requirements": [requirement("a", depends_on=["b"]), requirement("b", depends_on=["a"])]})
        for contract in bad_contracts:
            with self.subTest(contract=contract), self.assertRaises(ValueError):
                validate_contract(contract)


class StyleParserTests(unittest.TestCase):
    def test_swap_maps_back_to_original_candidate_and_detects_position_bias(self):
        def vote(winner):
            return parse_style_response(json.dumps({"winner": winner, "evidence": "Visible material."}))
        self.assertEqual(reconcile_style(vote("left"), vote("right"))["winner"], "left")
        self.assertEqual(reconcile_style(vote("right"), vote("left"))["winner"], "right")
        biased = reconcile_style(vote("left"), vote("left"))
        self.assertEqual(biased["winner"], "unknown")
        self.assertTrue(biased["order_disagreement"])
        self.assertEqual(reconcile_style(vote("tie"), vote("tie"))["winner"], "tie")
        self.assertEqual(reconcile_style(vote("tie"), vote("left"))["winner"], "unknown")
        self.assertEqual(reconcile_style(vote("unknown"), vote("unknown"))["winner"], "unknown")

    def test_malformed_style_cannot_be_rescued_by_other_order(self):
        invalid = parse_style_response('{"winner":"left","evidence":"ok","probability":0.99}')
        valid = parse_style_response('{"winner":"right","evidence":"material"}')
        self.assertFalse(invalid["parse_ok"])
        self.assertEqual(reconcile_style(invalid, valid)["winner"], "unknown")


class ScorerBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.left, self.right = self.root / "left.png", self.root / "right.png"
        rgba = Image.new("RGBA", (32, 32), (255, 0, 0, 0))
        rgba.putpixel((15, 15), (0, 0, 255, 255))
        rgba.save(self.left)
        Image.new("RGB", (32, 32), "green").save(self.right)

    def tearDown(self):
        self.temp.cleanup()

    def test_prepare_image_binds_source_and_white_display_without_writes(self):
        original = self.left.read_bytes()
        image, binding = prepare_image(self.left)
        self.assertEqual(image.getpixel((0, 0)), (255, 255, 255))
        self.assertEqual(image.getpixel((15, 15)), (0, 0, 255))
        self.assertEqual(binding["display_size"], [32, 32])
        image.close()
        self.assertEqual(self.left.read_bytes(), original)
        with Image.open(self.left) as source:
            source.putpixel((1, 1), (0, 255, 0, 255))
            source.save(self.left)
        changed, second = prepare_image(self.left)
        changed.close()
        self.assertNotEqual(binding["sha256"], second["sha256"])
        self.assertNotEqual(binding["display_pixel_sha256"], second["display_pixel_sha256"])

    def test_import_constructor_and_close_do_not_import_torch(self):
        code = ("import sys; from sage.experiments.codex_trellis_scene_v2.p020_vqa import QwenAtomicScorer; "
                "s=QwenAtomicScorer('/missing'); s.close(); assert 'torch' not in sys.modules")
        subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True)

    def test_exif_orientation_is_applied_before_recording_display_coordinates(self):
        source = Image.new("RGB", (16, 32), "white")
        source.putpixel((0, 0), (255, 0, 0))
        exif = Image.Exif()
        exif[274] = 6
        source.save(self.left, exif=exif)
        original = self.left.read_bytes()
        image, binding = prepare_image(self.left)
        self.assertEqual(binding["original_size"], [16, 32])
        self.assertEqual(binding["original_exif_orientation"], 6)
        self.assertEqual(binding["display_size"], [32, 16])
        self.assertEqual(image.getpixel((31, 0)), (255, 0, 0))
        image.close()
        self.assertEqual(self.left.read_bytes(), original)

    def test_score_one_call_records_raw_prompt_hash_and_contract_not_in_prompt(self):
        scorer = QwenAtomicScorer(self.root / "missing", device="cpu")
        contract = {"requirements": [requirement()]}
        raw = json.dumps({"answers": [observation("q000")]})
        with patch.object(scorer, "_generate", return_value={"raw_response": raw}) as generate:
            result = scorer.score(self.left, contract)
        self.assertEqual(generate.call_count, 1)
        self.assertEqual(result["method"], "B")
        self.assertEqual(result["verdict"], "pass")
        self.assertEqual(result["wire_id_map"], {"q000": "category"})
        self.assertEqual(result["requirements"][0]["id"], "category")
        self.assertEqual(result["inference"]["raw_response"], raw)
        self.assertEqual(result["contract_hash"], content_hash(contract))
        self.assertNotIn("PRIVATE_POSITIVE", result["inference"]["prompt"])
        self.assertEqual(result["settings"]["crop_count"], 0)
        self.assertEqual(result["model_binding"]["load_status"], "not_loaded")
        self.assertEqual(result["result_hash"], content_hash({k: v for k, v in result.items() if k != "result_hash"}))

    def test_score_maps_wire_dependencies_and_failures_back_to_real_ids(self):
        scorer = QwenAtomicScorer(self.root / "missing", device="cpu")
        contract = {"requirements": [requirement("no_legs", False), requirement("oak_body", "oak", ["no_legs"])]}
        raw = json.dumps({"answers": [observation("q000", True), observation("q001", "oak")]})
        with patch.object(scorer, "_generate", return_value={"raw_response": raw}):
            result = scorer.score(self.left, contract)
        self.assertEqual(result["requirements"][0]["id"], "no_legs")
        self.assertEqual(result["requirements"][0]["verdict"], "fail")
        self.assertEqual(result["requirements"][1]["blocked_by"], ["no_legs"])
        self.assertEqual(result["requirements"][1]["reason"], "blocked_unknown")
        self.assertEqual(result["contract_hash"], content_hash(contract))

    def test_score_retains_quantifier_on_wire_and_preserves_partial_raw_observation(self):
        scorer = QwenAtomicScorer(self.root / "missing", device="cpu")
        item = {**requirement("forbidden_handle", False), "quantifier": "absence"}
        contract = {"requirements": [item]}
        raw = json.dumps({"answers": [observation("q000", True, "partial")]})
        with patch.object(scorer, "_generate", return_value={"raw_response": raw}) as generate:
            result = scorer.score(self.left, contract)
        self.assertEqual(generate.call_count, 1)
        self.assertEqual(result["verdict"], "fail")
        self.assertEqual(result["requirements"][0]["id"], "forbidden_handle")
        self.assertEqual(result["requirements"][0]["reason"], "visible_counterexample")
        self.assertEqual(result["requirements"][0]["observability"], "partial")
        self.assertIs(result["requirements"][0]["answer"], True)
        self.assertEqual(result["inference"]["raw_response"], raw)
        self.assertEqual(result["contract_hash"], content_hash(contract))
        untagged = {"requirements": [requirement("forbidden_handle", False)]}
        self.assertEqual(result["inference"]["prompt"], build_atomic_prompt(untagged))

    def test_inference_failure_is_unknown_without_retry_or_probability(self):
        scorer = QwenAtomicScorer(self.root / "missing", device="cpu")
        with patch.object(scorer, "_generate", side_effect=RuntimeError("simulated OOM")) as generate:
            result = scorer.score(self.left, {"requirements": [requirement()]})
        self.assertEqual(generate.call_count, 1)
        self.assertEqual(result["verdict"], "unknown")
        self.assertEqual(result["inference"]["error"]["type"], "RuntimeError")
        self.assertNotIn("probability", json.dumps(result))

    def test_compare_has_exact_two_calls_swapped_rasters_and_records_each_order(self):
        scorer = QwenAtomicScorer(self.root / "missing", device="cpu")
        seen = []

        def generate(images, prompt):
            seen.append([image.getpixel((15, 15)) for image in images])
            winner = "left" if len(seen) == 1 else "right"
            return {"raw_response": json.dumps({"winner": winner, "evidence": "Blue material."})}

        with patch.object(scorer, "_generate", side_effect=generate):
            result = scorer.compare(self.left, self.right, "cool blue room")
        self.assertEqual(len(seen), 2)
        self.assertEqual(seen[0], list(reversed(seen[1])))
        self.assertEqual(result["winner"], "left")
        self.assertEqual(result["call_count"], 2)
        self.assertEqual(result["forward"]["image_order"], list(reversed(result["reverse"]["image_order"])))

    def test_incomplete_snapshot_rejected_before_loading_framework(self):
        (self.root / "config.json").write_text("{}")
        (self.root / "model.safetensors.partial").write_bytes(b"partial")
        scorer = QwenAtomicScorer(self.root, device="cpu")
        with self.assertRaisesRegex(RuntimeError, "incomplete downloads"):
            scorer._load()


if __name__ == "__main__":
    unittest.main()
