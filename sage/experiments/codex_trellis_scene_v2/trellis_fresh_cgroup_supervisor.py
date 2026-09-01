from __future__ import annotations

import argparse
import signal
import subprocess
from pathlib import Path
from typing import Sequence


def build_systemd_run_command(
    *,
    unit_name: str,
    log_path: Path,
    memory_high: str,
    memory_max: str,
    bridge_command: Sequence[str],
) -> list[str]:
    if not bridge_command:
        raise ValueError("bridge command must not be empty")
    return [
        "systemd-run",
        "--user",
        "--wait",
        "--collect",
        f"--unit={unit_name}",
        f"--property=MemoryHigh={memory_high}",
        f"--property=MemoryMax={memory_max}",
        "--property=ManagedOOMPreference=omit",
        "--property=OOMPolicy=stop",
        f"--property=StandardOutput=append:{log_path}",
        f"--property=StandardError=append:{log_path}",
        *bridge_command,
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run each bounded TRELLIS bridge batch in a fresh transient "
            "systemd cgroup while preserving hard memory limits."
        )
    )
    parser.add_argument("--unit-prefix", required=True)
    parser.add_argument("--log-dir", type=Path, required=True)
    parser.add_argument("--start-index", type=int, default=1)
    parser.add_argument("--max-groups", type=int, default=12)
    parser.add_argument("--memory-high", default="12G")
    parser.add_argument("--memory-max", default="16G")
    parser.add_argument("bridge_command", nargs=argparse.REMAINDER)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    bridge_command = list(args.bridge_command)
    if bridge_command[:1] == ["--"]:
        bridge_command = bridge_command[1:]
    if not bridge_command:
        raise SystemExit("bridge command is required after --")
    if args.max_groups <= 0:
        raise SystemExit("--max-groups must be positive")
    args.log_dir.mkdir(parents=True, exist_ok=True)

    current: dict[str, str | None] = {"unit": None}

    def stop_current(_signum: int, _frame: object) -> None:
        unit = current["unit"]
        if unit:
            subprocess.run(
                ["systemctl", "--user", "stop", unit],
                check=False,
            )
        raise SystemExit(128 + int(_signum))

    signal.signal(signal.SIGINT, stop_current)
    signal.signal(signal.SIGTERM, stop_current)

    for offset in range(args.max_groups):
        index = args.start_index + offset
        unit_name = f"{args.unit_prefix}-{index}"
        current["unit"] = unit_name
        log_path = args.log_dir / f"{unit_name}.log"
        command = build_systemd_run_command(
            unit_name=unit_name,
            log_path=log_path,
            memory_high=args.memory_high,
            memory_max=args.memory_max,
            bridge_command=bridge_command,
        )
        print(f"[fresh-cgroup-supervisor] starting {unit_name}", flush=True)
        result = subprocess.run(command, check=False)
        if result.returncode != 0:
            raise SystemExit(
                f"TRELLIS child unit {unit_name} failed with exit code "
                f"{result.returncode}; see {log_path}"
            )
        print(f"[fresh-cgroup-supervisor] completed {unit_name}", flush=True)
    current["unit"] = None
    raise SystemExit(
        f"reached --max-groups={args.max_groups}; refusing an unbounded loop"
    )


if __name__ == "__main__":
    main()
