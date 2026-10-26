from __future__ import annotations

import json
import hashlib
import tempfile
import unittest
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from PIL import Image

from sage.server.trellis2_flux_bridge_server import (
    JobStore, Trellis2BridgeRuntime, build_handler, provider_route,
)

from ..cli import build_parser
from ..content_chain import build_generation_contract, content_hash
from ..pipeline import image_provider_connection, run_pipeline


BRIDGE = "sage.server.trellis2_flux_bridge_server"
PIPELINE = "sage.experiments.codex_trellis_scene_v2.pipeline"


def runtime(root: Path | str = ".") -> Trellis2BridgeRuntime:
    return Trellis2BridgeRuntime(SimpleNamespace(
        output_dir=str(root), exit_after_metadata_responses=0,
        image_provider="builtin_imagegen", trellis_model="trellis-fixture",
        flux_server_url="http://127.0.0.1:8083", flux_profile="flux1-schnell",
        builtin_imagegen_url="http://127.0.0.1:8084", builtin_imagegen_timeout=1.0,
        flux_background_mode="white",
        flux_retry_count=2, flux_width=768, flux_height=768, flux_steps=4,
        flux_guidance_scale=0.0, flux_max_sequence_length=None,
    ))


def handler_instance(jobs: JobStore, bridge: Trellis2BridgeRuntime, path: str, body=None, broker=None):
    handler = build_handler(jobs, bridge, broker)
    instance = handler.__new__(handler)
    instance.path = path
    encoded = json.dumps(body if body is not None else {}).encode()
    instance.headers = {"Content-Length": str(len(encoded))}
    instance.rfile = BytesIO(encoded)
    instance._send_json = MagicMock()
    instance._send_file = MagicMock()
    return instance


