from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sage.experiments.codex_trellis_scene_v2 import p019_provider_benchmark as benchmark


def reply(status: int, value: dict, content_type: str = "application/json") -> tuple[int, bytes, str]:
    return status, json.dumps(value).encode(), content_type


class Transport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, payload=None, **kwargs):
        self.calls.append((url, payload, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        if callable(response):
            return response(url, payload, **kwargs)
        return response


class ProviderBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        specs = []
        for index, category in enumerate(benchmark.DIMENSIONS):
            prompt = f"One isolated {category}, pure white background."
            specs.append({"id": category, "prompt": prompt, "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                          "flux_seed": 123 + index, "visual_checks": ["one object"]})
        benchmark.write_json(self.root / "frozen_plan.json", {
            "providers": list(benchmark.PROVIDERS), "replicates_per_spec_provider": 2,
            "specifications": specs,
            "three_d_control": {"pipeline": "512", "steps": 12, "texture_size": 512, "decimation_target": 300000},
        })

    def runner(self, transport=None, *extra):
        args = benchmark.build_parser().parse_args(["--root", str(self.root), *extra, "status"])
        return benchmark.Benchmark(args, transport=transport or Transport())

    def selected(self, runner):
        return runner.frozen["cases"][0]

    def submit(self, runner):
        case = self.selected(runner)
        return runner.submit(case, "candidate", benchmark.candidate_request(case, runner.frozen))

    def candidate_metadata(self, runner, job_id="original"):
        case = self.selected(runner)
        source = self.root / "original_rgb.png"
        rgba = self.root / "prepared_rgba.png"
        manifest = self.root / "evidence_manifest.json"
        source.write_bytes(b"test-only source image fixture")
        rgba.write_bytes(b"test-only prepared image fixture")
        manifest.write_text("{}")
        evidence = {"parent_job_id": job_id, "reference_job_id": job_id, "image_provider": case["provider"],
                    "manifest": {"path": str(manifest), **benchmark.file_binding(manifest)},
                    "files": {"source_rgb": {"path": str(source), **benchmark.file_binding(source)},
                              "prepared_rgba": {"path": str(rgba), **benchmark.file_binding(rgba)}}}
        selected = {"reference_job_id": job_id, "image_provider": case["provider"], "prompt": f"Production prefix: {case['prompt']}",
                    "alpha_quality_ok": True, "persistent_evidence": evidence, "image_provider_metadata": None}
        return {"job_id": job_id, "image_provider": case["provider"], "input_text": case["prompt"],
                "status": "candidate_batch_done", "candidate_only": True,
                "image_provider_contract": {
                    "schema": "scene-image-provider-contract/v1", "provider": case["provider"],
                    "prompt_template_version": "isolated-white-v1", "background_mode": "white", "retry_count": 0,
                    "transport": "codex_tool_spool/v1", "requested_model": None, "backend_model_id": None,
                    "model_identity_status": "unverified", "seed_supported": False, "size_control_supported": False,
                },
                "reference_attempts": [selected], "selected_reference_job_id": job_id, "selected_reference_evidence": evidence}

    def test_freeze_retains_all_twelve_and_shared_reconstruction_seeds(self):
        runner = self.runner()
        cases = runner.frozen["cases"]
        self.assertEqual(len(cases), 12)
        self.assertEqual(len({case["id"] for case in cases}), 12)
        for category in benchmark.DIMENSIONS:
            for replicate in (1, 2):
                pair = [case for case in cases if case["category"] == category and case["replicate"] == replicate]
                self.assertEqual(pair[0]["seed"], pair[1]["seed"])
                self.assertEqual(pair[0]["prompt"], pair[1]["prompt"])
                self.assertIsNone(pair[0]["image_seed"])
        self.assertEqual(runner.frozen, benchmark.freeze(self.root))
        plan = benchmark.read_json(self.root / "frozen_plan.json")
        plan["specifications"][0]["prompt"] += " changed"
        benchmark.write_json(self.root / "frozen_plan.json", plan)
        with self.assertRaisesRegex(ValueError, "prompt hash mismatch"):
            benchmark.freeze(self.root)

    def test_legacy_plan_preserves_pre_filter_frozen_bytes_and_content_key(self):
        runner = self.runner()
        # Golden values captured before optional specification filtering was
        # implemented, from this deterministic three-specification fixture.
        self.assertEqual(runner.frozen["content_key"], "5efc6e450b3c718bfa53d39776cf3e82c3c72508f679fbff76bc72270105777b")
        frozen_path = self.root / "frozen_cases.json"
        self.assertEqual(benchmark.file_binding(frozen_path), {
            "bytes": 7187, "sha256": "e823ddd1d40aa0868693215479f67c027772002501ed5364b08a3b16eb3d886d"})
        before = frozen_path.read_bytes()
        benchmark.freeze(self.root)
        self.assertEqual(frozen_path.read_bytes(), before)
        self.assertNotIn("included_specifications", runner.frozen)
        self.assertNotIn("followup_to_plan", runner.frozen)

    def test_bookcase_followup_has_four_cases_and_uses_four_case_completion_barrier(self):
        plan_path = self.root / "frozen_plan.json"
        original = benchmark.read_json(plan_path)
        plan = {**original, "included_specifications": ["bookcase"], "followup_to_plan": benchmark.content_hash(original)}
        benchmark.write_json(plan_path, plan)
        runner = self.runner()
        cases = runner.frozen["cases"]
        self.assertEqual(len(cases), 4)
        self.assertEqual({case["category"] for case in cases}, {"bookcase"})
        self.assertEqual({(case["provider"], case["replicate"]) for case in cases}, {
            ("builtin_imagegen", 1), ("builtin_imagegen", 2), ("flux1-schnell", 1), ("flux1-schnell", 2)})
        self.assertEqual(runner.frozen["included_specifications"], ["bookcase"])
        self.assertEqual(runner.frozen["followup_to_plan"], benchmark.content_hash(original))
        self.assertEqual(benchmark.read_json(plan_path)["specifications"], original["specifications"])
        self.assertEqual(runner.frozen["preregistration_hash"], benchmark.content_hash(plan))
        for case in cases[:3]:
            benchmark.write_json(runner.directory(case, "candidate") / "result.json", {"status": "candidate_rejected", "ok": False})
        self.assertFalse(runner.all_candidates_terminal())
        with self.assertRaisesRegex(ValueError, "every frozen 2D attempt"):
            runner.submit_stage("trellis")
        benchmark.write_json(runner.directory(cases[-1], "candidate") / "result.json", {"status": "candidate_rejected", "ok": False})
        self.assertTrue(runner.all_candidates_terminal())
        report = runner.submit_stage("trellis")
        self.assertEqual(report["planned_case_count"], 4)
        self.assertTrue(report["all_candidates_terminal"])
        self.assertTrue(report["all_trellis_terminal"])
        self.assertEqual(set(report["composed_prompt_comparison"]), {"bookcase"})
        self.assertEqual(report["by_provider"]["builtin_imagegen"]["planned"], 2)
        self.assertEqual(report["by_provider"]["flux1-schnell"]["planned"], 2)
        self.assertTrue(all(row["trellis"]["status"] == "skipped_candidate_rejected" for row in report["results"]))

    def test_included_specifications_rejects_empty_unknown_duplicate_and_invalid_types(self):
        plan_path = self.root / "frozen_plan.json"
        original = benchmark.read_json(plan_path)
        for included in ([], ["unknown"], ["bookcase", "bookcase"], None, "bookcase", [None], [["bookcase"]]):
            with self.subTest(included=included):
                benchmark.write_json(plan_path, {**original, "included_specifications": included})
                with self.assertRaisesRegex(ValueError, "included_specifications"):
                    benchmark.freeze(self.root)
                self.assertFalse((self.root / "frozen_cases.json").exists())

    def test_specification_filter_cannot_be_added_to_an_existing_frozen_run(self):
        self.runner()
        frozen_path = self.root / "frozen_cases.json"
        before = frozen_path.read_bytes()
        plan_path = self.root / "frozen_plan.json"
        plan = benchmark.read_json(plan_path)
        plan["included_specifications"] = ["bookcase"]
        benchmark.write_json(plan_path, plan)
        with self.assertRaisesRegex(ValueError, "Existing frozen cases differ"):
            benchmark.freeze(self.root)
        self.assertEqual(frozen_path.read_bytes(), before)

    def test_accepted_id_is_durable_before_first_poll_and_repeat_submit(self):
        transport = Transport(reply(202, {"job_id": "original"}))
        runner = self.runner(transport)
        self.submit(runner)
        case = self.selected(runner)
        accepted = benchmark.read_json(runner.directory(case, "candidate") / "accepted.json")
        self.assertEqual(accepted["job_id"], "original")
        self.assertEqual(self.submit(runner)["status"], "already_submitted")
        self.assertEqual(len(transport.calls), 1)
        self.assertIn("/providers/builtin_imagegen/generate", transport.calls[0][0])

    def test_lost_post_response_never_resubmits_and_can_reconcile_server_owned_contract(self):
        transport = Transport(TimeoutError("response lost"))
        job_store = self.root / "bridge_jobs"
        runner = self.runner(transport, "--bridge-job-dir", str(job_store))
        self.assertEqual(self.submit(runner)["status"], "submission_uncertain")
        self.assertEqual(self.submit(runner)["status"], "submission_uncertain")
        self.assertEqual(len(transport.calls), 1)
        case = self.selected(runner)
        payload = benchmark.candidate_request(case, runner.frozen)
        payload["image_provider_contract"] = {"provider": "builtin_imagegen"}
        benchmark.write_json(job_store / "original.json", {"request": payload, "created_at": 100})
        recovered = self.submit(runner)
        self.assertEqual(recovered["job_id"], "original")
        self.assertEqual(recovered["status"], "accepted")
        self.assertEqual(len(transport.calls), 1)

    def test_429_remains_unsubmitted_and_does_not_count_as_sample_failure(self):
        transport = Transport(reply(429, {"retryable": True}), reply(202, {"job_id": "original"}))
        runner = self.runner(transport)
        self.assertEqual(self.submit(runner)["status"], "pending_not_submitted")
        self.assertIsNone(runner.stage_result(self.selected(runner), "candidate"))
        self.assertEqual(self.submit(runner)["status"], "accepted")

    def test_waiting_provider_is_not_terminal_and_requires_explicit_resume(self):
        transport = Transport(reply(202, {"job_id": "original"}),
                              reply(202, {"status": "waiting_for_image_provider", "resume_path": "/job/original/resume"}),
                              reply(202, {"status": "waiting_for_image_provider", "resume_path": "/job/original/resume"}),
                              reply(202, {"job_id": "original"}))
        runner = self.runner(transport)
        self.submit(runner)
        case = self.selected(runner)
        self.assertEqual(runner.poll_one(case, "candidate")["status"], "waiting_for_image_provider")
        self.assertIsNone(runner.stage_result(case, "candidate"))
        self.assertEqual(len(transport.calls), 2)
        runner.args.resume_pending = True
        self.assertEqual(runner.poll_one(case, "candidate")["status"], "processing")
        self.assertEqual(transport.calls[-1][0], runner.bridge_url + "/job/original/resume")
        self.assertIsNone(transport.calls[-1][1])
        self.assertEqual(transport.calls[-1][2]["method"], "POST")

    def test_interrupted_bridge_resumes_original_job_with_empty_body(self):
        transport = Transport(reply(202, {"job_id": "original"}), reply(410, {"status": "interrupted"}), reply(202, {"job_id": "original"}))
        runner = self.runner(transport)
        self.submit(runner)
        self.assertEqual(runner.poll_one(self.selected(runner), "candidate")["status"], "processing")
        self.assertIsNone(transport.calls[-1][1])
        self.assertEqual(benchmark.read_json(runner.directory(self.selected(runner), "candidate") / "accepted.json")["job_id"], "original")

    def test_failed_candidate_retained_in_all_case_denominator(self):
        transport = Transport(reply(202, {"job_id": "original"}), reply(500, {"error": "alpha QA rejected"}), reply(404, {"error": "metadata unavailable"}))
        runner = self.runner(transport)
        self.submit(runner)
        result = runner.poll_one(self.selected(runner), "candidate")
        self.assertEqual(result["status"], "bridge_failed")
        summary = runner.summary()
        self.assertEqual(summary["planned_case_count"], 12)
        self.assertEqual(summary["by_provider"]["builtin_imagegen"]["candidate_terminal"], 1)
        self.assertEqual(summary["by_provider"]["builtin_imagegen"]["candidate_accepted"], 0)
        self.assertFalse(summary["all_candidates_terminal"])

    def test_promote_requires_all_twelve_candidate_outcomes(self):
        runner = self.runner()
        with self.assertRaisesRegex(ValueError, "every frozen 2D attempt"):
            runner.submit_stage("trellis")

    @patch("sage.experiments.codex_trellis_scene_v2.asset_source_policy.validate_reference_evidence", return_value={"ok": True, "failures": []})
    def test_candidate_binding_rejects_wrong_provider_retry_controls_and_extra_attempts(self, gate):
        runner = self.runner()
        case = self.selected(runner)
        metadata = self.candidate_metadata(runner)
        self.assertTrue(benchmark.candidate_quality(metadata, case, "original")["ok"])
        metadata["image_provider"] = "flux1-schnell"
        metadata["image_provider_contract"]["retry_count"] = 1
        metadata["reference_attempts"].append({"reference_job_id": "unplanned_reroll"})
        report = benchmark.candidate_quality(metadata, case, "original")
        self.assertFalse(report["ok"])
        self.assertIn("candidate_provider_binding", report["failures"])
        self.assertIn("provider_control:retry_count", report["failures"])
        self.assertIn("candidate_count_not_one", report["failures"])

    @patch("sage.experiments.codex_trellis_scene_v2.asset_source_policy.validate_reference_evidence", return_value={"ok": True, "failures": []})
    def test_promotes_original_persistent_rgb_with_identical_provider_and_controls(self, gate):
        runner = self.runner()
        case = self.selected(runner)
        metadata = self.candidate_metadata(runner)
        directory = runner.directory(case, "candidate")
        benchmark.write_json(directory / "bridge_metadata.json", metadata)
        benchmark.write_json(directory / "result.json", {"job_id": "original", "ok": True, "status": "candidate_accepted"})
        request = runner.promotion_request(case)
        self.assertEqual(request["reference_image_path"], metadata["selected_reference_evidence"]["files"]["source_rgb"]["path"])
        self.assertNotEqual(request["reference_image_path"], metadata["selected_reference_evidence"]["files"]["prepared_rgba"]["path"])
        self.assertEqual(request["image_provider"], "builtin_imagegen")
        self.assertEqual(request["image_provider_contract"], metadata["image_provider_contract"])
        self.assertEqual(request["image_provider_contract"]["prompt_template_version"], "isolated-white-v1")
        self.assertEqual([request[key] for key in ("sparse_steps", "shape_steps", "tex_steps")], [12, 12, 12])
        self.assertEqual(request["texture_size"], 512)
        self.assertEqual(request["decimation_target"], 300000)
        self.assertFalse(request["candidate_only"])

    @patch("sage.experiments.codex_trellis_scene_v2.asset_source_policy.validate_reference_evidence", return_value={"ok": True, "failures": []})
    def test_promotion_rejects_candidate_without_provider_contract(self, gate):
        runner = self.runner()
        case = self.selected(runner)
        metadata = self.candidate_metadata(runner)
        metadata.pop("image_provider_contract")
        directory = runner.directory(case, "candidate")
        benchmark.write_json(directory / "bridge_metadata.json", metadata)
        benchmark.write_json(directory / "result.json", {"job_id": "original", "ok": True, "status": "candidate_accepted"})
        with self.assertRaisesRegex(ValueError, "Candidate evidence changed before promotion"):
            runner.promotion_request(case)

    @patch("sage.experiments.codex_trellis_scene_v2.asset_source_policy.validate_reference_evidence", return_value={"ok": True, "failures": []})
    def test_promotion_sends_frozen_template_to_bridge_and_retains_rejection(self, gate):
        def server_with_new_template(url, payload, **kwargs):
            self.assertTrue(url.endswith("/providers/builtin_imagegen/generate"))
            self.assertEqual(payload["image_provider_contract"]["prompt_template_version"], "isolated-white-v1")
            return reply(400, {"error": "Image provider contract changed; current template is isolated-white-v2"})
        runner = self.runner(Transport(server_with_new_template))
        case = self.selected(runner)
        metadata = self.candidate_metadata(runner)
        directory = runner.directory(case, "candidate")
        benchmark.write_json(directory / "bridge_metadata.json", metadata)
        benchmark.write_json(directory / "result.json", {"job_id": "original", "ok": True, "status": "candidate_accepted"})
        result = runner.submit(case, "trellis", runner.promotion_request(case))
        self.assertEqual(result["status"], "submission_rejected")
        self.assertFalse((runner.directory(case, "trellis") / "accepted.json").exists())

    @patch("sage.experiments.codex_trellis_scene_v2.asset_source_policy.validate_reference_evidence", return_value={"ok": True, "failures": []})
    def test_generation_contract_changes_with_provider_and_source_content(self, gate):
        runner = self.runner()
        case = self.selected(runner)
        metadata = self.candidate_metadata(runner)
        benchmark.write_json(runner.directory(case, "candidate") / "bridge_metadata.json", metadata)
        request = benchmark.candidate_request(case, runner.frozen)
        benchmark.write_json(runner.directory(case, "trellis") / "request.json", {"request_hash": benchmark.content_hash(request)})
        source = Path(metadata["selected_reference_evidence"]["files"]["source_rgb"]["path"])
        first = runner.generation_contract(case, {"job_id": "trellis"}, source)
        self.assertEqual(first["content_key"], benchmark.content_hash({key: value for key, value in first.items() if key != "content_key"}))
        self.assertEqual(first["reference_image"], benchmark.file_binding(source))
        source.write_bytes(b"changed image fixture")
        second = runner.generation_contract(case, {"job_id": "trellis"}, source)
        self.assertNotEqual(first["content_key"], second["content_key"])
        other_case = {**case, "provider": "flux1-schnell"}
        third = runner.generation_contract(other_case, {"job_id": "trellis"}, source)
        self.assertNotEqual(second["content_key"], third["content_key"])

    @patch("sage.experiments.codex_trellis_scene_v2.asset_source_policy.validate_reference_evidence", return_value={"ok": True, "failures": []})
    @patch("sage.experiments.codex_trellis_scene_v2.asset_source_policy.audit_asset_source_policy", return_value={"ok": True, "failures": []})
    @patch("sage.experiments.codex_trellis_scene_v2.white_background_real_batch._inspect_glb", return_value={"ok": True})
    def test_audit_binds_generation_and_all_twelve_views_and_resumes_valid_captures(self, inspect, source_gate, reference_gate):
        from sage.experiments.codex_trellis_scene_v2.scene_dna_multiview import VIEW_AXES
        from sage.experiments.codex_trellis_scene_v2.white_background_real_batch import LOW_UNDER_AXES

        blender = self.root / "blender_fixture"
        blender.write_bytes(b"test-only executable identity; never executed")
        runner = self.runner(None, "--blender", str(blender))
        case = self.selected(runner)
        candidate_metadata = self.candidate_metadata(runner)
        benchmark.write_json(runner.directory(case, "candidate") / "bridge_metadata.json", candidate_metadata)
        benchmark.write_json(runner.directory(case, "candidate") / "result.json", {"job_id": "original", "ok": True, "status": "candidate_accepted"})
        payload = runner.promotion_request(case)
        benchmark.write_json(runner.directory(case, "trellis") / "request.json", {"payload": payload, "request_hash": benchmark.content_hash(payload)})
        metadata = deepcopy(candidate_metadata)
        metadata.update(job_id="trellis", status="done", pipeline_type="512", requested_pipeline_type="512",
                        postprocess_attempts=[{"ok": True, "texture_size": 512, "decimation_target": 300000}])
        benchmark.write_json(runner.directory(case, "trellis") / "bridge_metadata.json", metadata)
        glb = runner.directory(case) / "assets" / f"{case['id']}.glb"
        benchmark.atomic_bytes(glb, b"glTFtest-only-content-binding-fixture")
        benchmark.write_json(runner.directory(case, "trellis") / "result.json", {
            "job_id": "trellis", "status": "generated", "ok": True, "glb_path": str(glb), "glb_binding": benchmark.file_binding(glb)})

        def render_fixture(output_dir, axes):
            views = {}
            for axis in axes:
                path = output_dir / f"fixture_{axis}.png"
                benchmark.atomic_bytes(path, f"test-only-{axis}".encode())
                views[axis] = str(path)
            benchmark.write_json(output_dir / "asset_turntable_manifest.json", {"views": {case["id"]: views}})
            return views

        def standard_render(**kwargs):
            self.assertTrue(kwargs["obj"]["asset_generation_contract"])
            self.assertEqual(kwargs["obj"]["asset_generation_key"], kwargs["obj"]["asset_generation_contract"]["content_key"])
            render_fixture(kwargs["output_dir"], VIEW_AXES)
            return {"hard_geometry_gate_passed": True}

        def low_render(**kwargs):
            views = render_fixture(kwargs["output_dir"], LOW_UNDER_AXES)
            return {"ok": True, "views": views}

        with patch("sage.experiments.codex_trellis_scene_v2.scene_dna_multiview.render_and_evaluate_generated_asset", side_effect=standard_render) as standard, \
             patch("sage.experiments.codex_trellis_scene_v2.white_background_real_batch.render_low_under", side_effect=low_render) as low:
            first = runner.audit_one(case)
            self.assertTrue(first["automated_accepted"])
            self.assertFalse(first["accepted"])
            self.assertEqual(first["standard_camera_count"], 4)
            self.assertEqual(first["low_under_camera_count"], 8)
            certificate = benchmark.read_json(runner.directory(case) / "audit_certificate.json")
            self.assertEqual(certificate["upstream"]["generation_key"], first["generation_key"])
            self.assertEqual(len([key for key in certificate["evidence"] if key.startswith("standard_") and key != "standard_report"]), 4)
            self.assertEqual(len([key for key in certificate["evidence"] if key.startswith("low_under_") and key != "low_under_report"]), 8)
            benchmark.write_json(runner.directory(case) / "visual_review.json", {
                "reviewer": "CPU fixture reviewer", "generation_key": first["generation_key"], "glb_sha256": first["glb_sha256"],
                "requirement_compliance_passed": True, "geometry_multiview_passed": True})
            second = runner.audit_one(case)
            self.assertTrue(second["accepted"])
            self.assertEqual(standard.call_count, 1)
            self.assertEqual(low.call_count, 1)
            Path(second["standard_views"]["+x"]).write_bytes(b"changed view fixture")
            runner.audit_one(case)
            self.assertEqual(standard.call_count, 2)
            self.assertEqual(low.call_count, 1)
            glb.write_bytes(b"glTFchanged content")
            rejected = runner.audit_one(case)
            self.assertFalse(rejected["accepted"])
            self.assertIn("downloaded_glb_content_changed", rejected["failures"])
            self.assertEqual(standard.call_count, 2)

    def test_metrics_separate_builtin_queue_from_executor_and_reported_local_stages(self):
        result = benchmark.measured_stage_times({
            "image_provider_metadata": {"created_at": 10, "claimed_at": 17, "completed_at": 39, "elapsed_seconds": 29},
            "pipeline_run_attempts": [{"elapsed_seconds": 3}, {"elapsed_seconds": 5}],
            "postprocess_attempts": [{"elapsed_seconds": 4}],
        })
        self.assertEqual(result["builtin_request_to_executor_claim_seconds"], 7)
        self.assertEqual(result["builtin_executor_claim_to_import_seconds"], 22)
        self.assertEqual(result["trellis_pipeline_reported_seconds"], 8)
        self.assertEqual(result["trellis_postprocess_reported_seconds"], 4)
        self.assertIsNone(result["compute_active_seconds"])

    def test_failure_classification_requires_explicit_stage_evidence(self):
        self.assertEqual(benchmark.classify_failure({"error": "All reference attempts failed white-background isolation QA: exposed_support_background_gap_missing"})["failure_class"], "qa_rejected")
        self.assertEqual(benchmark.classify_failure({"error": "Connection refused"})["failure_class"], "infrastructure_failure")
        self.assertEqual(benchmark.classify_failure({"error": "Builtin image job abc failed: tool error"})["failure_class"], "image_provider_failure")
        self.assertEqual(benchmark.classify_failure({"error": "Something failed"})["failure_class"], "unclassified_failure")

    def test_rejected_evidence_is_linked_only_to_its_original_job(self):
        runner = self.runner()
        image = self.root / "rejected-image-fixture"
        image.write_bytes(b"test-only failed candidate")
        evidence = {"parent_job_id": "original", "reference_job_id": "original", "files": {"source_rgb": {"path": str(image), **benchmark.file_binding(image)}}}
        directory = self.root / "evidence" / "original" / "attempts"
        benchmark.write_json(directory / "original.json", evidence)
        benchmark.write_json(directory / "wrong-job.json", {**evidence, "parent_job_id": "unrelated"})
        records = runner.failure_evidence("original")
        self.assertEqual(len(records), 1)
        self.assertTrue(records[0]["content_binding_ok"])
        self.assertFalse(records[0]["admitted"])
        image.write_bytes(b"changed failed image")
        self.assertFalse(runner.failure_evidence("original")[0]["content_binding_ok"])


if __name__ == "__main__":
    unittest.main()
