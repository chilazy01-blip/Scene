"""Freeze the 48-condition protocol, then run each once with durable progress."""

import argparse
import json
import os
import resource
import subprocess
import sys
import time
from pathlib import Path

from .cases import make_case
from .audit import audit
from .export import export
from sage.experiments.embodied_data_stability_v1.audit_candidates import (
    canonical_sha256,
    write_json_atomic,
    sha256_file,
)
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def freeze(root):
    output = root / "matrix_protocol_01"
    output.mkdir(exist_ok=False)
    cases = []
    for scene in ("S01r2", "S02", "S03"):
        for distance in (0.4, 0.7):
            for pose in (0, 1):
                for seed in (101, 102, 103, 104):
                    name = f"C{len(cases)+1:03d}"
                    path = output / (name + ".json")
                    make_case(root, scene, distance, pose, seed, path)
                    cases.append({"id": name, "case": _file_binding(path)})
    dependencies = [
        p for p in Path(__file__).parent.glob("*.py") if not p.name.startswith("test")
    ]
    document = {
        "schema": "generated-locomotion-matrix/v1",
        "cases": cases,
        "attempt_count": 48,
        "required_successes": 39,
        "scene_minimum_successes": 1,
        "max_retries": 0,
        "active_ticks": 300,
        "per_stage_wall_s": 120,
        "frozen_utc_timestamp": time.time(),
        "dependencies": {p.name: _file_binding(p) for p in dependencies},
        "plan": _file_binding(root / "PLAN.json"),
        "provenance": "development only; fixed planner seed, small randomized initialization; not independent held-out evaluation",
    }
    document["content_sha256_excluding_this_field"] = canonical_sha256(document)
    write_json_atomic(output / "MATRIX.json", document)
    print("frozen", len(cases), "cases")


def run(root):
    protocol = read_bound_json(root / "matrix_protocol_01/MATRIX.json")
    for binding in protocol["dependencies"].values():
        if sha256_file(Path(binding["path"])) != binding["sha256"]:
            raise ValueError("frozen matrix code changed")
    # Child processes inherit an explicit finite memory ceiling and <=8 CPUs.
    resource.setrlimit(resource.RLIMIT_AS, (16 * 1024**3, 16 * 1024**3))
    available = sorted(os.sched_getaffinity(0))
    os.sched_setaffinity(0, available[:8])
    destination = root / "matrix_run_01"
    destination.mkdir(exist_ok=False)
    began = time.monotonic()
    results = []
    for item in protocol["cases"]:
        if sha256_file(Path(item["case"]["path"])) != item["case"]["sha256"]:
            raise ValueError("case changed")
        case_root = destination / item["id"]
        case_root.mkdir()
        stage_results = []
        accepted = False
        failure = None
        start = time.monotonic()
        try:
            for stage in ("admission", "short", "full"):
                directory = case_root / stage
                argv = [
                    sys.executable,
                    "-B",
                    "-m",
                    "sage.experiments.embodied_locomotion_v1.run",
                    "--case",
                    item["case"]["path"],
                    "--output",
                    str(directory),
                ]
                if stage != "admission":
                    argv += ["--admission", str(case_root / "admission/REPORT.json")]
                if stage == "full":
                    argv += [
                        "--short",
                        str(case_root / "short/REPORT.json"),
                        "--ticks",
                        str(protocol["active_ticks"]),
                    ]
                with (case_root / (stage + ".log")).open("w") as log:
                    child = subprocess.run(
                        argv,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        timeout=protocol["per_stage_wall_s"],
                    )
                if not (directory / "REPORT.json").exists():
                    raise RuntimeError(
                        f"{stage} engineering failure, exit={child.returncode}"
                    )
                report = read_bound_json(directory / "REPORT.json")
                stage_results.append(
                    {
                        "stage": stage,
                        "report": _file_binding(directory / "REPORT.json"),
                        "physics_steps": report["physics_steps"],
                        "sonic_writes": report["sonic_candidate_actuator_writes"],
                        "wall_s": report["runtime"]["wall_seconds"],
                    }
                )
                if stage == "admission":
                    if not report["sonic_only_physics_smoke_admission_ready"]:
                        raise RuntimeError("admission rejected")
                else:
                    if not report["active_control_ticks"]:
                        raise RuntimeError("no active commands accepted")
                    checked = audit(directory)
                    write_json_atomic(directory / "AUDIT.json", checked)
                    if not checked["control_passed"]:
                        raise RuntimeError(
                            f'{stage} control rejected: {report["stop_reason"]}'
                        )
                    if stage == "full":
                        accepted = checked["task_passed"]
                        if accepted:
                            export(directory, case_root / "episode")
                        else:
                            failure = "task predicates failed"
        except Exception as exc:
            failure = f"{type(exc).__name__}: {exc}"
        result = {
            "schema": "locomotion-matrix-case-result/v1",
            "id": item["id"],
            "case": item["case"],
            "accepted": accepted,
            "failure": failure,
            "stages": stage_results,
            "wall_s": time.monotonic() - start,
        }
        result["content_sha256_excluding_this_field"] = canonical_sha256(result)
        write_json_atomic(case_root / "RESULT.json", result)
        results.append(result)
        progress = {
            "completed": len(results),
            "total": 48,
            "accepted": sum(r["accepted"] for r in results),
            "failed": sum(not r["accepted"] for r in results),
            "elapsed_s": time.monotonic() - began,
            "last_case": item["id"],
        }
        write_json_atomic(destination / "PROGRESS.json", progress)
        print(json.dumps(progress), flush=True)
    document = {
        "schema": "generated-locomotion-matrix-result/v1",
        "protocol": _file_binding(root / "matrix_protocol_01/MATRIX.json"),
        "completed": len(results),
        "accepted": sum(r["accepted"] for r in results),
        "case_results": [
            _file_binding(destination / r["id"] / "RESULT.json") for r in results
        ],
        "wall_s": time.monotonic() - began,
        "completed_utc_timestamp": time.time(),
        "production_accepted": False,
    }
    document["content_sha256_excluding_this_field"] = canonical_sha256(document)
    write_json_atomic(destination / "RESULT.json", document)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--freeze", action="store_true")
    args = parser.parse_args()
    freeze(args.root) if args.freeze else run(args.root)
