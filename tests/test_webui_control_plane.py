from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from sage.experiments.codex_trellis_scene_v2.content_chain import file_binding
from sage.webui.controller import JobController, SystemdBackend, unit_name
from sage.webui.job_store import JobStore
from sage.webui.server import DEFAULT_OUTPUT_ROOT, build_flow_plan, validate_bind_host


class FakeSystemd:
    def __init__(self) -> None:
        self.units = {}

    def launch(self, *, unit, command, cwd, stdout, stderr):
        self.units[unit] = {"LoadState": "loaded", "ActiveState": "active", "SubState": "running", "Result": "success", "ExecMainStatus": "0", "MainPID": "4242", "ControlGroup": f"/user.slice/{unit}"}
        return dict(self.units[unit])

    def show(self, unit):
        return dict(self.units.get(unit, {"LoadState": "not-found", "ActiveState": "inactive", "MainPID": "0"}))

    def stop(self, unit):
        self.units[unit].update({"ActiveState": "inactive", "Result": "success", "ExecMainStatus": "0", "MainPID": "0"})


def healthy():
    return {"healthy_for_heavy_stage": True, "reasons": []}


def idle_gpu():
    return {"available": True, "process_pids": []}


class WebUIControlPlaneTest(unittest.TestCase):
    def make_job(self, output: Path, *, strategy: str = "asset_library"):
        return {
            "id": "job-001", "status": "created", "createdAt": "2026-09-01T00:00:00Z",
            "payload": {"mode": "text_to_scene"}, "warnings": [],
            "plan": {"mode": "text_to_scene", "profile": "development", "profileKind": "diagnostic", "assetStrategy": strategy, "outputDir": str(output), "command": ["/bin/true"]},
        }

    def controller(self, root: Path, store: JobStore, backend: FakeSystemd, **kwargs):
        return JobController(store, workspace_root=root, jobs_dir=root / "logs", broker_state=root / "broker.json", backend=backend, resource_probe=kwargs.get("resource_probe", healthy), gpu_probe=kwargs.get("gpu_probe", idle_gpu))

    def test_wal_restart_reattaches_unit_and_imports_dag_attempt_artifact_and_asset_review(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "output"
            output.mkdir()
            store = JobStore(root / "jobs.sqlite3")
            with sqlite3.connect(store.path) as db:
                self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
            store.create_job(self.make_job(output))
            backend = FakeSystemd()
            first = self.controller(root, store, backend)
            running = first.start("job-001")
            self.assertEqual(running["status"], "running")
            self.assertEqual(running["systemdUnit"], unit_name("job-001"))
            self.assertEqual(running["controlGroup"], f"/user.slice/{unit_name('job-001')}")

            artifact = output / "brief.json"
            artifact.write_text("{}\n", encoding="utf-8")
            binding = file_binding(artifact)
            (output / "run_dag.json").write_text(json.dumps({
                "stage_order": ["expand"], "stages": {"expand": {"attempts": [{
                    "attempt": 1, "status": "committed", "started_at": 1.0, "completed_at": 2.0,
                    "input_key": "a" * 64, "output_key": "b" * 64, "resource_peak": {"rss": 10},
                    "outputs": {"brief": {"path": str(artifact), **binding}},
                }]}}
            }), encoding="utf-8")
            (output / "asset_resolution.json").write_text(json.dumps({"results": [{"asset_id": "chair-v1", "category": "chair", "status": "generated_for_run", "staged": str(output / "chair.glb")}]}), encoding="utf-8")

            # New Python objects simulate a WebUI process restart. Unit identity,
            # not an in-memory Popen, is sufficient to recover the running state.
            restarted_store = JobStore(root / "jobs.sqlite3")
            restarted = self.controller(root, restarted_store, backend)
            recovered = restarted.reattach_all()[0]
            self.assertEqual(recovered["status"], "running")
            self.assertEqual(recovered["stages"][0]["attempts"][0]["status"], "committed")
            self.assertEqual(recovered["artifacts"][0]["sha256"], binding["sha256"])
            self.assertEqual(recovered["assetCandidates"][0]["approval_status"], "pending")
            restarted_store.review_asset("job-001", "chair-v1", "approved", "reviewer", "four views checked")
            self.assertEqual(restarted_store.get_job("job-001")["assetCandidates"][0]["approval_status"], "approved")

            backend.units[unit_name("job-001")].update({"ActiveState": "inactive", "Result": "success", "ExecMainStatus": "0", "MainPID": "0"})
            self.assertEqual(restarted.refresh("job-001")["status"], "succeeded")

    def test_remain_after_exit_unit_recovers_success_while_server_was_down(self):
        state = {"LoadState": "loaded", "ActiveState": "active", "SubState": "exited", "Result": "success", "ExecMainStatus": "0", "MainPID": "0"}
        self.assertEqual(JobController._status_from_unit(state), ("succeeded", 0))

    def test_busy_resource_reason_is_persisted_instead_of_starting(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = JobStore(root / "jobs.sqlite3")
            store.create_job(self.make_job(root / "output", strategy="generate_from_scratch"))
            controller = self.controller(root, store, FakeSystemd(), resource_probe=lambda: {"healthy_for_heavy_stage": False, "reasons": ["mem_available_below_threshold"]})
            job = controller.start("job-001")
            self.assertEqual(job["status"], "waiting_for_resources")
            self.assertIn("mem_available_below_threshold", job["resourceGate"]["reasons"])

    def test_sqlite_launch_claim_serializes_heavy_queue(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = JobStore(root / "jobs.sqlite3")
            first = self.make_job(root / "first", strategy="generate_from_scratch")
            second = self.make_job(root / "second", strategy="generate_from_scratch")
            second["id"] = "job-002"
            store.create_job(first)
            store.create_job(second)
            self.assertEqual(store.claim_launch("job-001", heavy=True), (True, None))
            self.assertEqual(store.claim_launch("job-002", heavy=True), (False, "webui_heavy_job_active"))

    def test_missing_unit_after_restart_is_explicitly_orphaned(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = JobStore(root / "jobs.sqlite3")
            job = self.make_job(root / "output")
            job.update({"systemdUnit": unit_name("job-001"), "status": "running"})
            store.create_job(job)
            self.assertEqual(self.controller(root, store, FakeSystemd()).refresh("job-001")["status"], "orphaned")

    def test_profiles_path_allowlist_and_local_only_binding(self):
        plan = build_flow_plan({"mode": "text_to_scene", "textPrompt": "a room", "outputRoot": str(DEFAULT_OUTPUT_ROOT), "deliveryProfile": "production", "assetStrategy": "asset_library"})
        self.assertEqual(plan["profile"], "production")
        self.assertEqual(plan["profileKind"], "formal_delivery")
        self.assertIn("--profile", plan["command"])
        with self.assertRaises(ValueError):
            build_flow_plan({"mode": "text_to_scene", "textPrompt": "a room", "outputRoot": "/etc"})
        self.assertEqual(validate_bind_host("127.0.0.1"), "127.0.0.1")
        with self.assertRaises(ValueError):
            validate_bind_host("0.0.0.0")

    def test_stopping_an_already_unloaded_transient_unit_is_idempotent(self):
        completed = Mock(returncode=5, stderr="Unit example.service not loaded.", stdout="")
        with patch("sage.webui.controller.subprocess.run", return_value=completed):
            SystemdBackend().stop("example.service")


if __name__ == "__main__":
    unittest.main()
