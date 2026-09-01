from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .assets import bridge_health
from .build_sdf_complex_bedroom import (
    LAUNCH_THRESHOLDS,
    MAXIMUM_TASK_RSS_GIB,
    RUNTIME_THRESHOLDS,
    _atomic_write_json,
    _process_tree_rss_gib,
)
from .io_utils import read_json
from .content_chain import build_generation_contract
from .pilot_asset import PILOT_ASSET_DEFINITIONS, validate_pilot_report
from .resource_health import append_health_checkpoint


SCHEMA = "codex_trellis_sdf_asset_batch_v1"
DEFAULT_OUTPUT = Path(
    "/data/wsj/main/scene_runs/codex_trellis_v2/"
    "sdf_complex_bedroom_trellis2_20260829_v2"
)
DEFAULT_TRELLIS_REPO = Path("/data/wsj/main/scene/external/TRELLIS.2")
DEFAULT_TRELLIS_MODEL = Path(
    "/data/wsj/main/scene_runs/codex_trellis_v2/trellis2_primary_local"
)
DEFAULT_RMBG_MODEL = Path("/data/wsj/models/rmbg_2_0")
DEFAULT_TRELLIS_PYTHON = Path("/data/wsj/anaconda3/envs/trellis2/bin/python")
DEFAULT_CLIENT_PYTHON = Path(
    "/data/wsj/anaconda3/envs/tree-sage-flow2/bin/python"
)
FOREIGN_GEOMETRY_MARKERS = (
    "audit_geometry_quality.py",
    "blender",
    "trellis2_flux_bridge_server.py",
    "codex_trellis_scene_v2.pilot_asset",
    "run_batch_add_object_like.py",
    "component_probing.cli",
    "round11b_cuda_fea480",
    "formalize_one_node1.py",
)
CONCURRENCY_CLEAR_STABILITY_SECONDS = 3600.0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _proc_table() -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for status_path in Path("/proc").glob("[0-9]*/status"):
        try:
            values: dict[str, str] = {}
            for line in status_path.read_text(encoding="utf-8").splitlines():
                if line.startswith(("Pid:", "PPid:", "State:")):
                    key, value = line.split(":", 1)
                    values[key] = value.strip()
            pid = int(values["Pid"])
            cmdline = (status_path.parent / "cmdline").read_bytes().replace(
                b"\x00", b" "
            ).decode("utf-8", errors="replace")
            result[pid] = {
                "ppid": int(values["PPid"]),
                "state": values["State"].split()[0],
                "cmdline": cmdline,
            }
        except (FileNotFoundError, KeyError, PermissionError, ProcessLookupError, ValueError):
            continue
    return result


def _descendants(root_pid: int, table: dict[int, dict[str, Any]]) -> set[int]:
    members = {int(root_pid)}
    changed = True
    while changed:
        changed = False
        for pid, item in table.items():
            if int(item["ppid"]) in members and pid not in members:
                members.add(pid)
                changed = True
    return members


def foreign_geometry_processes() -> list[dict[str, Any]]:
    table = _proc_table()
    own = _descendants(os.getpid(), table)
    found: list[dict[str, Any]] = []
    for pid, item in table.items():
        if pid in own or item["state"] in {"T", "t", "Z", "X", "I"}:
            continue
        command = str(item["cmdline"])
        if not command or not any(marker in command for marker in FOREIGN_GEOMETRY_MARKERS):
            continue
        found.append(
            {
                "pid": pid,
                "ppid": int(item["ppid"]),
                "state": str(item["state"]),
                "cmdline": command,
            }
        )
    return sorted(found, key=lambda item: int(item["pid"]))


def _terminate(process: subprocess.Popen[Any] | None) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()


