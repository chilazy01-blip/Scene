"""Explicit shared-GPU admission and a separate, pidfd-bound process watchdog.

No model imports, allocations, process-list filtering, or machine-wide kills.
The legacy exclusive broker remains unchanged. Only the explicit shared entry
uses this policy; its state file must be the same lease used by other workers.
"""

from __future__ import annotations

import json
import ctypes
import math
import multiprocessing
import os
import platform
import queue
import select
import signal
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from .heavy_job_broker import HeavyJobBroker, cgroup_snapshot, pid_alive
from .resource_health import sample_resource_health

GIB = 1024**3
SCHEMA = "scene-v2-shared-gpu-execution/v1"


def _pidfd_syscall(number: int, *args: Any) -> int:
    # Older Conda builds omit os.pidfd_open and use a libc without its wrapper.
    # Linux x86_64/aarch64 UAPI uses 434=open and 424=send_signal. Fail closed
    # on other architectures; never fall back to signalling a numeric PID.
    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "aarch64"}:
        raise RuntimeError("this platform lacks a supported pidfd interface")
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    result = int(libc.syscall(ctypes.c_long(number), *args))
    if result < 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    return result


def _pidfd_open(pid: int) -> int:
    if hasattr(os, "pidfd_open"):
        return os.pidfd_open(pid)
    return _pidfd_syscall(434, ctypes.c_int(pid), ctypes.c_uint(0))


def _pidfd_signal(pidfd: int, signum: int) -> None:
    if hasattr(signal, "pidfd_send_signal"):
        signal.pidfd_send_signal(pidfd, signum)
    else:
        _pidfd_syscall(424, ctypes.c_int(pidfd), ctypes.c_int(signum), ctypes.c_void_p(), ctypes.c_uint(0))


@dataclass(frozen=True)
class SharedGpuPolicy:
    required_peak_gib: float = 20.0
    gpu_reserve_gib: float = 4.0
    stable_samples: int = 3
    sample_interval_seconds: float = 1.0
    maximum_free_variation_gib: float = 1.0
    minimum_start_mem_available_gib: float = 96.0
    minimum_running_mem_available_gib: float = 24.0
    maximum_running_cgroup_fraction: float = 0.92
    sustained_io_samples: int = 3
    probe_timeout_seconds: float = 0.9
    max_runtime_seconds: float = 21600.0

    def __post_init__(self) -> None:
        numeric = asdict(self)
        if any(not math.isfinite(float(value)) or float(value) <= 0 for value in numeric.values()):
            raise ValueError("shared GPU policy values must be positive and finite")
        if self.stable_samples < 3 or int(self.stable_samples) != self.stable_samples:
            raise ValueError("at least three stable admission samples are required")
        if self.minimum_start_mem_available_gib < 96:
            raise ValueError("the P007 96 GiB startup memory gate cannot be lowered")
        if self.gpu_reserve_gib < 4 or self.sample_interval_seconds > 1:
            raise ValueError("shared execution requires >=4 GiB reserve and <=1 second polling")
        if self.probe_timeout_seconds > self.sample_interval_seconds:
            raise ValueError("probe deadline must fit inside the sampling interval")
        if not 0 < self.maximum_running_cgroup_fraction <= 0.92:
            raise ValueError("cgroup stop fraction must be in (0, 0.92]")


def append_evidence(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"schema": SCHEMA, "at": time.time(), **report}, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def gpu_inventory() -> list[dict[str, Any]]:
    """Read required driver fields directly, including compute and graphics.

    Full nvidia-smi XML queries caused actual 0.7s subprocess timeouts on the
    shared host. Direct NVML keeps the existing outer 0.9s telemetry deadline
    and all resource thresholds; unavailable telemetry still fails closed.
    """
    from .gpu_nvml import inventory
    return inventory()


