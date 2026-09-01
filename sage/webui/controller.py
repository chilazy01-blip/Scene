"""Restart-safe systemd/cgroup controller for WebUI jobs."""

from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from sage.experiments.codex_trellis_scene_v2.heavy_job_broker import HeavyJobBroker, nvml_snapshot
from sage.experiments.codex_trellis_scene_v2.resource_health import sample_resource_health

from .job_store import JobStore, TERMINAL


def unit_name(job_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "-", job_id).strip(".-")
    if not safe:
        raise ValueError("job id cannot form a systemd unit")
    return f"scene-webui-{safe}.service"


class SystemdBackend:
    def launch(self, *, unit: str, command: list[str], cwd: Path, stdout: Path, stderr: Path) -> dict[str, Any]:
        argv = [
            "systemd-run", "--user", f"--unit={unit}", "--same-dir",
            "--property=Type=exec", "--property=MemoryHigh=24G", "--property=MemoryMax=32G",
            "--property=TasksMax=4096", "--property=RemainAfterExit=yes", f"--property=WorkingDirectory={cwd}",
            f"--property=StandardOutput=append:{stdout}", f"--property=StandardError=append:{stderr}",
            "--", *command,
        ]
        result = subprocess.run(argv, check=False, capture_output=True, text=True, timeout=20.0)
        if result.returncode != 0:
            raise RuntimeError(f"systemd-run failed: {result.stderr.strip() or result.stdout.strip()}")
        return self.show(unit)

    def show(self, unit: str) -> dict[str, Any]:
        result = subprocess.run(
            ["systemctl", "--user", "show", unit, "--property=LoadState,ActiveState,SubState,Result,ExecMainStatus,MainPID,ControlGroup"],
            check=False, capture_output=True, text=True, timeout=10.0,
        )
        fields: dict[str, str] = {}
        for line in result.stdout.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                fields[key] = value
        fields["query_returncode"] = str(result.returncode)
        return fields

    def stop(self, unit: str) -> None:
        result = subprocess.run(["systemctl", "--user", "stop", unit], check=False, capture_output=True, text=True, timeout=20.0)
        missing = "not loaded" in result.stderr.lower() or "not found" in result.stderr.lower()
        if result.returncode != 0 and not missing:
            raise RuntimeError(f"systemctl stop failed: {result.stderr.strip()}")


