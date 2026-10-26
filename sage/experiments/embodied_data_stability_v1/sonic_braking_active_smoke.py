"""Qualified 2s smoke, then explicitly bounded 5/6s start-walk-stop segment."""

import argparse
import json
from pathlib import Path
from .sonic_braking_shadow import run_shadow, validated_admission


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--admission", type=Path, required=True)
    p.add_argument("--output-root", type=Path, required=True)
    p.add_argument(
        "--active-budget-ticks", type=int, choices=(100, 250, 300), default=100
    )
    p.add_argument("--short-smoke-report", type=Path)
    args = p.parse_args()
    info = validated_admission(args.admission)["report"]["planner"]
    result = run_shadow(
        args.output_root,
        reference_mode=1,
        baseline_reference=True,
        warmup_ticks=10,
        baseline_bias_compensation=True,
        real_command_history=True,
        active_admission=args.admission,
        band_lowering_steps=2,
        release_support_on_active=True,
        brake_speed=info["brake_speed_m_s"],
        brake_frame=info["brake_command_frame"],
        idle_frame=info["stop_command_frame"],
        active_budget_ticks=args.active_budget_ticks,
        short_smoke_report=args.short_smoke_report,
    )
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "classification",
                    "active_smoke_passed",
                    "active_control_ticks",
                    "stop_reason",
                    "controlled_stop_acceptance",
                )
            },
            indent=2,
        )
    )
    return 0 if result["active_smoke_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
