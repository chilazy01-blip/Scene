"""Carry qualification, unsupported standing hold or bounded walking attempt."""

import argparse
import json
from pathlib import Path
from .engine import run_shadow
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--case", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--admission", type=Path)
    p.add_argument("--short", type=Path)
    p.add_argument("--ticks", type=int, choices=(100, 300), default=100)
    a = p.parse_args()
    case = read_bound_json(a.case)
    report = run_shadow(
        a.output,
        case_path=a.case,
        reference_mode=0 if case["carry_mode"] == "standing" else 1,
        baseline_reference=True,
        warmup_ticks=10,
        baseline_bias_compensation=True,
        real_command_history=True,
        active_admission=a.admission,
        band_lowering_steps=2,
        release_support_on_active=True,
        active_budget_ticks=a.ticks,
        short_smoke_report=a.short,
    )
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "classification",
                    "active_smoke_passed",
                    "active_control_ticks",
                    "stop_reason",
                    "carrying_acceptance",
                )
            },
            indent=2,
        )
    )
    raise SystemExit(
        0
        if report["active_smoke_passed"]
        or report["sonic_only_physics_smoke_admission_ready"]
        else 2
    )