def parse_gpu_inventory(xml: str) -> list[dict[str, Any]]:
    def memory(text: str | None) -> int:
        value, unit = str(text).split()
        if unit not in {"MiB", "GiB"}:
            raise ValueError("invalid GPU memory telemetry unit")
        return int(float(value) * (1024**2 if unit == "MiB" else GIB))

    rows = []
    for index, item in enumerate(ET.fromstring(xml).findall("gpu")):
        processes = item.find("processes")
        if processes is None or (processes.text or "").strip() in {"N/A", "Not Supported"}:
            raise ValueError("GPU process telemetry is missing")
        raw_processes = [{child.tag: child.text for child in process} for process in processes.findall("process_info")]
        rows.append({
            "available": True, "provider": "nvidia-smi-xml", "gpu_index": index,
            "uuid": item.findtext("uuid"), "name": item.findtext("product_name"),
            "memory_total_bytes": memory(item.findtext("fb_memory_usage/total")),
            "memory_used_bytes": memory(item.findtext("fb_memory_usage/used")),
            "memory_free_bytes": memory(item.findtext("fb_memory_usage/free")),
            "process_pids": sorted({int(process["pid"]) for process in raw_processes}),
            "processes": raw_processes,
        })
    if not rows:
        raise RuntimeError("GPU inventory is empty")
    return rows


def process_identity(pid: int) -> dict[str, Any]:
    root = Path("/proc") / str(pid)
    stat = (root / "stat").read_text()
    # comm may contain spaces or parentheses. Field 22 is index 19 after comm.
    fields = stat[stat.rfind(")") + 2:].split()
    return {
        "pid": int(pid), "start_ticks": int(fields[19]), "uid": root.stat().st_uid,
        "cgroup": (root / "cgroup").read_text(), "state": fields[0],
    }


def same_process(expected: dict[str, Any]) -> bool:
    try:
        current = process_identity(int(expected["pid"]))
        return all(current[key] == expected[key] for key in ("pid", "start_ticks", "uid", "cgroup")) and current["state"] != "Z"
    except (OSError, ValueError, KeyError):
        return False


def _free_gib(gpu: dict[str, Any]) -> float:
    if not gpu.get("available"):
        raise ValueError("GPU telemetry unavailable")
    total, used = int(gpu["memory_total_bytes"]), int(gpu["memory_used_bytes"])
    if not 0 <= used <= total or total <= 0 or not gpu.get("uuid"):
        raise ValueError("GPU memory/identity telemetry invalid")
    free = int(gpu.get("memory_free_bytes", total - used))
    if not 0 <= free <= total:
        raise ValueError("invalid GPU free-memory telemetry")
    return free / GIB


def gpu_budget(gpu: dict[str, Any], policy: SharedGpuPolicy, *, owner_identity: dict[str, Any] | None = None, pinned_gpu_uuid: str | None = None) -> dict[str, Any]:
    """Credit only driver-proven resident bytes of this exact owner on its GPU.

    The full peak includes the owner's already-resident models. Actual free
    telemetry is never changed, and unrelated processes contribute no credit.
    Missing, ambiguous, stale, or invalid owner evidence uses the cold budget.
    """
    resident = 0.0
    status = "cold_or_unverified_owner"
    if owner_identity and gpu.get("uuid") == pinned_gpu_uuid and same_process(owner_identity):
        try:
            pid = int(owner_identity["pid"])
            rows = [row for row in gpu.get("processes", []) if str(row.get("pid")) == str(pid)]
            if len(rows) != 1 or pid not in gpu.get("process_pids", []):
                raise ValueError("owner process memory is missing or ambiguous")
            value, unit = str(rows[0]["used_memory"]).split()
            amount = float(value)
            if not math.isfinite(amount) or amount < 0 or unit not in {"MiB", "GiB"}:
                raise ValueError("invalid owner process memory")
            resident = amount / 1024 if unit == "MiB" else amount
            if resident * GIB > int(gpu["memory_used_bytes"]):
                raise ValueError("owner process memory exceeds device usage")
            status = "verified_same_owner_same_gpu"
        except (KeyError, TypeError, ValueError):
            resident = 0.0
            status = "owner_memory_unavailable_conservative_cold_budget"
    free = _free_gib(gpu)
    incremental = max(0.0, policy.required_peak_gib - resident)
    return {"actual_free_gib": free, "required_peak_gib": policy.required_peak_gib, "verified_own_resident_gib": resident, "incremental_peak_needed_gib": incremental, "reserve_gib": policy.gpu_reserve_gib, "required_free_gib": incremental + policy.gpu_reserve_gib, "capacity_sufficient": free >= incremental + policy.gpu_reserve_gib, "own_memory_credit_status": status}


def _cgroup_limit(cgroup: dict[str, Any], maximum_bytes: int) -> tuple[int, int]:
    maximum, current = int(cgroup["memory_max"]), int(cgroup["memory_current"])
    if not 0 < maximum <= maximum_bytes or current < 0 or not cgroup.get("path"):
        raise ValueError("bounded cgroup limit missing or invalid")
    return maximum, current