def _wait_for_concurrency_gate(output: Path) -> None:
    last_summary = ""
    clear_started: float | None = None
    while True:
        foreign = foreign_geometry_processes()
        if not foreign:
            if clear_started is None:
                clear_started = time.monotonic()
                print(
                    f"[{_utc_now()}] foreign geometry clear; starting "
                    f"{CONCURRENCY_CLEAR_STABILITY_SECONDS:.0f}s stability window",
                    flush=True,
                )
            clear_seconds = time.monotonic() - clear_started
            if clear_seconds < CONCURRENCY_CLEAR_STABILITY_SECONDS:
                time.sleep(30)
                continue
            append_health_checkpoint(
                output / "resource_health.jsonl",
                stage="trellis_batch_concurrency_gate_clear",
                require_healthy=True,
                thresholds=LAUNCH_THRESHOLDS,
            )
            return
        clear_started = None
        summary = ", ".join(
            f"pid={item['pid']} state={item['state']}" for item in foreign
        )
        if summary != last_summary:
            print(f"[{_utc_now()}] waiting for foreign geometry: {summary}", flush=True)
            last_summary = summary
        time.sleep(30)


def _require_concurrency_gate_clear(output: Path, stage: str) -> None:
    foreign = foreign_geometry_processes()
    if foreign:
        raise RuntimeError(
            "foreign geometry started after TRELLIS bridge launch: "
            + ", ".join(f"pid={item['pid']}" for item in foreign)
        )
    append_health_checkpoint(
        output / "resource_health.jsonl",
        stage=stage,
        require_healthy=True,
        thresholds=LAUNCH_THRESHOLDS,
    )


def _bridge_command(args: argparse.Namespace) -> list[str]:
    return [
        str(args.trellis_python),
        str(args.bridge_script),
        "--host",
        "127.0.0.1",
        "--port",
        "8082",
        "--trellis-repo",
        str(args.trellis_repo),
        "--trellis-model",
        str(args.trellis_model),
        "--output-dir",
        str(args.output_dir / "bridge_runtime"),
        "--rmbg-model",
        str(args.rmbg_model),
        "--rmbg-module-root",
        "/data/wsj/cache/hf_home/modules",
        "--pipeline-type",
        "512",
        "--no-trellis-low-vram",
        "--trellis-preprocess-image",
        "--texture-size",
        "512",
        "--decimation-target",
        "500000",
        "--no-glb-webp",
        "--sparse-steps",
        "12",
        "--shape-steps",
        "12",
        "--tex-steps",
        "12",
    ]


def _pilot_command(args: argparse.Namespace, item: dict[str, Any]) -> list[str]:
    return [
        str(args.client_python),
        "-m",
        "sage.experiments.codex_trellis_scene_v2.pilot_asset",
        "--category",
        str(item["category"]),
        "--object-id",
        str(item["object_id"]),
        "--asset-prompt",
        str(item["asset_prompt"]),
        "--reference-image",
        str(args.output_dir / str(item["reference_image"])),
        "--output-dir",
        str(args.output_dir / "trellis_assets"),
        "--trellis-url",
        "http://127.0.0.1:8082",
        "--pipeline-type",
        "512",
        "--preprocess-image",
        "--seed",
        str(item["seed"]),
        "--timeout",
        "1800",
        "--steps",
        "12",
        "--texture-size",
        "512",
        "--decimation-target",
        "500000",
        "--model-fingerprint",
        str(args.trellis_model_fingerprint),
        "--rmbg-fingerprint",
        str(args.rmbg_model_fingerprint),
        "--code-version",
        str(args.generation_code_version),
    ]


def _expected_pilot_contract(args: argparse.Namespace, item: dict[str, Any]) -> dict[str, Any]:
    width, length, height = PILOT_ASSET_DEFINITIONS[str(item["category"])]["dimensions"]
    return build_generation_contract(
        category=str(item["category"]),
        prompt=str(item["asset_prompt"]),
        target_dimensions_m={"width": width, "length": length, "height": height},
        seed=int(item["seed"]),
        model_fingerprint=str(args.trellis_model_fingerprint),
        rmbg_fingerprint=str(args.rmbg_model_fingerprint),
        pipeline_type="512",
        steps=12,
        texture_size=512,
        decimation_target=500000,
        preprocess_image=True,
        code_version=str(args.generation_code_version),
        reference_image=args.output_dir / str(item["reference_image"]),
    )


