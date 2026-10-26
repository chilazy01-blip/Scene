"""Progressively extend the exact continuous task, preserving every rejection."""

import argparse
import os
from pathlib import Path
import resource
import subprocess
import sys
import time
from .engine import authorize
from .audit import audit
from sage.experiments.embodied_data_stability_v1.audit_candidates import (
    canonical_sha256,
    write_json_atomic,
)
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def run(root):
    protocol = authorize(root)
    output = root / "attempt_01"
    output.mkdir(exist_ok=False)
    resource.setrlimit(resource.RLIMIT_AS, (16 * 1024**3, 16 * 1024**3))
    os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:8])
    began = time.monotonic()
    outcomes = []
    previous = None
    success = False
    error = None
    try:
        for ticks in (0, *protocol["active_budgets_ticks"]):
            directory = output / ("admission" if ticks == 0 else f"active_{ticks:04d}")
            argv = [
                sys.executable,
                "-B",
                "-m",
                "sage.experiments.embodied_transport_v1.engine",
                "--root",
                str(root),
                "--output",
                str(directory),
                "--ticks",
                str(ticks or 100),
            ]
            if ticks:
                argv += ["--admission", str(output / "admission/REPORT.json")]
            if ticks > 100:
                argv += ["--previous", str(previous)]
            with directory.with_suffix(".log").open("w") as log:
                child = subprocess.run(
                    argv,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=protocol["per_process_wall_s"],
                )
            if not (directory / "REPORT.json").exists():
                raise RuntimeError(
                    f"engineering failure exit={child.returncode}, inspect {directory.with_suffix('.log')}"
                )
            report = read_bound_json(directory / "REPORT.json")
            independent = audit(directory)
            outcomes.append(
                {
                    "stage": directory.name,
                    "report": _file_binding(directory / "REPORT.json"),
                    "audit": _file_binding(directory / "AUDIT.json"),
                    "control_passed": independent["control_passed"],
                    "task_passed": independent["task_passed"],
                    "final_stage": report["final_stage"],
                    "stop_reason": report["stop_reason"],
                    "physics_steps": report["physics_steps"],
                }
            )
            write_json_atomic(
                output / "PROGRESS.json",
                {"outcomes": outcomes, "elapsed_s": time.monotonic() - began},
            )
            print(outcomes[-1], flush=True)
            if not independent["control_passed"]:
                break
            if ticks:
                previous = directory / "REPORT.json"
            if independent["task_passed"]:
                success = True
                break
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    result = {
        "schema": "continuous-transport-attempt/v1",
        "task_passed": success,
        "error": error,
        "outcomes": outcomes,
        "protocol": _file_binding(root / "PROTOCOL.json"),
        "elapsed_s": time.monotonic() - began,
        "physics_steps": sum(x["physics_steps"] for x in outcomes),
        "implementation": _file_binding(Path(__file__)),
    }
    result["content_sha256_excluding_this_field"] = canonical_sha256(result)
    write_json_atomic(output / "RESULT.json", result)
    print(result, flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    run(p.parse_args().root)
