from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RESOURCE_HEALTH_SCHEMA = "codex_trellis_resource_health_v1"


@dataclass(frozen=True)
class ResourceHealthThresholds:
    minimum_mem_available_gib: float = 96.0
    maximum_dirty_writeback_gib: float = 4.0
    maximum_blocked_processes: int = 16
    maximum_iowait_fraction: float = 0.35
    minimum_data_free_gib: float = 100.0
    minimum_tmp_free_gib: float = 20.0


def _meminfo() -> dict[str, int]:
    values: dict[str, int] = {}
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        key, raw = line.split(":", 1)
        token = raw.strip().split()[0]
        values[key] = int(token) * 1024
    return values


def _proc_stat() -> tuple[list[int], int]:
    cpu: list[int] = []
    blocked = 0
    for line in Path("/proc/stat").read_text(encoding="utf-8").splitlines():
        if line.startswith("cpu "):
            cpu = [int(value) for value in line.split()[1:]]
        elif line.startswith("procs_blocked "):
            blocked = int(line.split()[1])
    if len(cpu) < 5:
        raise RuntimeError("/proc/stat does not expose CPU accounting")
    return cpu, blocked


def _gib(value: int | float) -> float:
    return float(value) / (1024.0**3)


def sample_resource_health(
    *,
    sample_seconds: float = 1.0,
    data_path: Path = Path("/data"),
    tmp_path: Path = Path("/tmp"),
    thresholds: ResourceHealthThresholds | None = None,
) -> dict[str, Any]:
    thresholds = thresholds or ResourceHealthThresholds()
    if sample_seconds <= 0.0 or sample_seconds > 10.0:
        raise ValueError("sample_seconds must be in (0, 10]")
    first_cpu, first_blocked = _proc_stat()
    time.sleep(sample_seconds)
    second_cpu, second_blocked = _proc_stat()
    count = min(len(first_cpu), len(second_cpu))
    deltas = [max(0, second_cpu[index] - first_cpu[index]) for index in range(count)]
    total_delta = max(sum(deltas), 1)
    # Linux aggregate CPU fields: user, nice, system, idle, iowait, ...
    iowait_fraction = float(deltas[4] / total_delta)

    memory = _meminfo()
    data_usage = shutil.disk_usage(data_path)
    tmp_usage = shutil.disk_usage(tmp_path)
    load = os.getloadavg()
    cpu_count = max(int(os.cpu_count() or 1), 1)
    dirty_writeback = int(memory.get("Dirty", 0)) + int(memory.get("Writeback", 0))
    metrics = {
        "mem_available_gib": _gib(memory.get("MemAvailable", 0)),
        "swap_free_gib": _gib(memory.get("SwapFree", 0)),
        "dirty_writeback_gib": _gib(dirty_writeback),
        "load_average": [float(value) for value in load],
        "logical_cpu_count": cpu_count,
        "load_1m_per_cpu": float(load[0] / cpu_count),
        "blocked_processes_before": first_blocked,
        "blocked_processes_after": second_blocked,
        "iowait_fraction": iowait_fraction,
        "data_free_gib": _gib(data_usage.free),
        "tmp_free_gib": _gib(tmp_usage.free),
    }
    reasons: list[str] = []
    if metrics["mem_available_gib"] < thresholds.minimum_mem_available_gib:
        reasons.append("mem_available_below_threshold")
    if metrics["dirty_writeback_gib"] > thresholds.maximum_dirty_writeback_gib:
        reasons.append("dirty_writeback_above_threshold")
    if max(first_blocked, second_blocked) > thresholds.maximum_blocked_processes:
        reasons.append("blocked_processes_above_threshold")
    if iowait_fraction > thresholds.maximum_iowait_fraction:
        reasons.append("iowait_above_threshold")
    if metrics["data_free_gib"] < thresholds.minimum_data_free_gib:
        reasons.append("data_free_below_threshold")
    if metrics["tmp_free_gib"] < thresholds.minimum_tmp_free_gib:
        reasons.append("tmp_free_below_threshold")
    return {
        "schema": RESOURCE_HEALTH_SCHEMA,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "sample_seconds": float(sample_seconds),
        "healthy_for_heavy_stage": not reasons,
        "reasons": reasons,
        "thresholds": asdict(thresholds),
        "metrics": metrics,
    }


def append_health_checkpoint(
    path: Path,
    *,
    stage: str,
    require_healthy: bool = False,
    thresholds: ResourceHealthThresholds | None = None,
) -> dict[str, Any]:
    report = sample_resource_health(thresholds=thresholds)
    report["stage"] = str(stage)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    if require_healthy and not report["healthy_for_heavy_stage"]:
        raise RuntimeError(
            "resource health gate rejected heavy stage: "
            + ", ".join(report["reasons"])
        )
    return report