def _monitor_pilot(
    *,
    output: Path,
    bridge: subprocess.Popen[Any],
    pilot: subprocess.Popen[Any],
    asset_id: str,
) -> dict[str, Any]:
    maximum_rss_gib = 0.0
    over_rss_samples = 0
    io_pressure_samples = 0
    termination_reason: str | None = None
    started = time.monotonic()
    while pilot.poll() is None:
        if bridge.poll() is not None:
            termination_reason = "bridge_exited_during_asset"
            break
        foreign = foreign_geometry_processes()
        if foreign:
            termination_reason = "foreign_geometry_started"
            break
        rss_gib = _process_tree_rss_gib(bridge.pid) + _process_tree_rss_gib(pilot.pid)
        maximum_rss_gib = max(maximum_rss_gib, rss_gib)
        over_rss_samples = over_rss_samples + 1 if rss_gib > MAXIMUM_TASK_RSS_GIB else 0
        health = append_health_checkpoint(
            output / "resource_health.jsonl",
            stage=f"trellis_{asset_id}_monitor",
            require_healthy=False,
            thresholds=RUNTIME_THRESHOLDS,
        )
        metrics = health["metrics"]
        pressure = bool(
            max(
                int(metrics["blocked_processes_before"]),
                int(metrics["blocked_processes_after"]),
            )
            > 16
            or float(metrics["iowait_fraction"]) > 0.35
        )
        io_pressure_samples = io_pressure_samples + 1 if pressure else 0
        if over_rss_samples >= 2:
            termination_reason = "task_rss_above_12_gib_twice"
        elif float(metrics["mem_available_gib"]) < 64.0:
            termination_reason = "mem_available_below_64_gib"
        elif float(metrics["dirty_writeback_gib"]) > 4.0:
            termination_reason = "dirty_writeback_above_4_gib"
        elif io_pressure_samples >= 3:
            termination_reason = "blocked_or_iowait_pressure_three_samples"
        if termination_reason:
            break
        time.sleep(4)
    if termination_reason:
        _terminate(pilot)
    return_code = pilot.wait()
    checkpoint = {
        "schema": SCHEMA,
        "asset_id": asset_id,
        "elapsed_seconds": time.monotonic() - started,
        "exit_code": return_code if return_code >= 0 else None,
        "signal": -return_code if return_code < 0 else None,
        "maximum_task_process_tree_rss_gib": maximum_rss_gib,
        "termination_reason": termination_reason,
        "ok": bool(return_code == 0 and termination_reason is None),
    }
    _atomic_write_json(
        output / "checkpoints" / f"trellis_{asset_id}.exit.json", checkpoint
    )
    return checkpoint