class JobController:
    def __init__(
        self,
        store: JobStore,
        *,
        workspace_root: Path,
        jobs_dir: Path,
        broker_state: Path,
        backend: SystemdBackend | None = None,
        resource_probe: Callable[[], dict[str, Any]] | None = None,
        gpu_probe: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self.store = store
        self.workspace_root = workspace_root.resolve()
        self.jobs_dir = jobs_dir.resolve()
        self.backend = backend or SystemdBackend()
        self.resource_probe = resource_probe or (lambda: sample_resource_health(sample_seconds=0.1))
        self.gpu_probe = gpu_probe or (lambda: nvml_snapshot(0))
        self.broker = HeavyJobBroker(broker_state, require_nvml=False)

    def resource_gate(self, plan: dict[str, Any]) -> dict[str, Any]:
        resources = self.resource_probe()
        gpu = self.gpu_probe()
        broker = self.broker.snapshot()
        heavy = str(plan.get("assetStrategy")) == "generate_from_scratch" and str(plan.get("profile")) != "plan"
        reasons = list(resources.get("reasons", []))
        active = broker.get("active")
        if heavy and isinstance(active, dict):
            reasons.append("heavy_broker_lease_active")
        if heavy and not bool(gpu.get("available")):
            reasons.append("gpu_probe_unavailable")
        if heavy and gpu.get("process_pids"):
            reasons.append("external_gpu_busy")
        return {
            "schema": "scene-webui-resource-gate/v1", "heavy": heavy,
            "accepted": not reasons, "reasons": sorted(set(reasons)),
            "resources": resources, "gpu": gpu, "broker": broker,
        }

    def start(self, job_id: str) -> dict[str, Any]:
        job = self.store.get_job(job_id)
        if not job:
            raise KeyError(job_id)
        if job["status"] in TERMINAL:
            raise ValueError(f"cannot start terminal job: {job['status']}")
        if job["status"] not in {"created", "queued", "waiting_for_resources"}:
            raise ValueError(f"job is not queued for launch: {job['status']}")
        command = job.get("plan", {}).get("command")
        if not isinstance(command, list) or not command or any(str(part).startswith("<") for part in command):
            self.store.update_job(job_id, status="blocked", warnings=[*job.get("warnings", []), "Runnable command is incomplete."])
            return self.store.get_job(job_id) or {}
        gate = self.resource_gate(job["plan"])
        self.store.update_job(job_id, resourceGate=gate)
        if not gate["accepted"]:
            self.store.update_job(job_id, status="waiting_for_resources")
            return self.store.get_job(job_id) or {}
        claimed, reason = self.store.claim_launch(job_id, heavy=bool(gate["heavy"]))
        if not claimed:
            gate["accepted"] = False
            gate["reasons"] = sorted(set([*gate["reasons"], str(reason)]))
            self.store.update_job(job_id, status="waiting_for_resources", resourceGate=gate)
            return self.store.get_job(job_id) or {}
        log_dir = self.jobs_dir / job_id
        log_dir.mkdir(parents=True, exist_ok=True)
        stdout = log_dir / "stdout.log"
        stderr = log_dir / "stderr.log"
        stdout.touch(exist_ok=True)
        stderr.touch(exist_ok=True)
        unit = unit_name(job_id)
        try:
            state = self.backend.launch(unit=unit, command=[str(part) for part in command], cwd=self.workspace_root, stdout=stdout, stderr=stderr)
        except Exception as exc:
            self.store.update_job(job_id, status="failed", finishedAt=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), warnings=[*job.get("warnings", []), f"systemd launch failed: {type(exc).__name__}: {exc}"])
            raise
        pid = int(state.get("MainPID") or 0) or None
        self.store.record_log(job_id, "stdout", stdout)
        self.store.record_log(job_id, "stderr", stderr)
        self.store.update_job(job_id, status="running", systemdUnit=unit, controlGroup=state.get("ControlGroup"), pid=pid, startedAt=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        return self.store.get_job(job_id) or {}

    @staticmethod
    def _status_from_unit(state: dict[str, Any]) -> tuple[str, int | None]:
        load = state.get("LoadState")
        active = state.get("ActiveState")
        result = state.get("Result")
        code = int(state.get("ExecMainStatus") or 0)
        if load == "not-found":
            return "orphaned", None
        if active == "active" and state.get("SubState") == "exited":
            return ("succeeded", code) if result in {"", "success", None} and code == 0 else ("failed", code)
        if active in {"active", "activating", "reloading"}:
            return "running", None
        if active == "failed" or result not in {"", "success", None} or code != 0:
            return "failed", code
        if active in {"inactive", "deactivating"}:
            return "succeeded", code
        return "reattaching", None

    def refresh(self, job_id: str) -> dict[str, Any]:
        job = self.store.get_job(job_id)
        if not job:
            raise KeyError(job_id)
        if job["status"] == "waiting_for_resources" and not job.get("systemdUnit"):
            return self.start(job_id)
        unit = job.get("systemdUnit")
        if unit and job["status"] not in TERMINAL:
            state = self.backend.show(str(unit))
            status, code = self._status_from_unit(state)
            update: dict[str, Any] = {"status": status, "controlGroup": state.get("ControlGroup"), "pid": int(state.get("MainPID") or 0) or None}
            if status in TERMINAL:
                update["finishedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                update["returnCode"] = code
            self.store.update_job(job_id, **update)
        self.store.sync_v2_output(job_id)
        current = self.store.get_job(job_id) or {}
        for stream, path in current.get("logs", {}).items():
            self.store.record_log(job_id, stream, Path(path))
        return self.store.get_job(job_id) or {}

    def reattach_all(self) -> list[dict[str, Any]]:
        return [self.refresh(job["id"]) for job in self.store.list_jobs() if job["status"] not in TERMINAL]

    def cancel(self, job_id: str) -> dict[str, Any]:
        job = self.store.get_job(job_id)
        if not job:
            raise KeyError(job_id)
        if job.get("systemdUnit"):
            self.backend.stop(str(job["systemdUnit"]))
        elif job.get("pid"):
            os.kill(int(job["pid"]), 15)
        self.store.update_job(job_id, status="cancelled", finishedAt=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        return self.store.get_job(job_id) or {}