class ImageProviderRoutingTest(unittest.TestCase):
    def test_scoped_routes_preserve_all_asset_client_endpoints(self):
        for provider in ("builtin_imagegen", "flux1-schnell"):
            for path in ("/health", "/generate", "/job/job-1", "/job/job-1/metadata"):
                with self.subTest(provider=provider, path=path):
                    self.assertEqual(provider_route(f"/providers/{provider}{path}"), (path, provider))
        self.assertEqual(provider_route("/generate"), ("/generate", None))
        for path in ("/providers/unknown/generate", "/providers//generate", "/providers/builtin_imagegen"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                provider_route(path)

    def test_route_body_conflict_rejects_before_resource_admission_or_job_creation(self):
        jobs, broker = JobStore(), MagicMock()
        request = handler_instance(jobs, runtime(), "/providers/builtin_imagegen/generate",
                                   {"input_text": "a chair", "image_provider": "flux1-schnell"}, broker)
        with patch(BRIDGE + ".threading.Thread") as worker:
            request.do_POST()
        self.assertEqual(request._send_json.call_args.args[0], 400)
        broker.acquire.assert_not_called()
        worker.assert_not_called()
        self.assertEqual(jobs._jobs, {})

    def test_route_provider_is_frozen_in_job_and_worker_request(self):
        for path, body, expected in (
            ("/generate", {}, "builtin_imagegen"),
            ("/generate", {"image_provider": "flux1-schnell"}, "flux1-schnell"),
            ("/providers/flux1-schnell/generate", {}, "flux1-schnell"),
        ):
            with self.subTest(path=path, body=body):
                jobs = JobStore()
                request = handler_instance(jobs, runtime(), path, {"input_text": "a chair", **body})
                with patch(BRIDGE + ".threading.Thread"):
                    request.do_POST()
                code, accepted = request._send_json.call_args.args
                self.assertEqual(code, 202)
                stored = jobs.get(accepted["job_id"])
                self.assertEqual(stored["image_provider"], expected)
                self.assertEqual(stored["request"]["image_provider"], expected)

    def test_cross_provider_cannot_read_glb_or_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            glb, metadata = root / "asset.glb", root / "metadata.json"
            glb.write_bytes(b"glTF-fixture")
            metadata.write_text("{}")
            jobs = JobStore()
            job_id = jobs.create("job-1")
            jobs.update(job_id, image_provider="builtin_imagegen", status="done",
                        glb_path=str(glb), metadata_path=str(metadata))
            for suffix in ("", "/metadata"):
                rejected = handler_instance(jobs, runtime(root), f"/providers/flux1-schnell/job/{job_id}{suffix}")
                rejected.do_GET()
                self.assertEqual(rejected._send_json.call_args.args[0], 404)
                rejected._send_file.assert_not_called()
                allowed = handler_instance(jobs, runtime(root), f"/providers/builtin_imagegen/job/{job_id}{suffix}")
                allowed.do_GET()
                allowed._send_file.assert_called_once()

    def test_health_contract_describes_requested_route_without_loading_models(self):
        bridge = runtime()
        for provider in ("builtin_imagegen", "flux1-schnell"):
            request = handler_instance(JobStore(), bridge, f"/providers/{provider}/health")
            request.do_GET()
            code, health = request._send_json.call_args.args
            self.assertEqual(code, 200)
            self.assertEqual(health["image_provider"], provider)
            self.assertEqual(health["image_provider_contract"]["provider"], provider)
        builtin = bridge.image_provider_contract("builtin_imagegen")
        self.assertIsNone(builtin["backend_model_id"])
        self.assertIsNone(builtin["requested_model"])
        self.assertEqual(builtin["model_identity_status"], "unverified")

    def test_bridge_restart_exposes_interruption_and_resumes_same_request_and_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = JobStore(root / "jobs")
            initial = handler_instance(original, runtime(root), "/providers/builtin_imagegen/generate",
                                       {"input_text": "one chair", "seed": 42})
            with patch(BRIDGE + ".threading.Thread"):
                initial.do_POST()
            self.assertEqual(initial._send_json.call_args.args[0], 202)
            job_id = initial._send_json.call_args.args[1]["job_id"]
            payload = deepcopy(original.get(job_id)["request"])
            self.assertEqual(payload["image_provider_contract"], runtime(root).image_provider_contract("builtin_imagegen"))
            restarted = JobStore(root / "jobs")
            self.assertEqual(restarted.get(job_id)["status"], "interrupted")
            for prefix in ("", "/providers/builtin_imagegen"):
                for suffix in ("", "/metadata"):
                    request = handler_instance(restarted, runtime(root), f"{prefix}/job/{job_id}{suffix}")
                    request.do_GET()
                    self.assertEqual(request._send_json.call_args.args[0], 410)
                    request._send_file.assert_not_called()
            broker = MagicMock()
            broker.acquire.return_value = {"accepted": True}
            request = handler_instance(restarted, runtime(root), f"/providers/builtin_imagegen/job/{job_id}/resume", {}, broker)
            with patch(BRIDGE + ".threading.Thread") as worker:
                request.do_POST()
            code, accepted = request._send_json.call_args.args
            self.assertEqual(code, 202)
            self.assertEqual(accepted["job_id"], job_id)
            self.assertEqual(restarted.get(job_id)["request"], payload)
            self.assertEqual(restarted.get(job_id)["status"], "processing")
            self.assertEqual(list(restarted._jobs), [job_id])
            self.assertEqual(json.loads((root / "jobs" / f"{job_id}.json").read_text())["request"], payload)
            broker.acquire.assert_called_once_with(job_id)
            worker.assert_called_once()

    def test_resume_rejects_provider_conflict_request_changes_and_completed_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for state, provider, body in (
                ("done", "builtin_imagegen", {}),
                ("interrupted", "flux1-schnell", {}),
                ("interrupted", "builtin_imagegen", {"input_text": "a different chair"}),
            ):
                with self.subTest(state=state, provider=provider, body=body):
                    jobs, broker = JobStore(), MagicMock()
                    job_id = jobs.create("job-1")
                    payload = {"image_provider": "builtin_imagegen", "input_text": "one chair",
                               "image_provider_contract": runtime(root).image_provider_contract("builtin_imagegen")}
                    jobs.update(job_id, image_provider="builtin_imagegen", status=state, request=payload)
                    request = handler_instance(jobs, runtime(root), f"/providers/{provider}/job/{job_id}/resume", body, broker)
                    with patch(BRIDGE + ".threading.Thread") as worker:
                        request.do_POST()
                    self.assertEqual(request._send_json.call_args.args[0], 400)
                    self.assertEqual(jobs.get(job_id)["status"], state)
                    self.assertEqual(jobs.get(job_id)["request"], payload)
                    broker.acquire.assert_not_called()
                    worker.assert_not_called()

    def test_resume_resource_rejection_preserves_interrupted_checkpoint(self):
        jobs, broker = JobStore(), MagicMock()
        job_id = jobs.create("job-1")
        jobs.update(job_id, image_provider="builtin_imagegen", status="interrupted",
                    request={"image_provider": "builtin_imagegen", "input_text": "one chair",
                             "image_provider_contract": runtime().image_provider_contract("builtin_imagegen")})
        before = jobs.get(job_id)
        broker.acquire.return_value = {"accepted": False, "retryable": True}
        request = handler_instance(jobs, runtime(), f"/providers/builtin_imagegen/job/{job_id}/resume", {}, broker)
        with patch(BRIDGE + ".threading.Thread") as worker:
            request.do_POST()
        self.assertEqual(request._send_json.call_args.args[0], 429)
        self.assertEqual(jobs.get(job_id), before)
        worker.assert_not_called()

    def test_resume_rejects_missing_or_changed_provider_contract(self):
        complete = runtime().image_provider_contract("builtin_imagegen")
        for contract in (None, {**complete, "retry_count": complete["retry_count"] + 1}):
            with self.subTest(contract=contract):
                jobs, broker = JobStore(), MagicMock()
                payload = {"image_provider": "builtin_imagegen", "input_text": "one chair"}
                if contract is not None:
                    payload["image_provider_contract"] = contract
                job_id = jobs.create("job-1", image_provider="builtin_imagegen", request=payload)
                jobs.update(job_id, status="interrupted")
                before = deepcopy(jobs.get(job_id))
                request = handler_instance(jobs, runtime(), f"/providers/builtin_imagegen/job/{job_id}/resume", {}, broker)
                with patch(BRIDGE + ".threading.Thread") as worker:
                    request.do_POST()
                self.assertEqual(request._send_json.call_args.args[0], 400)
                self.assertEqual(jobs.get(job_id), before)
                worker.assert_not_called()
                broker.acquire.assert_not_called()

    def test_waiting_for_image_provider_survives_restart_and_can_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs, bridge = JobStore(root / "jobs"), runtime(root)
            initial = handler_instance(jobs, bridge, "/providers/builtin_imagegen/generate", {"input_text": "one chair"})
            with patch(BRIDGE + ".threading.Thread") as worker:
                initial.do_POST()
            job_id = initial._send_json.call_args.args[1]["job_id"]
            frozen_request = deepcopy(jobs.get(job_id)["request"])
            with patch.object(bridge, "generate", side_effect=TimeoutError("waiting_for_image_provider: image-job-1")), \
                 patch.object(bridge, "cleanup_after_job"), patch("builtins.print"):
                worker.call_args.kwargs["target"]()
            restarted = JobStore(root / "jobs")
            self.assertEqual(restarted.get(job_id)["status"], "waiting_for_image_provider")
            waiting = handler_instance(restarted, bridge, f"/providers/builtin_imagegen/job/{job_id}")
            waiting.do_GET()
            code, status = waiting._send_json.call_args.args
            self.assertEqual(code, 202)
            self.assertEqual(status["status"], "waiting_for_image_provider")
            self.assertTrue(status["resume_path"].endswith(f"/job/{job_id}/resume"))
            resumed = handler_instance(restarted, bridge, f"/providers/builtin_imagegen/job/{job_id}/resume", {})
            with patch(BRIDGE + ".threading.Thread"):
                resumed.do_POST()
            self.assertEqual(resumed._send_json.call_args.args[0], 202)
            self.assertEqual(resumed._send_json.call_args.args[1]["job_id"], job_id)
            self.assertEqual(restarted.get(job_id)["request"], frozen_request)

    def test_explicit_empty_or_null_provider_is_rejected_without_defaulting(self):
        for provider in ("", None):
            with self.subTest(provider=provider):
                jobs, broker = JobStore(), MagicMock()
                request = handler_instance(jobs, runtime(), "/generate",
                                           {"input_text": "one chair", "image_provider": provider}, broker)
                with patch(BRIDGE + ".threading.Thread") as worker:
                    request.do_POST()
                self.assertEqual(request._send_json.call_args.args[0], 400)
                self.assertEqual(jobs._jobs, {})
                worker.assert_not_called()
                broker.acquire.assert_not_called()


class ImageProviderConnectionTest(unittest.TestCase):
    def args(self, **changes):
        values = dict(trellis_url="http://127.0.0.1:8082", asset_mode="trellis2", image_provider="builtin_imagegen")
        values.update(changes)
        return SimpleNamespace(**values)

    def test_conflicting_url_is_rejected_without_health_request(self):
        with patch(PIPELINE + ".bridge_health") as health, self.assertRaises(ValueError):
            image_provider_connection(self.args(trellis_url="http://127.0.0.1:8082/providers/flux1-schnell"))
        health.assert_not_called()

    def test_existing_matching_url_does_not_duplicate_provider_prefix(self):
        contract = runtime().image_provider_contract("builtin_imagegen")
        url = "http://127.0.0.1:8082/providers/builtin_imagegen"
        with patch(PIPELINE + ".bridge_health", return_value={"ok": True, "payload": {"image_provider_contract": contract}}) as health:
            endpoint, observed = image_provider_connection(self.args(trellis_url=url + "/"))
        self.assertEqual(endpoint, url)
        self.assertEqual(observed, contract)
        health.assert_called_once_with(url)

    def test_non_generation_modes_require_no_live_provider(self):
        for mode in ("plan", "reuse"):
            with patch(PIPELINE + ".bridge_health") as health:
                _, contract = image_provider_connection(self.args(asset_mode=mode))
            health.assert_not_called()
            self.assertEqual(contract["configuration_status"], "not_queried_in_non_generation_mode")

    def test_unavailable_or_wrong_provider_contract_is_rejected(self):
        for health in (
            {"ok": False, "error": "connection refused"},
            {"ok": True, "payload": {}},
            {"ok": True, "payload": {"image_provider_contract": {"provider": "flux1-schnell"}}},
        ):
            with self.subTest(health=health), patch(PIPELINE + ".bridge_health", return_value=health), self.assertRaises(RuntimeError):
                image_provider_connection(self.args())

    def test_incomplete_or_incompatible_contract_is_rejected(self):
        complete = runtime().image_provider_contract("builtin_imagegen")
        candidates = [{"provider": "builtin_imagegen"}, {**complete, "schema": "unknown/v9"},
                      {**complete, "transport": "openai_image_api"}]
        for missing in ("prompt_template_version", "background_mode", "seed_supported"):
            candidates.append({key: value for key, value in complete.items() if key != missing})
        for contract in candidates:
            with self.subTest(contract=contract), patch(PIPELINE + ".bridge_health", return_value={"ok": True, "payload": {"image_provider_contract": contract}}), self.assertRaises(RuntimeError):
                image_provider_connection(self.args())

    def test_provider_settings_reach_asset_cache_and_dag_keys(self):
        class ResolverBoundary(Exception):
            pass

        def capture(root: Path, contract: dict):
            args = build_parser().parse_args([
                "--prompt", "A study with a desk and a chair.", "--output-dir", str(root),
                "--profile", "development", "--expander", "rules", "--planner", "rules",
                "--asset-mode", "trellis2", "--image-provider", contract["provider"],
                "--generation-code-version", "test-release", "--no-assemble", "--overwrite",
            ])
            with patch(PIPELINE + ".bridge_health", return_value={"ok": True, "payload": {"image_provider_contract": contract}}), patch(PIPELINE + ".resolve_assets", side_effect=ResolverBoundary) as resolve:
                with self.assertRaises(ResolverBoundary):
                    run_pipeline(args)
            config = resolve.call_args.kwargs
            provider_record = json.loads((root / "image_provider.json").read_text())
            dag = json.loads((root / "run_dag.json").read_text())
            attempt = dag["stages"]["asset_plan"]["attempts"][-1]
            self.assertEqual(config["trellis_url"], "http://127.0.0.1:8082/providers/" + contract["provider"])
            self.assertEqual(provider_record["contract"], contract)
            self.assertEqual(provider_record["contract_hash"], content_hash(contract))
            self.assertEqual(provider_record["generation_code_version"], config["generation_code_version"])
            generation = build_generation_contract(
                category="chair", prompt="one chair", target_dimensions_m={"width": 1, "length": 1, "height": 1},
                seed=1, model_fingerprint="trellis", rmbg_fingerprint="rmbg", pipeline_type="512",
                steps=12, texture_size=512, decimation_target=300000, preprocess_image=True,
                code_version=config["generation_code_version"],
            )
            return config["generation_code_version"], generation["content_key"], attempt["input_key"]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = runtime().image_provider_contract("flux1-schnell")
            original = capture(root / "run", base)
            reordered = dict(reversed(list(base.items())))
            self.assertEqual(capture(root / "run", reordered), original)
            variations = [runtime().image_provider_contract("builtin_imagegen")]
            for key, value in (("width", 1024), ("steps", 8), ("guidance_scale", 1.0), ("prompt_template_version", "isolated-white-v2")):
                variations.append({**deepcopy(base), key: value})
            for index, contract in enumerate(variations):
                with self.subTest(contract=contract):
                    changed = capture(root / "run", contract)
                    self.assertTrue(all(a != b for a, b in zip(original, changed)))


class BuiltinImageHandleRecoveryTest(unittest.TestCase):
    prompt = "one isolated chair on white"
    reference_id = "reference-1"
    parent_id = "trellis-job-1"

    def wait(self, bridge):
        return bridge._wait_for_builtin_image(
            self.prompt, self.reference_id, parent_job_id=self.parent_id,
            specification="one chair", attempt=0,
        )

    def leave_accepted_handle(self, bridge, root):
        with patch.object(bridge, "_persistent_evidence_root", return_value=root), \
             patch(BRIDGE + ".post_json", return_value=(202, {"job_id": "image-job-1", "request_sha256": "a" * 64})) as post, \
             patch(BRIDGE + ".get_bytes", return_value=(202, b'{}', "application/json")), \
             patch(BRIDGE + ".time.monotonic", side_effect=[0, 0, 2]), \
             patch(BRIDGE + ".time.sleep"):
            with self.assertRaises(TimeoutError):
                self.wait(bridge)
        post.assert_called_once()
        self.assertTrue((root / "provider_requests" / f"{self.reference_id}.json").is_file())

    def completion(self):
        buffer = BytesIO()
        Image.new("RGB", (2, 2), "white").save(buffer, format="PNG")
        body = buffer.getvalue()
        metadata = {
            "provider": "builtin_imagegen", "job_id": "image-job-1",
            "request_id": self.reference_id, "upstream_job_id": self.parent_id,
            "request_sha256": "a" * 64,
            "image_sha256": hashlib.sha256(body).hexdigest(),
            "prompt_sha256": hashlib.sha256(self.prompt.encode()).hexdigest(),
        }
        return body, metadata

    def test_new_runtime_reuses_accepted_image_handle_without_resubmitting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.leave_accepted_handle(runtime(root), root)
            restarted = runtime(root)
            body, metadata = self.completion()
            with patch.object(restarted, "_persistent_evidence_root", return_value=root), \
                 patch(BRIDGE + ".post_json") as post, \
                 patch(BRIDGE + ".get_bytes", side_effect=[(200, body, "image/png"), (200, json.dumps(metadata).encode(), "application/json")]):
                path, observed = self.wait(restarted)
            post.assert_not_called()
            self.assertEqual(path.read_bytes(), body)
            self.assertEqual(observed, metadata)

    def test_recovered_handle_rejects_other_job_provider_image_and_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bridge = runtime(root)
            self.leave_accepted_handle(bridge, root)
            body, metadata = self.completion()
            for key in ("provider", "job_id", "image_sha256", "prompt_sha256", "request_sha256", "request_id", "upstream_job_id"):
                invalid = {**metadata, key: "wrong-binding"}
                with self.subTest(key=key), patch.object(bridge, "_persistent_evidence_root", return_value=root), \
                     patch(BRIDGE + ".post_json") as post, \
                     patch(BRIDGE + ".get_bytes", side_effect=[(200, body, "image/png"), (200, json.dumps(invalid).encode(), "application/json")]), \
                     self.assertRaises(ValueError):
                    self.wait(bridge)
                post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
