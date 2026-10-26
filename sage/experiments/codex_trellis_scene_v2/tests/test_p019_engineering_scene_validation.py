"""CPU scope/admission tests; fixtures are not visual acceptance evidence."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from .. import p019_engineering_scene_validation as engineering
from .. import p019_scene_validation as strict
from ..content_chain import content_hash
from ..white_background_real_batch import _object
from .test_p019_scene_validation import tetrahedron_glb


class EngineeringSceneValidationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.output = self.root / "engineering_scene_validation"
        self.sources = {}
        for provider, replicate in (("builtin_imagegen", 2), ("builtin_imagegen", 1), ("flux1-schnell", 1), ("flux1-schnell", 2)):
            identifier = f"sofa__{provider}__r{replicate}"
            case = {"id": identifier, "category": "sofa", "provider": provider, "replicate": replicate, "dimensions": strict.DIMENSIONS["sofa"], "prompt": "test only"}
            directory = self.root / "fixture_sources" / identifier
            directory.mkdir(parents=True)
            asset_path = directory / "mathematical_fixture.glb"
            tetrahedron_glb(asset_path)
            object_path = directory / "asset_object.json"
            engineering.write_json(object_path, _object(case))
            view_names = [f"standard_views:{axis}" for axis in strict.VIEW_AXES] + [f"low_under_views:{axis}" for axis in strict.LOW_UNDER_AXES] + [f"supplement_1400px:{axis}" for axis in strict.VIEW_AXES]
            views = {}
            for index, name in enumerate(view_names):
                path = directory / f"view_{index}.png"
                path.write_bytes(f"unit test image fixture {index}".encode())
                views[name] = engineering.bound(path)
            facts = {identifier: {"status": "pass", "observation": "unit test prior observation", "evidence_views": [view_names[0]]} for identifier, _, _, _ in engineering.REQUIREMENTS}
            self.sources[identifier] = {**engineering.SCOPE_FIELDS, "case": case, "asset": engineering.bound(asset_path), "generation_key": identifier, "generation": {"job_id": identifier}, "source_policy": {"ok": True}, "prior_requirement_facts": facts,
                                        "prior_geometry_facts": [], "original_quality_findings": [{"requirement": "dark wooden leg appearance", "status": "unknown"}, {"requirement": "absence of image-resolved surface blemishes", "status": "fail"}], "original_uncertainties": {}, "views": views, "evidence": {"asset_object": engineering.bound(object_path)}}
        original_plan = {"test_only": True}
        frozen = {"cases": [row["case"] for row in self.sources.values()], "preregistration_hash": content_hash(original_plan)}
        frozen["content_key"] = content_hash(frozen)
        engineering.write_json(self.root / "frozen_plan.json", original_plan)
        engineering.write_json(self.root / "frozen_cases.json", frozen)

    def source(self, root, frozen, case):
        if case["id"] == "sofa__flux1-schnell__r1":
            raise ValueError("original candidate failed")
        return deepcopy(self.sources[case["id"]])

    def freeze(self):
        with patch.object(engineering, "verify_engineering_source", side_effect=self.source):
            return engineering.freeze(self.root)

    def completed_review(self, packet, request):
        review = engineering.asset_review_template(packet, request)
        review["reviewer"] = "unit test fixture, not a real review"
        review["reviewed_views"] = list(packet["views"])
        for check in review["checks"]:
            check.update(status="pass", observation="unit test explicit requirement observation", evidence_views=packet["prior_requirement_facts"][check["requirement_id"]]["evidence_views"])
        return review

    def selected(self):
        frozen = self.freeze()
        binding = frozen["packets"]["builtin_imagegen"]
        return engineering.read_json(Path(binding["path"])), engineering.engineering_request()

    def test_freeze_scope_and_lowest_replicate_leave_original_files_untouched(self):
        before = {name: (self.root / name).read_bytes() for name in ("frozen_plan.json", "frozen_cases.json")}
        frozen = self.freeze()
        self.assertEqual({provider: engineering.read_json(Path(binding["path"]))["case"]["id"] for provider, binding in frozen["packets"].items()}, {"builtin_imagegen": "sofa__builtin_imagegen__r1", "flux1-schnell": "sofa__flux1-schnell__r2"})
        self.assertEqual(frozen["scope"], engineering.SCOPE)
        self.assertFalse(frozen["original_full_specification_passed"])
        self.assertFalse(frozen["count_toward_original_benchmark"])
        self.assertFalse((self.root / "scene_validation").exists())
        self.assertEqual(before, {name: (self.root / name).read_bytes() for name in before})
        with self.assertRaises(FileNotFoundError):
            strict.verify_prepared(self.root, self.output)

    def test_old_true_flag_or_unfilled_template_cannot_replace_new_review(self):
        packet, request = self.selected()
        template = engineering.asset_review_template(packet, request)
        template.update(requirement_compliance_passed=True, geometry_multiview_passed=True)
        with self.assertRaisesRegex(ValueError, "new explicit engineering review"):
            engineering.verify_asset_review(template, packet, request)
        complete = self.completed_review(packet, request)
        engineering.verify_asset_review(complete, packet, request)
        complete["checks"][0]["status"] = "unknown"
        with self.assertRaisesRegex(ValueError, "not passed"):
            engineering.verify_asset_review(complete, packet, request)

    def test_new_review_rejects_changed_scope_hash_missing_views_or_hidden_negatives(self):
        packet, request = self.selected()
        good = self.completed_review(packet, request)
        for key, bad in (("scope", "full_specification_quality"), ("original_full_specification_passed", True), ("count_toward_original_benchmark", True), ("packet_content_key", "wrong"), ("asset_glb_sha256", "wrong"), ("request_content_key", "wrong"), ("acknowledged_original_quality_findings_hash", content_hash([])), ("reviewed_views", [])):
            with self.subTest(key=key):
                review = deepcopy(good)
                review[key] = bad
                with self.assertRaises(ValueError):
                    engineering.verify_asset_review(review, packet, request)

    def test_unknown_required_fact_cannot_be_inferred_from_compound_observation(self):
        visual = {"supplementary_observations": {"checks": [{"requirement": "beige fabric appearance", "status": "unknown", "observation": "possibly beige", "evidence_views": ["supplement_1400px:-y"]}, {"requirement": "beige fabric and dark wooden legs", "status": "pass", "observation": "test compound", "evidence_views": ["supplement_1400px:-y"]}]}}
        with self.assertRaisesRegex(ValueError, "not explicitly passed"):
            engineering.check_fact(visual, "supplementary_observations", "beige fabric appearance")

    def test_automated_source_failure_blocks_before_any_visual_scope_exception(self):
        case = self.sources["sofa__builtin_imagegen__r1"]["case"]
        frozen = engineering.read_json(self.root / "frozen_cases.json")
        engineering.write_json(self.root / "cases" / case["id"] / "audit.json", {"schema": "p019-case-audit/v1", "case_id": case["id"], "provider": case["provider"], "automated_accepted": False, "accepted": True})
        with self.assertRaisesRegex(ValueError, "automated gate failed"):
            engineering.verify_engineering_source(self.root, frozen, case)

    def test_prepare_requires_two_new_reviews_and_preserves_generated_lifecycle(self):
        frozen = self.freeze()
        with patch.object(engineering, "verify_engineering_source", side_effect=self.source):
            with self.assertRaises(FileNotFoundError):
                engineering.prepare(self.root)
            self.assertFalse((self.output / "builtin_imagegen" / "assets").exists())
            for provider, binding in frozen["packets"].items():
                packet = engineering.read_json(Path(binding["path"]))
                engineering.write_json(self.output / "asset_reviews" / f"{packet['case']['id']}.json", self.completed_review(packet, engineering.engineering_request()))
            with patch.object(engineering, "audit_asset_source_policy", return_value={"ok": True}):
                prepared = engineering.prepare(self.root)
            self.assertEqual(prepared["status"], "prepared_not_rendered")
            for provider in engineering.PROVIDERS:
                resolution = engineering.read_json(self.output / provider / "asset_resolution.json")
                self.assertEqual(resolution["results"][0]["status"], "generated")
                self.assertEqual(resolution["results"][0]["lifecycle"]["status"], "generated_for_run")
                refs = engineering.read_json(self.output / provider / "asset_references.json")["assets"]
                self.assertEqual(refs[0]["original_quality_findings"][0]["status"], "unknown")
            report = engineering.verify(self.root)
            self.assertFalse(report["engineering_accepted"])
            self.assertFalse(report["automated_engineering_accepted"])
            self.assertFalse(report["original_full_specification_passed"])
            self.assertFalse(report["count_toward_original_benchmark"])


if __name__ == "__main__":
    unittest.main()