def _sample(inventory_probe, resource_probe, cgroup_probe, timeout: float) -> dict[str, Any]:
    """Bound a stalled native/driver probe without depending on the worker GIL."""
    result: queue.Queue = queue.Queue(maxsize=1)
    started = time.monotonic()

    def probe() -> None:
        try:
            result.put({"gpus": inventory_probe(), "resources": resource_probe(), "cgroup": cgroup_probe()})
        except Exception as exc:
            result.put({"error": f"{type(exc).__name__}: {exc}"})

    threading.Thread(target=probe, daemon=True).start()
    try:
        sample = result.get(timeout=timeout)
    except queue.Empty:
        sample = {"error": "telemetry_deadline_exceeded"}
    return {"sampled_at": time.time(), "elapsed_seconds": time.monotonic() - started, **sample}


def select_shared_gpu(
    policy: SharedGpuPolicy, *, maximum_cgroup_memory_bytes: int,
    inventory_probe: Callable = gpu_inventory,
    resource_probe: Callable = lambda: sample_resource_health(sample_seconds=0.25),
    cgroup_probe: Callable = cgroup_snapshot,
    sleep: Callable = time.sleep,
    owner_identity: dict[str, Any] | None = None,
    pinned_gpu_uuid: str | None = None,
) -> dict[str, Any]:
    """Rank GPUs by their minimum free memory over three stable healthy samples."""
    samples: list[dict[str, Any]] = []
    candidates: dict[str, list[dict[str, Any]]] = {}
    for index in range(policy.stable_samples):
        if index:
            sleep(policy.sample_interval_seconds)
        sample = _sample(inventory_probe, resource_probe, cgroup_probe, policy.probe_timeout_seconds)
        samples.append(sample)
        try:
            if sample.get("error"):
                raise ValueError(sample["error"])
            maximum, current = _cgroup_limit(sample["cgroup"], maximum_cgroup_memory_bytes)
            if current >= maximum * policy.maximum_running_cgroup_fraction:
                return {"accepted": False, "status": "cgroup_memory_near_max", "retryable": True, "samples": samples}
            resources = sample["resources"]
            available = float(resources["metrics"]["mem_available_gib"])
            if not math.isfinite(available):
                raise ValueError("invalid host memory telemetry")
            if not resources.get("healthy_for_heavy_stage") or available < policy.minimum_start_mem_available_gib:
                return {"accepted": False, "status": "resource_busy", "retryable": True, "samples": samples}
            seen = set()
            sample["gpu_budgets"] = {}
            for gpu in sample["gpus"]:
                _free_gib(gpu)
                uuid = gpu["uuid"]
                if uuid in seen:
                    raise ValueError("duplicate GPU identity")
                seen.add(uuid)
                candidates.setdefault(uuid, []).append(gpu)
                sample["gpu_budgets"][uuid] = gpu_budget(gpu, policy, owner_identity=owner_identity, pinned_gpu_uuid=pinned_gpu_uuid)
        except (ValueError, TypeError, KeyError) as exc:
            return {"accepted": False, "status": "telemetry_or_cgroup_unavailable", "retryable": True, "error": str(exc), "samples": samples}
    eligible = []
    for uuid, rows in candidates.items():
        free = [_free_gib(row) for row in rows]
        budgets = [sample["gpu_budgets"].get(uuid, {}) for sample in samples]
        if len(rows) == policy.stable_samples and len({row["gpu_index"] for row in rows}) == 1 and all(budget.get("capacity_sufficient") for budget in budgets) and max(free) - min(free) <= policy.maximum_free_variation_gib:
            eligible.append((min(free), uuid, rows[-1]))
    if not eligible:
        return {"accepted": False, "status": "no_stable_gpu_capacity", "retryable": True, "samples": samples}
    minimum_free, _, selected = max(eligible, key=lambda item: (item[0], -int(item[2]["gpu_index"])))
    return {"accepted": True, "status": "shared_gpu_selected", "gpu": selected, "minimum_free_gib": minimum_free, "policy": asdict(policy), "samples": samples}


