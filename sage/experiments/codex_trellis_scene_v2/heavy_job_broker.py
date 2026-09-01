"""Lease-based admission control for GPU-heavy Scene V2 jobs."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from .resource_health import sample_resource_health


def nvml_snapshot(gpu_index: int = 0) -> dict[str, Any]:
    try:
        import pynvml

        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(gpu_index)
        memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
        processes = []
        for getter in (
            pynvml.nvmlDeviceGetComputeRunningProcesses,
            pynvml.nvmlDeviceGetGraphicsRunningProcesses,
        ):
            try:
                processes.extend(int(item.pid) for item in getter(handle))
            except pynvml.NVMLError:
                pass
        result = {
            "available": True,
            "gpu_index": gpu_index,
            "name": pynvml.nvmlDeviceGetName(handle),
            "memory_total_bytes": int(memory.total),
            "memory_used_bytes": int(memory.used),
            "temperature_c": int(
                pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
            ),
            "process_pids": sorted(set(processes)),
        }
        pynvml.nvmlShutdown()
        return result
    except Exception as exc:
        return {"available": False, "gpu_index": gpu_index, "error": f"{type(exc).__name__}: {exc}"}


def cgroup_snapshot() -> dict[str, Any]:
    root = Path("/sys/fs/cgroup")
    relative = "/"
    for line in Path("/proc/self/cgroup").read_text(encoding="utf-8").splitlines():
        fields = line.split(":", 2)
        if len(fields) == 3 and fields[0] == "0":
            relative = fields[2]
            break
    directory = root / relative.lstrip("/")
    result: dict[str, Any] = {"path": relative}
    for name in ("memory.high", "memory.max", "memory.current"):
        path = directory / name
        result[name.replace(".", "_")] = path.read_text(encoding="utf-8").strip() if path.is_file() else None
    return result


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


class HeavyJobBroker:
    def __init__(
        self,
        state_path: Path,
        *,
        lease_ttl_seconds: float = 120.0,
        gpu_index: int = 0,
        resource_probe: Callable[[], dict[str, Any]] | None = None,
        gpu_probe: Callable[[], dict[str, Any]] | None = None,
        owner_pid: int | None = None,
        require_nvml: bool = True,
        require_bounded_cgroup: bool = False,
        maximum_cgroup_memory_bytes: int = 16 * 1024**3,
    ) -> None:
        if lease_ttl_seconds <= 1:
            raise ValueError("lease_ttl_seconds must exceed one second")
        self.state_path = state_path
        self.lock_path = state_path.with_suffix(state_path.suffix + ".lock")
        self.lease_ttl_seconds = float(lease_ttl_seconds)
        self.gpu_index = int(gpu_index)
        self.resource_probe = resource_probe or (lambda: sample_resource_health(sample_seconds=0.25))
        self.gpu_probe = gpu_probe or (lambda: nvml_snapshot(self.gpu_index))
        self.owner_pid = int(owner_pid or os.getpid())
        self.require_nvml = bool(require_nvml)
        self.require_bounded_cgroup = bool(require_bounded_cgroup)
        self.maximum_cgroup_memory_bytes = int(maximum_cgroup_memory_bytes)

    def _read(self) -> dict[str, Any]:
        if not self.state_path.is_file():
            return {"schema": "scene-v2-heavy-job-broker/v1", "active": None}
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {"active": None}
        except (OSError, json.JSONDecodeError):
            return {"schema": "scene-v2-heavy-job-broker/v1", "active": None}

    def _write(self, value: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.state_path.parent, delete=False) as stream:
            json.dump(value, stream, sort_keys=True)
            stream.write("\n")
            temporary = Path(stream.name)
        temporary.replace(self.state_path)

    def _locked(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.lock_path.open("a+")
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        return stream

    def acquire(self, job_id: str) -> dict[str, Any]:
        resources = self.resource_probe()
        gpu = self.gpu_probe()
        cgroup = cgroup_snapshot()
        memory_max = cgroup.get("memory_max")
        bounded = bool(
            isinstance(memory_max, str)
            and memory_max.isdigit()
            and int(memory_max) <= self.maximum_cgroup_memory_bytes
        )
        if self.require_bounded_cgroup and not bounded:
            return {"accepted": False, "status": "cgroup_limit_missing", "retryable": False, "resources": resources, "gpu": gpu, "cgroup": cgroup}
        if not bool(resources.get("healthy_for_heavy_stage")):
            return {"accepted": False, "status": "resource_busy", "retryable": True, "resources": resources, "gpu": gpu, "cgroup": cgroup}
        if self.require_nvml and not bool(gpu.get("available")):
            return {"accepted": False, "status": "gpu_probe_unavailable", "retryable": True, "resources": resources, "gpu": gpu, "cgroup": cgroup}
        foreign = [int(pid) for pid in gpu.get("process_pids", []) if int(pid) != self.owner_pid]
        if foreign:
            return {"accepted": False, "status": "external_gpu_busy", "retryable": True, "foreign_gpu_pids": foreign, "resources": resources, "gpu": gpu, "cgroup": cgroup}
        now = time.time()
        lock = self._locked()
        try:
            state = self._read()
            active = state.get("active")
            if isinstance(active, dict):
                expired = now - float(active.get("heartbeat_at", 0)) > self.lease_ttl_seconds
                dead = not pid_alive(int(active.get("owner_pid", -1)))
                if not expired and not dead:
                    return {"accepted": False, "status": "queue_full", "retryable": True, "active_job_id": active.get("job_id")}
            lease = {"job_id": str(job_id), "owner_pid": self.owner_pid, "gpu_index": self.gpu_index, "acquired_at": now, "heartbeat_at": now, "lease_ttl_seconds": self.lease_ttl_seconds}
            state = {"schema": "scene-v2-heavy-job-broker/v1", "limits": {"max_active": 1, "max_queue": 0, "lease_ttl_seconds": self.lease_ttl_seconds, "maximum_cgroup_memory_bytes": self.maximum_cgroup_memory_bytes}, "active": lease, "last_admission": {"resources": resources, "gpu": gpu, "cgroup": cgroup}}
            self._write(state)
            return {"accepted": True, "status": "acquired", "lease": lease, "resources": resources, "gpu": gpu, "cgroup": cgroup}
        finally:
            lock.close()

    def heartbeat(self, job_id: str) -> bool:
        lock = self._locked()
        try:
            state = self._read(); active = state.get("active")
            if not isinstance(active, dict) or active.get("job_id") != job_id or int(active.get("owner_pid", -1)) != self.owner_pid:
                return False
            active["heartbeat_at"] = time.time(); state["active"] = active; self._write(state); return True
        finally:
            lock.close()

    def release(self, job_id: str) -> bool:
        lock = self._locked()
        try:
            state = self._read(); active = state.get("active")
            if not isinstance(active, dict) or active.get("job_id") != job_id:
                return False
            state["active"] = None; state["released_at"] = time.time(); self._write(state); return True
        finally:
            lock.close()

    def snapshot(self) -> dict[str, Any]:
        lock = self._locked()
        try:
            return self._read()
        finally:
            lock.close()
