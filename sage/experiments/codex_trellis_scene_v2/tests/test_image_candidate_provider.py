"""Offline contract tests; all images below are explicitly synthetic fixtures."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from PIL import Image

from sage.experiments.codex_trellis_scene_v2.image_candidate_provider import (
    ImageCandidateJobSpool,
    ImageProviderConflict,
    ImageProviderError,
    ImageProviderIntegrityError,
    canonical_json,
    main,
    sha256_bytes,
)
from sage.server.builtin_imagegen_server import build_handler


class ImageCandidateSpoolTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "jobs"
        self.now = 1000.0
        self.spool = ImageCandidateJobSpool(self.root, clock=lambda: self.now)
        self.source = Path(self.temp.name) / "synthetic_contract_fixture.png"
        Image.new("RGB", (32, 24), "white").save(self.source)
        self.payload = {
            "prompt": "Exact prompt for a synthetic test fixture.\n",
            "provider": "builtin_imagegen",
            "request_id": "reference_attempt_2",
            "upstream_job_id": "trellis_parent",
            "specification": {"category": "test_fixture"},
            "attempt": 2,
            "requested_model": None,
            "seed": 123,
        }

    def submit_claim(self, **submit_args):
        job = self.spool.submit(self.payload, **submit_args)
        claim = self.spool.claim(job["job_id"], owner="unittest synthetic executor")
        return job, claim

    def fulfil(self, job, claim, **kwargs):
        values = {
            "claim_token": claim["claim_token"],
            "request_sha256": job["request_sha256"],
            "prompt_sha256": job["prompt_sha256"],
            "tool_call_id": "synthetic_unit_test_tool_call",
        }
        values.update(kwargs)
        return self.spool.fulfil(job["job_id"], self.source, **values)

    def test_absent_executor_remains_waiting_across_restart_without_image(self):
        job = self.spool.submit(self.payload)
        self.now += 100_000
        restarted = ImageCandidateJobSpool(self.root, clock=lambda: self.now)
        status = restarted.get(job["job_id"])
        self.assertEqual(status["status"], "waiting_for_image_provider")
        self.assertFalse(list(self.root.glob("builtin_*/source.*")))
        self.assertEqual(restarted.pending()[0]["job_id"], job["job_id"])
        self.assertIsNone(status["backend_model_id"])
        self.assertFalse(status["strict_model_identity_verified"])

    def test_request_idempotence_and_each_changed_input_invalidates_cache(self):
        first = self.spool.submit(self.payload)
        reordered = dict(reversed(list(self.payload.items())))
        second = self.spool.submit(reordered)
        self.assertEqual(first["job_id"], second["job_id"])
        self.assertEqual(first["request_sha256"], sha256_bytes(canonical_json(self.payload)))
        self.assertEqual(first["prompt_sha256"], sha256_bytes(self.payload["prompt"].encode()))
        for key, value in [("prompt", "other"), ("attempt", 3), ("seed", 321), ("specification", {"category": "other"})]:
            changed = self.spool.submit({**self.payload, key: value})
            self.assertNotEqual(first["job_id"], changed["job_id"])

    def test_concurrent_store_instances_submit_and_claim_only_once(self):
        def submit(_):
            return ImageCandidateJobSpool(self.root).submit(self.payload)["job_id"]

        with ThreadPoolExecutor(max_workers=8) as pool:
            ids = list(pool.map(submit, range(16)))
        self.assertEqual(len(set(ids)), 1)

        def claim(_):
            try:
                return ImageCandidateJobSpool(self.root).claim(ids[0], owner="test")["claim_token"]
            except ImageProviderConflict:
                return None

        with ThreadPoolExecutor(max_workers=8) as pool:
            claims = list(pool.map(claim, range(16)))
        self.assertEqual(sum(value is not None for value in claims), 1)

    def test_separate_cli_processes_share_one_committed_request(self):
        request_path = Path(self.temp.name) / "request.json"
        request_path.write_bytes(canonical_json(self.payload))
        command = [sys.executable, "-m", "sage.experiments.codex_trellis_scene_v2.image_candidate_provider",
                   "--spool-dir", str(self.root), "submit", "--request-json", str(request_path)]

        def submit(_):
            result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=10)
            return json.loads(result.stdout)["job_id"]

        with ThreadPoolExecutor(max_workers=4) as pool:
            ids = list(pool.map(submit, range(4)))
        self.assertEqual(len(set(ids)), 1)
        self.assertEqual(len(self.spool.pending()), 1)

    def test_expired_claim_recovers_and_fences_old_executor(self):
        job, old = self.submit_claim()
        self.now += 901
        self.assertEqual(self.spool.get(job["job_id"])["status"], "waiting_for_image_provider")
        new = self.spool.claim(job["job_id"], owner="replacement executor")
        self.assertNotEqual(old["claim"]["attempt_id"], new["claim"]["attempt_id"])
        with self.assertRaisesRegex(ImageProviderConflict, "token"):
            self.fulfil(job, old)
        self.fulfil(job, new)
        self.assertEqual(self.spool.get(job["job_id"])["attempt_count"], 2)

    def test_heartbeat_extends_owned_claim(self):
        job, claim = self.submit_claim()
        self.now += 800
        self.spool.heartbeat(job["job_id"], claim_token=claim["claim_token"], lease_seconds=600)
        self.now += 200
        self.assertEqual(self.spool.get(job["job_id"])["status"], "claimed")
        with self.assertRaises(ImageProviderConflict):
            self.spool.heartbeat(job["job_id"], claim_token="wrong")

    def test_explicit_failure_and_retry_preserve_same_request_and_history(self):
        job, claim = self.submit_claim()
        failed = self.spool.fail(job["job_id"], claim_token=claim["claim_token"], error="synthetic tool timeout")
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(self.spool.submit(self.payload)["status"], "failed")
        retried = self.spool.retry(job["job_id"], reason="executor resumed")
        self.assertEqual(retried["job_id"], job["job_id"])
        self.assertEqual(retried["status"], "waiting_for_image_provider")
        self.assertEqual(retried["retries"][0]["error"], "synthetic tool timeout")

    def test_explicit_job_deadline_survives_restart_until_explicit_retry(self):
        job = self.spool.submit(self.payload, timeout_seconds=30)
        self.now += 31
        restarted = ImageCandidateJobSpool(self.root, clock=lambda: self.now)
        self.assertEqual(restarted.get(job["job_id"])["status"], "expired")
        with self.assertRaises(ImageProviderConflict):
            restarted.claim(job["job_id"], owner="test")
        retried = restarted.retry(job["job_id"], reason="explicit retry", timeout_seconds=50)
        self.assertEqual(retried["deadline_at"], self.now + 50)

    def test_completed_result_bytes_and_metadata_keep_request_provenance(self):
        job, claim = self.submit_claim()
        result = self.fulfil(job, claim)
        body, mime_type = self.spool.image_bytes(job["job_id"])
        self.assertEqual(body, self.source.read_bytes())
        self.assertEqual(mime_type, "image/png")
        self.assertEqual((result["width"], result["height"]), (32, 24))
        self.assertEqual(result["request_id"], self.payload["request_id"])
        self.assertEqual(result["upstream_job_id"], self.payload["upstream_job_id"])
        self.assertEqual(result["source_image_sha256"], sha256_bytes(body))
        self.assertEqual(result["provenance_verification"], "executor_attestation")
        self.assertEqual(result["tool_call_id_source"], "executor_correlation_id")
        self.assertIsNone(result["requested_model"])
        self.assertIsNone(result["backend_model_id"])
        self.assertIsNone(result["seed"])
        self.assertEqual(result["requested_seed"], 123)
        self.assertEqual(result["model_identity_status"], "unverified")
        request_file = result["request_file"]
        self.assertEqual(request_file["sha256"], sha256_bytes(Path(request_file["path"]).read_bytes()))
        self.assertEqual(self.fulfil(job, claim), result)
        with self.assertRaises(ImageProviderConflict):
            self.fulfil(job, claim, tool_call_id="different_call")
        self.assertNotIn("claim_token", json.dumps(self.spool.get(job["job_id"])))

    def test_import_rejects_wrong_request_prompt_claim_and_missing_tool_call(self):
        job, claim = self.submit_claim()
        for field, value in [("request_sha256", "0" * 64), ("prompt_sha256", "0" * 64), ("claim_token", "wrong"), ("tool_call_id", "")]:
            with self.subTest(field=field), self.assertRaises(ImageProviderError):
                self.fulfil(job, claim, **{field: value})
        self.assertEqual(self.spool.get(job["job_id"])["status"], "claimed")
        self.assertFalse((self.root / job["job_id"] / "metadata.json").exists())

    def test_image_import_rejects_nonimage_and_truncated_container(self):
        job, claim = self.submit_claim()
        for body in [b"not an image", b"\x89PNG\r\n\x1a\nnot really a PNG", self.source.read_bytes()[:40]]:
            self.source.write_bytes(body)
            with self.assertRaises(ImageProviderError):
                self.fulfil(job, claim)

    def test_request_metadata_state_and_image_tampering_cannot_hit_cache(self):
        for filename in ["request.json", "metadata.json", "state.json", "source.png"]:
            with self.subTest(filename=filename):
                spool = ImageCandidateJobSpool(Path(self.temp.name) / filename)
                job = spool.submit(self.payload)
                claim = spool.claim(job["job_id"], owner="test")
                spool.fulfil(job["job_id"], self.source, claim_token=claim["claim_token"],
                             request_sha256=job["request_sha256"], prompt_sha256=job["prompt_sha256"], tool_call_id="test_fixture_call")
                path = spool.root / job["job_id"] / filename
                if filename.endswith("json"):
                    value = json.loads(path.read_bytes())
                    value["provider"] = "forged_provider"
                    path.write_bytes(canonical_json(value))
                else:
                    path.write_bytes(b"tampered image")
                with self.assertRaises(ImageProviderIntegrityError):
                    spool.get(job["job_id"])
                with self.assertRaises(ImageProviderIntegrityError):
                    spool.submit(self.payload)

    def test_key_or_state_loss_is_rejected_without_recreating_existing_jobs(self):
        job, _ = self.submit_claim()
        (self.root / job["job_id"] / "state.json").unlink()
        with self.assertRaisesRegex(ImageProviderIntegrityError, "state"):
            self.spool.submit(self.payload)
        (self.root / ".integrity.key").unlink()
        with self.assertRaisesRegex(ImageProviderIntegrityError, "key missing"):
            ImageCandidateJobSpool(self.root)

    def test_interrupted_result_commit_recovers_without_a_second_tool_call(self):
        job, claim = self.submit_claim()
        original_write = self.spool._write

        def interrupted_write(path, record):
            if path.name == "state.json" and record.get("status") == "done":
                raise OSError("synthetic crash after metadata fsync")
            original_write(path, record)

        with patch.object(self.spool, "_write", side_effect=interrupted_write):
            with self.assertRaisesRegex(OSError, "synthetic crash"):
                self.fulfil(job, claim)
        self.now += 2000
        restarted = ImageCandidateJobSpool(self.root, clock=lambda: self.now)
        self.assertEqual(restarted.get(job["job_id"])["status"], "done")
        self.assertEqual(restarted.image_bytes(job["job_id"])[0], self.source.read_bytes())
        with self.assertRaises(ImageProviderConflict):
            restarted.claim(job["job_id"], owner="would duplicate")

    def test_orphan_image_is_never_treated_as_a_completed_generation(self):
        job, _ = self.submit_claim()
        (self.root / job["job_id"] / "source.png").write_bytes(self.source.read_bytes())
        self.now += 1000
        self.assertEqual(self.spool.get(job["job_id"])["status"], "waiting_for_image_provider")
        with self.assertRaises(ImageProviderConflict):
            self.spool.image_bytes(job["job_id"])

    def test_optional_tool_result_is_persisted_and_verified(self):
        job, claim = self.submit_claim()
        tool_json = Path(self.temp.name) / "synthetic_tool_result.json"
        tool_json.write_text('{"synthetic_test_fixture": true}')
        metadata = self.fulfil(job, claim, tool_result_json=tool_json)
        Path(metadata["tool_result"]["path"]).write_text("{}")
        with self.assertRaisesRegex(ImageProviderIntegrityError, "tool result"):
            self.spool.metadata(job["job_id"])

    def test_invalid_provider_backend_claims_and_nonfinite_inputs_rejected(self):
        for payload in [[], {}, {"prompt": " "}, {"prompt": "test", "provider": "flux1-schnell"},
                        {"prompt": "test", "model": "gpt-image-2"}, {"prompt": "test", "seed": float("nan")}]:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.spool.submit(payload)
        for job_id in ["../other", "builtin_../../etc/passwd", "x"]:
            with self.assertRaises(ImageProviderError):
                self.spool.get(job_id)
        with self.assertRaises(ImageProviderError):
            self.spool.submit(self.payload, timeout_seconds=float("inf"))

    def test_cli_reads_persistent_pending_request(self):
        job = self.spool.submit(self.payload)
        output = StringIO()
        with redirect_stdout(output):
            code = main(["--spool-dir", str(self.root), "pending"])
        self.assertEqual(code, 0)
        value = json.loads(output.getvalue())
        self.assertEqual(value[0]["job_id"], job["job_id"])
        self.assertEqual(value[0]["prompt"], self.payload["prompt"])


class BuiltinImageHTTPTest(unittest.TestCase):
    def test_http_contract_waiting_real_bytes_metadata_and_rejected_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            spool = ImageCandidateJobSpool(Path(directory) / "jobs")
            server = ThreadingHTTPServer(("127.0.0.1", 0), build_handler(spool))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(server.server_close)
            self.addCleanup(thread.join, 2)
            self.addCleanup(server.shutdown)
            base = f"http://127.0.0.1:{server.server_port}"

            def request(path, payload=None):
                req = urllib.request.Request(base + path, data=json.dumps(payload).encode() if payload is not None else None,
                                             headers={"Content-Type": "application/json"})
                try:
                    response = urllib.request.urlopen(req, timeout=3)
                except urllib.error.HTTPError as exc:
                    response = exc
                with response:
                    return response.status, response.headers.get("Content-Type"), response.read()

            status, _, body = request("/generate", {"prompt": "synthetic HTTP contract fixture"})
            self.assertEqual(status, 202)
            job = json.loads(body)
            job_id = job["job_id"]
            self.assertEqual(request(f"/job/{job_id}")[0], 202)
            self.assertEqual(request(f"/job/{job_id}/metadata")[0], 202)
            self.assertEqual(json.loads(request("/health")[2])["executor_available"], None)
            repeated = json.loads(request("/generate", {"prompt": "synthetic HTTP contract fixture"})[2])
            self.assertEqual(repeated["job_id"], job_id)
            claim = spool.claim(job_id, owner="synthetic HTTP test executor")
            source = Path(directory) / "fixture.png"
            Image.new("RGB", (24, 24), "white").save(source)
            spool.fulfil(job_id, source, claim_token=claim["claim_token"], request_sha256=job["request_sha256"],
                         prompt_sha256=job["prompt_sha256"], tool_call_id="synthetic_test_call")
            status, mime_type, body = request(f"/job/{job_id}")
            self.assertEqual((status, mime_type, body), (200, "image/png", source.read_bytes()))
            metadata = json.loads(request(f"/job/{job_id}/metadata")[2])
            self.assertEqual(metadata["image_sha256"], sha256_bytes(body))
            Path(metadata["image_path"]).write_bytes(b"tampered")
            self.assertEqual(request(f"/job/{job_id}")[0], 500)
            self.assertEqual(request(f"/job/{job_id}/metadata")[0], 500)
            self.assertEqual(request("/generate", {"prompt": "synthetic HTTP contract fixture"})[0], 500)
            self.assertEqual(request("/generate", ["bad"])[0], 400)
            self.assertEqual(request("/job/builtin_" + "0" * 64)[0], 404)


if __name__ == "__main__":
    unittest.main()