class SharedGpuBroker(HeavyJobBroker):
    """Use the existing lease lock/storage with an explicit shared admission path."""

    def __init__(self, state_path: Path, *, policy: SharedGpuPolicy, selected_gpu: dict[str, Any], evidence_path: Path, inventory_probe: Callable = gpu_inventory, cgroup_probe: Callable = cgroup_snapshot, sleep: Callable = time.sleep, **kwargs) -> None:
        super().__init__(state_path, gpu_index=int(selected_gpu["gpu_index"]), require_nvml=True, require_bounded_cgroup=True, **kwargs)
        self.policy, self.selected_gpu, self.evidence_path = policy, selected_gpu, evidence_path
        self.inventory_probe, self.cgroup_probe, self.sleep = inventory_probe, cgroup_probe, sleep
        self.identity = process_identity(self.owner_pid)

    def acquire(self, job_id: str) -> dict[str, Any]:
        lock = self._locked()
        try:
            state = self._read()
            active = state.get("active")
            if isinstance(active, dict):
                identity = active.get("owner_identity")
                alive = same_process(identity) if identity else pid_alive(int(active.get("owner_pid", -1)))
                # Never steal from a live job merely because a heartbeat was late.
                if alive:
                    return {"accepted": False, "status": "queue_full", "retryable": True, "active_job_id": active.get("job_id")}
            admission = select_shared_gpu(self.policy, maximum_cgroup_memory_bytes=self.maximum_cgroup_memory_bytes, inventory_probe=self.inventory_probe, resource_probe=self.resource_probe, cgroup_probe=self.cgroup_probe, sleep=self.sleep, owner_identity=self.identity, pinned_gpu_uuid=self.selected_gpu["uuid"])
            if admission.get("accepted"):
                pinned = self.selected_gpu["uuid"]
                rows = [next((row for row in sample["gpus"] if row["uuid"] == pinned), None) for sample in admission["samples"]]
                free = [_free_gib(row) for row in rows if row is not None]
                budgets = [sample["gpu_budgets"].get(pinned, {}) for sample in admission["samples"]]
                if len(free) != self.policy.stable_samples or any(row["gpu_index"] != self.gpu_index for row in rows if row is not None) or not all(budget.get("capacity_sufficient") for budget in budgets) or max(free) - min(free) > self.policy.maximum_free_variation_gib:
                    admission.update(accepted=False, status="pinned_gpu_capacity_changed", retryable=True)
                else:
                    admission["best_gpu_at_recheck"] = admission["gpu"]
                    admission["gpu"] = rows[-1]
                    admission["minimum_free_gib"] = min(free)
                    admission["pinned_gpu_budgets"] = budgets
                    now = time.time()
                    lease = {"job_id": str(job_id), "owner_pid": self.owner_pid, "owner_identity": self.identity, "gpu_index": self.gpu_index, "gpu_uuid": pinned, "acquired_at": now, "heartbeat_at": now, "lease_ttl_seconds": self.lease_ttl_seconds, "admission_mode": "explicit_shared_gpu"}
                    self._write({"schema": "scene-v2-heavy-job-broker/v1", "active": lease, "limits": {"max_active": 1, "max_queue": 0, "maximum_cgroup_memory_bytes": self.maximum_cgroup_memory_bytes}, "shared_gpu_policy": asdict(self.policy), "last_admission": admission})
                    admission.update(status="acquired", lease=lease)
            append_evidence(self.evidence_path, {"event": "job_admission", "job_id": job_id, "admission": admission})
            return admission
        finally:
            lock.close()

    def release(self, job_id: str) -> bool:
        lock = self._locked()
        try:
            state = self._read()
            active = state.get("active")
            if not isinstance(active, dict) or active.get("job_id") != job_id or active.get("owner_identity") != self.identity:
                return False
            state.update(active=None, released_at=time.time())
            self._write(state)
            return True
        finally:
            lock.close()


