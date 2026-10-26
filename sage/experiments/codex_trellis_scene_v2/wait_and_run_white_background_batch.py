"""Wait for two truly idle GPUs, then run the frozen white-background batch."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .resource_health import sample_resource_health


def gpu_snapshot() -> list[dict[str, Any]]:
    gpu = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=index,uuid,memory.total,memory.used,utilization.gpu,temperature.gpu",
            "--format=csv,noheader,nounits",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    processes = subprocess.run(
        [
            "nvidia-smi",
            "--query-compute-apps=gpu_uuid,pid,used_memory,name",
            "--format=csv,noheader,nounits",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    by_uuid: dict[str, list[dict[str, Any]]] = {}
    for line in processes.stdout.splitlines():
        fields = [item.strip() for item in line.split(",", 3)]
        if len(fields) != 4:
            continue
        by_uuid.setdefault(fields[0], []).append(
            {"pid": int(fields[1]), "used_memory_mib": int(fields[2]), "name": fields[3]}
        )
    rows: list[dict[str, Any]] = []
    for line in gpu.stdout.splitlines():
        values = [item.strip() for item in line.split(",")]
        if len(values) != 6:
            continue
        rows.append(
            {
                "index": int(values[0]),
                "uuid": values[1],
                "memory_total_mib": int(values[2]),
                "memory_used_mib": int(values[3]),
                "utilization_percent": int(values[4]),
                "temperature_c": int(values[5]),
                "compute_processes": by_uuid.get(values[1], []),
            }
        )
    return rows


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _health(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=5.0) as response:
            return response.status == 200
    except Exception:
        return False


def _wait_health(url: str, process: subprocess.Popen, timeout: float, label: str) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"{label} exited before health check: {process.returncode}")
        if _health(url):
            return
        time.sleep(3.0)
    raise TimeoutError(f"{label} health timeout: {url}")


def _stop(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def run(args: argparse.Namespace) -> int:
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    monitor_path = output / "gpu_monitor.jsonl"
    streak: list[int] = []
    selected: list[int] | None = None
    while selected is None:
        gpu = gpu_snapshot()
        resources = sample_resource_health(sample_seconds=0.5)
        free = sorted(
            row["index"]
            for row in gpu
            if not row["compute_processes"]
            and row["memory_used_mib"] <= int(args.maximum_idle_memory_mib)
        )
        pair = free[:2]
        if len(pair) == 2 and bool(resources.get("healthy_for_heavy_stage")):
            if pair == streak:
                args._stable_samples += 1
            else:
                streak = pair
                args._stable_samples = 1
        else:
            streak = []
            args._stable_samples = 0
        sample = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "gpu": gpu,
            "resource_health": resources,
            "free_gpu_indices": free,
            "candidate_pair": pair,
            "stable_sample_count": args._stable_samples,
            "required_stable_sample_count": int(args.stable_samples),
        }
        append_jsonl(monitor_path, sample)
        print(json.dumps({"event": "gpu_sample", **sample}), flush=True)
        if args._stable_samples >= int(args.stable_samples):
            selected = pair
            break
        time.sleep(float(args.poll_seconds))

    admission = {
        "schema": "white_background_real_batch_gpu_admission_v1",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "accepted": True,
        "policy": {
            "minimum_free_gpu_count": 2,
            "maximum_idle_memory_mib": int(args.maximum_idle_memory_mib),
            "stable_samples": int(args.stable_samples),
            "poll_seconds": float(args.poll_seconds),
            "external_compute_processes_allowed": False,
        },
        "flux_gpu_index": selected[0],
        "trellis_gpu_index": selected[1],
        "final_snapshot": gpu_snapshot(),
        "resource_health": sample_resource_health(sample_seconds=0.5),
    }
    (output / "gpu_admission.json").write_text(json.dumps(admission, indent=2), encoding="utf-8")

    root = Path(__file__).resolve().parents[3]
    flux_log = (output / "logs" / "flux.log")
    bridge_log = (output / "logs" / "trellis_bridge.log")
    runner_log = (output / "logs" / "batch_runner.log")
    flux_log.parent.mkdir(parents=True, exist_ok=True)
    base_env = os.environ.copy()
    base_env.update(
        {
            "HF_HOME": "/data/wsj/cache/hf_home",
            "HF_HUB_CACHE": "/data/wsj/cache/hf_home/hub",
            "HF_XET_CACHE": "/data/wsj/cache/hf_home/xet",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_DATASETS_OFFLINE": "1",
            "ATTN_BACKEND": "sdpa",
            "SPARSE_ATTN_BACKEND": "sdpa",
            "SPARSE_CONV_BACKEND": "flex_gemm",
            "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True",
            "XDG_CONFIG_HOME": "/tmp/codex-white-bg-blender-config",
            "XDG_CACHE_HOME": "/tmp/codex-white-bg-blender-cache",
            "XDG_DATA_HOME": "/tmp/codex-white-bg-blender-data",
        }
    )
    flux_env = {**base_env, "CUDA_VISIBLE_DEVICES": str(selected[0])}
    bridge_env = {**base_env, "CUDA_VISIBLE_DEVICES": str(selected[1])}
    flux: subprocess.Popen | None = None
    bridge: subprocess.Popen | None = None
    try:
        with flux_log.open("a", encoding="utf-8") as stream:
            flux = subprocess.Popen(
                [
                    "/data/wsj/anaconda3/envs/simgen/bin/python",
                    str(root / "sage/server/flux_schnell_server.py"),
                    "--host", "127.0.0.1", "--port", "8083",
                    "--model-path", "/data/wsj/models/text_to_image__primary",
                    "--output-dir", str(output / "flux_output"),
                    # This host's validated FLUX.1-schnell path uses sequential
                    # model CPU offload.  Moving the entire pipeline with
                    # pipe.to(cuda) can stall during cold start even on an
                    # otherwise empty A6000 and provides no batch-quality gain.
                    "--device", "cuda:0", "--cpu-offload", "--preload",
                ],
                env=flux_env,
                stdout=stream,
                stderr=subprocess.STDOUT,
            )
        _wait_health("http://127.0.0.1:8083/health", flux, float(args.service_timeout), "Flux")
        with bridge_log.open("a", encoding="utf-8") as stream:
            bridge = subprocess.Popen(
                [
                    "/data/wsj/anaconda3/envs/trellis2/bin/python",
                    str(root / "sage/server/trellis2_flux_bridge_server.py"),
                    "--host", "127.0.0.1", "--port", "8082",
                    "--flux-server-url", "http://127.0.0.1:8083",
                    "--image-provider", "flux1-schnell",
                    "--trellis-repo", str(root / "external/TRELLIS.2"),
                    "--trellis-model", "/data/wsj/main/scene_runs/codex_trellis_v2/trellis2_primary_local",
                    "--output-dir", str(output / "bridge_output"),
                    "--persistent-evidence-dir", str(output / "persistent_reference_evidence"),
                    "--rmbg-model", "/data/wsj/models/rmbg_2_0",
                    "--rmbg-module-root", "/data/wsj/cache/hf_home/modules",
                    "--pipeline-type", "512", "--flux-background-mode", "white",
                    "--background-isolation-require-clean", "--alpha-require-quality",
                    "--trellis-preprocess-image", "--texture-size", "512",
                    "--decimation-target", "300000", "--no-glb-webp",
                    "--no-trellis-low-vram", "--gpu-index", str(selected[1]),
                    "--maximum-cgroup-memory-gib", str(float(args.maximum_cgroup_memory_gib)),
                    "--require-bounded-cgroup", "--require-nvml-admission",
                    "--flux-timeout", "900",
                ],
                env=bridge_env,
                stdout=stream,
                stderr=subprocess.STDOUT,
            )
        _wait_health("http://127.0.0.1:8082/health", bridge, float(args.service_timeout), "TRELLIS bridge")
        with runner_log.open("a", encoding="utf-8") as stream:
            completed = subprocess.run(
                [
                    "/data/wsj/anaconda3/envs/simgen/bin/python", "-m",
                    "sage.experiments.codex_trellis_scene_v2.white_background_real_batch",
                    "--output-dir", str(output), "--bridge-url", "http://127.0.0.1:8082",
                    "--blender", "/data/wsj/tools/blender-4.3.2-linux-x64/blender",
                    "--steps", "12", "--texture-size", "512",
                    "--decimation-target", "300000", "--resolution", "420",
                    "--timeout", "2400", "--resume",
                ],
                cwd=root,
                env=base_env,
                stdout=stream,
                stderr=subprocess.STDOUT,
                check=False,
            )
        completion = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "runner_returncode": completed.returncode,
            "validation_summary": str(output / "validation_summary.json"),
        }
        (output / "orchestrator_completion.json").write_text(json.dumps(completion, indent=2), encoding="utf-8")
        return int(completed.returncode)
    except Exception as exc:
        failure = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "error": f"{type(exc).__name__}: {exc}",
            "flux_gpu_index": selected[0],
            "trellis_gpu_index": selected[1],
            "resume_safe": True,
        }
        (output / "orchestrator_failure.json").write_text(
            json.dumps(failure, indent=2), encoding="utf-8"
        )
        raise
    finally:
        _stop(bridge)
        _stop(flux)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--poll-seconds", type=float, default=30.0)
    parser.add_argument("--stable-samples", type=int, default=3)
    parser.add_argument("--maximum-idle-memory-mib", type=int, default=1024)
    parser.add_argument("--service-timeout", type=float, default=600.0)
    parser.add_argument("--maximum-cgroup-memory-gib", type=float, default=96.0)
    parser.set_defaults(_stable_samples=0)
    return parser


def main(argv: list[str] | None = None) -> int:
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