def run(args: argparse.Namespace) -> None:
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / "trellis_assets").mkdir(parents=True, exist_ok=True)
    plan = read_json(output / "missing_asset_generation_plan.json")
    assets = list(plan["assets"])
    environment = dict(os.environ)
    environment.update(
        {
            "CUDA_VISIBLE_DEVICES": str(args.cuda_visible_devices),
            "HF_HOME": "/data/wsj/cache/hf_home",
            "HF_HUB_CACHE": "/data/wsj/cache/hf_home/hub",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "ATTN_BACKEND": "sdpa",
            "SPARSE_ATTN_BACKEND": "sdpa",
            "SPARSE_CONV_BACKEND": "flex_gemm",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "PYTHONPATH": str(args.repository_root),
        }
    )
    bridge: subprocess.Popen[Any] | None = None
    bridge_log = output / "logs" / "trellis_bridge_book_regeneration_v2.log"
    bridge_log.parent.mkdir(parents=True, exist_ok=True)
    try:
        _wait_for_concurrency_gate(output)
        with bridge_log.open("a", encoding="utf-8") as bridge_handle:
            bridge = subprocess.Popen(
                _bridge_command(args),
                cwd=args.repository_root,
                env=environment,
                stdout=bridge_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            for _ in range(60):
                if bridge.poll() is not None:
                    raise RuntimeError("TRELLIS bridge exited before becoming healthy")
                if bridge_health("http://127.0.0.1:8082").get("ok"):
                    break
                time.sleep(2)
            else:
                raise TimeoutError("TRELLIS bridge health timeout")

            for item in assets:
                asset_id = str(item["object_id"])
                report_path = output / "trellis_assets" / f"{asset_id}_pilot_report.json"
                if report_path.is_file():
                    report = read_json(report_path)
                    valid, reasons = validate_pilot_report(
                        report, _expected_pilot_contract(args, item)
                    )
                    if valid:
                        print(f"[{_utc_now()}] resume accepted existing {asset_id}", flush=True)
                        continue
                    print(
                        f"[{_utc_now()}] invalidated stale {asset_id}: {','.join(reasons)}",
                        flush=True,
                    )
                _require_concurrency_gate_clear(
                    output, f"trellis_{asset_id}_launch"
                )
                log_path = output / "logs" / f"trellis_{asset_id}.log"
                with log_path.open("a", encoding="utf-8") as pilot_handle:
                    pilot = subprocess.Popen(
                        _pilot_command(args, item),
                        cwd=args.repository_root,
                        env=environment,
                        stdout=pilot_handle,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                    )
                    checkpoint = _monitor_pilot(
                        output=output,
                        bridge=bridge,
                        pilot=pilot,
                        asset_id=asset_id,
                    )
                if not checkpoint["ok"]:
                    raise RuntimeError(
                        f"TRELLIS asset failed: {asset_id}: {checkpoint}"
                    )
                report = read_json(report_path)
                if not bool(report.get("ok")):
                    raise RuntimeError(f"pilot report rejected generated asset: {asset_id}")
                print(f"[{_utc_now()}] generated {asset_id}", flush=True)
    finally:
        _terminate(bridge)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Resource-gated serial TRELLIS.2 generation for the SDF bedroom."
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).parents[3])
    parser.add_argument(
        "--bridge-script",
        type=Path,
        default=Path(__file__).parents[2] / "server" / "trellis2_flux_bridge_server.py",
    )
    parser.add_argument("--trellis-repo", type=Path, default=DEFAULT_TRELLIS_REPO)
    parser.add_argument("--trellis-model", type=Path, default=DEFAULT_TRELLIS_MODEL)
    parser.add_argument("--rmbg-model", type=Path, default=DEFAULT_RMBG_MODEL)
    parser.add_argument("--trellis-python", type=Path, default=DEFAULT_TRELLIS_PYTHON)
    parser.add_argument("--client-python", type=Path, default=DEFAULT_CLIENT_PYTHON)
    parser.add_argument(
        "--trellis-model-fingerprint",
        default=os.environ.get("SAGE_TRELLIS_MODEL_FINGERPRINT", "unfrozen-local-trellis-model"),
    )
    parser.add_argument(
        "--rmbg-model-fingerprint",
        default=os.environ.get("SAGE_RMBG_MODEL_FINGERPRINT", "unfrozen-local-rmbg-model"),
    )
    parser.add_argument(
        "--generation-code-version",
        default=os.environ.get("SAGE_GENERATION_CODE_VERSION", "unfrozen-scene-v2-code"),
    )
    parser.add_argument(
        "--cuda-visible-devices",
        default="0",
        help="Physical CUDA device list exposed to the TRELLIS bridge (default: 0).",
    )
    return parser


def main() -> None:
    run(build_parser().parse_args())


if __name__ == "__main__":
    main()
