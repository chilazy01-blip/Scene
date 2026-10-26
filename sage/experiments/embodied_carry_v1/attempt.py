"""Run the previously frozen finite carrying attempt, without retries."""

import argparse
import os
import resource
import subprocess
import sys
import time
from pathlib import Path
from .model import authorize
from .cases import create
from .audit import audit
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


def run(main_root, model_root, preflight, output):
    admission = authorize(main_root)
    protocol_path = main_root / "carry/PROTOCOL.json"
    protocol = read_bound_json(protocol_path)
    resource.setrlimit(resource.RLIMIT_AS, (16 * 1024**3, 16 * 1024**3))
    os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:8])
    output.mkdir(parents=True, exist_ok=False)
    outcomes = []
    started = time.monotonic()

    def stage(case, directory, previous=None, short=None, ticks=100):
        for b in protocol["dependencies"].values():
            if sha256_file(Path(b["path"])) != b["sha256"]:
                raise ValueError("frozen carry dependency changed: " + b["path"])
        argv = [
            sys.executable,
            "-B",
            "-m",
            "sage.experiments.embodied_carry_v1.run",
            "--case",
            str(case),
            "--output",
            str(directory),
            "--ticks",
            str(ticks),
        ]
        if previous:
            argv += ["--admission", str(previous)]
        if short:
            argv += ["--short", str(short)]
        with directory.with_suffix(".log").open("w") as log:
            child = subprocess.run(
                argv,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=protocol["max_per_stage_wall_s"],
            )
        if not (directory / "REPORT.json").exists():
            outcomes.append(
                {
                    "stage": str(directory),
                    "engineering_failure": True,
                    "exit_code": child.returncode,
                    "log": _file_binding(directory.with_suffix(".log")),
                }
            )
            return None
        report = read_bound_json(directory / "REPORT.json")
        audited = audit(directory)
        outcomes.append(
            {
                "stage": str(directory),
                "report": _file_binding(directory / "REPORT.json"),
                "audit": _file_binding(directory / "CARRY_AUDIT.json"),
                "stop_reason": report["stop_reason"],
                "ready": report["sonic_only_physics_smoke_admission_ready"],
                "active_passed": report["active_smoke_passed"],
                "carry_passed": bool(audited["passed"]),
                "physics_steps": report["physics_steps"],
                "sonic_writes": report["sonic_candidate_actuator_writes"],
            }
        )
        print(
            directory.name,
            "ready",
            outcomes[-1]["ready"],
            "carry",
            outcomes[-1]["carry_passed"],
            "stop",
            report["stop_reason"],
            flush=True,
        )
        write_json_atomic(
            output / "PROGRESS.json",
            {"outcomes": outcomes, "elapsed_s": time.monotonic() - started},
        )
        return report

    selected = None
    succeeded = False
    error = None
    try:
        candidates = read_bound_json(preflight)["candidates"]
        for index in range(
            min(len(candidates), protocol["max_dynamic_grasp_candidates"])
        ):
            candidate_root = output / f"grasp_{index+1:02d}"
            candidate_root.mkdir()
            case = candidate_root / "CASE.json"
            create(main_root, model_root, preflight, index, "standing", case)
            shadow = stage(case, candidate_root / "admission")
            if shadow is None:
                raise RuntimeError("engineering failure; no scientific retry")
            if (
                not shadow["sonic_only_physics_smoke_admission_ready"]
                or shadow["stop_reason"] is not None
            ):
                continue
            hold = stage(
                case, candidate_root / "hold", candidate_root / "admission/REPORT.json"
            )
            if hold is None:
                raise RuntimeError("engineering failure; no scientific retry")
            if outcomes[-1]["carry_passed"]:
                selected = (index, candidate_root / "hold/REPORT.json")
                break
        if selected:
            walking = output / "walking"
            walking.mkdir()
            case = walking / "CASE.json"
            create(
                main_root,
                model_root,
                preflight,
                selected[0],
                "walking",
                case,
                selected[1],
            )
            shadow = stage(case, walking / "admission")
            if (
                shadow
                and shadow["sonic_only_physics_smoke_admission_ready"]
                and shadow["stop_reason"] is None
            ):
                short = stage(
                    case, walking / "short", walking / "admission/REPORT.json"
                )
                if (
                    short
                    and short["active_smoke_passed"]
                    and outcomes[-1]["carry_passed"]
                ):
                    full = stage(
                        case,
                        walking / "full",
                        walking / "admission/REPORT.json",
                        walking / "short/REPORT.json",
                        300,
                    )
                    succeeded = bool(full and outcomes[-1]["carry_passed"])
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    result = {
        "schema": "conditional-contact-carry-attempt/v1",
        "classification": (
            "accepted_development_carry"
            if succeeded
            else "bounded_attempt_not_accepted"
        ),
        "main_goal_admission": admission,
        "protocol": _file_binding(protocol_path),
        "implementation": _file_binding(Path(__file__)),
        "outcomes": outcomes,
        "standing_contact_hold_accepted": selected is not None,
        "walking_accepted": succeeded,
        "engineering_error": error,
        "elapsed_s": time.monotonic() - started,
        "physics_steps": sum(r.get("physics_steps", 0) for r in outcomes),
        "sonic_writes": sum(r.get("sonic_writes", 0) for r in outcomes),
        "preloaded_grasp_not_pickup": True,
        "production_accepted": False,
    }
    result["content_sha256_excluding_this_field"] = canonical_sha256(result)
    write_json_atomic(output / "RESULT.json", result)
    print(result, flush=True)
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--main-root", type=Path, required=True)
    p.add_argument("--model-root", type=Path, required=True)
    p.add_argument("--preflight", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    run(a.main_root, a.model_root, a.preflight, a.output)
