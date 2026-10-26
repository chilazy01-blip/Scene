"""Execute one frozen ordered development condition; stop at the first rejection."""

import argparse
import os
from pathlib import Path
import resource
import subprocess
import sys
import time
from .protocol import authorize
from .cases import create
from .audit_corrected import audit
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
    protocol_binding = authorize(root)
    protocol = read_bound_json(root / "PROTOCOL.json")
    resource.setrlimit(resource.RLIMIT_AS, (16 * 1024**3, 16 * 1024**3))
    os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:8])
    output = root / "continuation_01"
    output.mkdir(exist_ok=False)
    started = time.monotonic()
    outcomes = []
    error = None
    accepted = False

    def stage(case, directory, admission=None, short=None, ticks=100):
        authorize(root)
        argv = [
            sys.executable,
            "-B",
            "-m",
            "sage.experiments.embodied_carry_v2.run",
            "--case",
            str(case),
            "--output",
            str(directory),
            "--ticks",
            str(ticks),
        ]
        if admission:
            argv += ["--admission", str(admission)]
        if short:
            argv += ["--short", str(short)]
        log_path = directory.with_suffix(".log")
        with log_path.open("w") as log:
            child = subprocess.run(
                argv,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=protocol["per_process_wall_s"],
            )
        if not (directory / "REPORT.json").exists():
            raise RuntimeError(
                f"engineering failure in {directory.name}, exit={child.returncode}; preserved {log_path}"
            )
        report = read_bound_json(directory / "REPORT.json")
        audited = audit(directory)
        outcomes.append(
            {
                "stage": directory.name,
                "report": _file_binding(directory / "REPORT.json"),
                "audit": _file_binding(directory / "CARRY_AUDIT.json"),
                "passed": audited["passed"],
                "stop_reason": report["stop_reason"],
                "physics_steps": report["physics_steps"],
                "sonic_writes": report["sonic_candidate_actuator_writes"],
            }
        )
        write_json_atomic(
            output / "PROGRESS.json",
            {"outcomes": outcomes, "elapsed_s": time.monotonic() - started},
        )
        if not audited["passed"] or (
            admission is None and not report["sonic_only_physics_smoke_admission_ready"]
        ):
            raise RuntimeError("stage rejected: " + directory.name)
        return directory / "REPORT.json"

    try:
        standing = root / "attempt_01/standing.json"
        sa = root / "verification_01/standing_admission/REPORT.json"
        prior_audit = read_bound_json(sa.with_name("CARRY_AUDIT.json"))
        if not prior_audit["passed"]:
            raise RuntimeError("corrected admission not independently accepted")
        ss = stage(standing, output / "standing_short", sa)
        sf = stage(standing, output / "standing_full", sa, ss, 300)
        walking = output / "walking.json"
        create(root, "walking", walking, sf)
        wa = stage(walking, output / "walking_admission")
        ws = stage(walking, output / "walking_short", wa)
        stage(walking, output / "walking_full", wa, ws, 300)
        accepted = True
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    result = {
        "schema": "ordered-contact-carry-continuation/v2",
        "prior_observer_report": _file_binding(
            root / "attempt_01/standing_admission/REPORT.json"
        ),
        "corrected_admission": _file_binding(
            root / "verification_01/standing_admission/CARRY_AUDIT.json"
        ),
        "audit_correction": _file_binding(
            root / "verification_01/standing_admission/CORRECTION.json"
        ),
        "classification": (
            "accepted_development_carry_cycle"
            if accepted
            else "stage_rejected_or_engineering_failure"
        ),
        "all_stages_passed": accepted,
        "error": error,
        "protocol": protocol_binding,
        "outcomes": outcomes,
        "physics_steps": sum(r["physics_steps"] for r in outcomes),
        "sonic_writes": sum(r["sonic_writes"] for r in outcomes),
        "elapsed_s": time.monotonic() - started,
        "implementation": _file_binding(Path(__file__)),
        "preloaded_grasp_not_pickup": True,
        "production_accepted": False,
    }
    result["content_sha256_excluding_this_field"] = canonical_sha256(result)
    write_json_atomic(output / "RESULT.json", result)
    print(result, flush=True)
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    run(p.parse_args().root)
