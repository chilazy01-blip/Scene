"""Correct a read-only audit timebase in a new directory; never replay physics."""

import argparse
from pathlib import Path
from .audit_corrected import audit
from sage.experiments.embodied_data_stability_v1.audit_candidates import (
    canonical_sha256,
    write_json_atomic,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def verify(source, output):
    output.mkdir(parents=True, exist_ok=False)
    (output / "REPORT.json").symlink_to(source / "REPORT.json")
    correction = {
        "schema": "audit-timebase-correction/v1",
        "source_report": _file_binding(source / "REPORT.json"),
        "prior_audit": _file_binding(source / "CARRY_AUDIT.json"),
        "reason": "execution sets native.SIMULATION_DT_S (.005s), but first audit used XML default (.002s) for local finite-difference speed, falsely reducing grip counter. Restore execution timestep only; unchanged traces/engine/thresholds.",
        "corrected_auditor": _file_binding(
            Path(__file__).with_name("audit_corrected.py")
        ),
        "physics_steps": 0,
        "old_evidence_unchanged": True,
    }
    correction["content_sha256_excluding_this_field"] = canonical_sha256(correction)
    write_json_atomic(output / "CORRECTION.json", correction)
    return audit(output)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    verify(a.source, a.output)
