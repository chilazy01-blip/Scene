"""Execute one independently qualified low-speed SONIC standing-to-WALK smoke."""

import argparse
import json
from pathlib import Path

from .sonic_walk_shadow import run_shadow, validated_admission


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admission", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    admitted = validated_admission(args.admission)
    if admitted["report"]["support"].get("release_on_active") is not True:
        raise RuntimeError(
            "WALK requires explicit qualification for active support release"
        )
    report = run_shadow(
        args.output_root,
        reference_mode=2,
        baseline_reference=True,
        warmup_ticks=10,
        paused_reference=False,
        baseline_bias_compensation=True,
        real_command_history=True,
        active_admission=args.admission,
        band_lowering_steps=2,
        release_support_on_active=True,
    )
    keys = (
        "classification",
        "physical_gates",
        "active_control_ticks",
        "active_physics_steps",
        "sonic_candidate_actuator_writes",
        "stop_reason",
        "motion_metrics",
        "runtime",
    )
    print(json.dumps({key: report[key] for key in keys}, indent=2))
    return 0 if report["active_smoke_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
