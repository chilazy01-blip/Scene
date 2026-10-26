"""Independent supported SONIC-only 29-DoF body control smoke entrypoint.

Requires a bound passing shadow. Repeats its initial 50 ticks exactly, with
zero candidate writes, then applies at most 100 ticks of unchanged SONIC
targets through official PD. Every command and physical substep is guarded.
"""

import argparse
import json
from pathlib import Path

from .sonic_supported_shadow import run_shadow, validated_admission


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admission", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    admitted = validated_admission(args.admission)
    report = run_shadow(
        args.output_root, reference_mode=0, baseline_reference=True,
        warmup_ticks=10, paused_reference=True, baseline_bias_compensation=True,
        real_command_history=True, active_admission=args.admission,
        band_lowering_steps=admitted["report"]["support"]["startup_lowering_key7_presses"],
    )
    print(json.dumps({key: report[key] for key in (
        "classification", "physical_gates", "active_control_ticks", "active_physics_steps",
        "sonic_candidate_actuator_writes", "stop_reason", "runtime"
    )}, indent=2))
    return 0 if report["active_smoke_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