def running_stop_reasons(sample: dict[str, Any], *, policy: SharedGpuPolicy, selected_gpu: dict[str, Any], maximum_cgroup_memory_bytes: int) -> tuple[list[str], bool]:
    """Return immediate stop reasons and a separate transient I/O pressure flag."""
    reasons: list[str] = []
    try:
        if sample.get("error"):
            return [str(sample["error"])], False
        gpu = next(row for row in sample["gpus"] if row["uuid"] == selected_gpu["uuid"])
        if _free_gib(gpu) < policy.gpu_reserve_gib:
            reasons.append("gpu_free_below_reserve")
        maximum, current = _cgroup_limit(sample["cgroup"], maximum_cgroup_memory_bytes)
        if current >= maximum * policy.maximum_running_cgroup_fraction:
            reasons.append("cgroup_memory_near_max")
        metrics = sample["resources"]["metrics"]
        available = float(metrics["mem_available_gib"])
        if not math.isfinite(available):
            raise ValueError("invalid host memory telemetry")
        if available < policy.minimum_running_mem_available_gib:
            reasons.append("host_memory_below_running_floor")
        io_pressure = any(reason in sample["resources"].get("reasons", []) for reason in ("dirty_writeback_above_threshold", "blocked_processes_above_threshold", "iowait_above_threshold"))
        storage = [float(metrics[key]) for key in ("data_free_gib", "tmp_free_gib")]
        if any(not math.isfinite(value) or value < 0 for value in storage):
            raise ValueError("invalid storage telemetry")
        if storage[0] < 100 or storage[1] < 20:
            reasons.append("storage_free_below_threshold")
        return reasons, io_pressure
    except (ValueError, TypeError, KeyError, StopIteration):
        return ["telemetry_or_cgroup_unavailable"], False


def run_watchdog(config: dict[str, Any], stop_event: Any, ready_event: Any, *, inventory_probe: Callable = gpu_inventory, resource_probe: Callable = lambda: sample_resource_health(sample_seconds=0.25), cgroup_probe: Callable = cgroup_snapshot) -> None:
    """Separate process; signal only the identity-bound bridge through its pidfd."""
    policy = SharedGpuPolicy(**config["policy"])
    identity, evidence = config["owner_identity"], Path(config["evidence_path"])
    pidfd = _pidfd_open(int(identity["pid"]))
    try:
        if not same_process(identity):
            append_evidence(evidence, {"event": "binding_rejected", "owner_identity": identity})
            return
        ready_event.set()
        started = time.monotonic()
        io_streak = 0
        while not stop_event.is_set():
            tick = time.monotonic()
            if not same_process(identity):
                append_evidence(evidence, {"event": "owner_exited_or_identity_changed", "owner_identity": identity})
                return
            sample = _sample(inventory_probe, resource_probe, cgroup_probe, policy.probe_timeout_seconds)
            reasons, io_pressure = running_stop_reasons(sample, policy=policy, selected_gpu=config["selected_gpu"], maximum_cgroup_memory_bytes=int(config["maximum_cgroup_memory_bytes"]))
            io_streak = io_streak + 1 if io_pressure else 0
            if io_streak >= policy.sustained_io_samples:
                reasons.append("sustained_io_pressure")
            if time.monotonic() - started >= policy.max_runtime_seconds:
                reasons.append("bounded_runtime_exhausted")
            record = {"event": "stop_requested" if reasons else "watchdog_sample", "owner_identity": identity, "sample": sample, "reasons": reasons, "io_streak": io_streak}
            if reasons and config.get("lease_path"):
                try:
                    record["active_lease"] = json.loads(Path(config["lease_path"]).read_text()).get("active")
                except (OSError, ValueError):
                    record["active_lease_unavailable"] = True
                record["job_store_root"] = config.get("job_store_root")
            append_evidence(evidence, record)
            if reasons:
                # pidfd closes the check-to-signal PID reuse race. No killpg,
                # cgroup.kill, systemctl glob, or GPU process-list signalling.
                if same_process(identity):
                    _pidfd_signal(pidfd, signal.SIGTERM)
                    if not select.select([pidfd], [], [], 0.5)[0] and same_process(identity):
                        _pidfd_signal(pidfd, signal.SIGKILL)
                return
            stop_event.wait(max(0, policy.sample_interval_seconds - (time.monotonic() - tick)))
    finally:
        os.close(pidfd)


def start_watchdog(config: dict[str, Any]):
    context = multiprocessing.get_context("spawn")
    stop_event, ready_event = context.Event(), context.Event()
    process = context.Process(target=run_watchdog, args=(config, stop_event, ready_event), daemon=True, name="shared-gpu-watchdog")
    process.start()
    if not ready_event.wait(5) or not process.is_alive():
        stop_event.set()
        process.join(timeout=1)
        raise RuntimeError("shared GPU watchdog failed to bind; refusing to serve")

    def supervise_monitor() -> None:
        process.join()
        if not stop_event.is_set() and same_process(config["owner_identity"]):
            # This is unconditionally our own process, never an external GPU PID.
            os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=supervise_monitor, daemon=True).start()
    return process, stop_event
