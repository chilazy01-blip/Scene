#!/usr/bin/env python3
"""Explicit opt-in shared-GPU entry; the historical bridge stays unchanged.

Run inside a dedicated bounded systemd user service/cgroup, using the same
--heavy-job-lease-state as exclusive workers. Add --enable-shared-gpu and a
persistent --shared-proof-dir to the usual bridge arguments. The watchdog only
signals this bridge PID; the service manager owns cleanup of its own cgroup.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import asdict
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sage.experiments.codex_trellis_scene_v2.shared_gpu_execution import (
    GIB, SharedGpuBroker, SharedGpuPolicy, append_evidence, process_identity,
    select_shared_gpu, start_watchdog,
)


def parse_shared_args(argv: list[str]):
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--enable-shared-gpu", action="store_true", required=True)
    parser.add_argument("--shared-proof-dir", type=Path, required=True)
    parser.add_argument("--shared-required-peak-gib", type=float, default=20.0)
    parser.add_argument("--shared-gpu-reserve-gib", type=float, default=4.0)
    parser.add_argument("--shared-max-runtime-seconds", type=float, default=21600.0)
    return parser.parse_known_args(argv)


def main() -> None:
    shared, legacy_argv = parse_shared_args(sys.argv[1:])
    from sage.server.trellis2_flux_bridge_server import (
        JobStore, Trellis2BridgeRuntime, _is_loopback_url, build_handler, parse_args,
    )
    previous = sys.argv
    try:
        sys.argv = [previous[0], *legacy_argv]
        args = parse_args()
    finally:
        sys.argv = previous
    if not args.require_bounded_cgroup or not args.require_nvml_admission:
        raise ValueError("shared execution requires bounded cgroup and GPU telemetry")
    if args.builtin_imagegen_timeout <= 0:
        raise ValueError("--builtin-imagegen-timeout must be positive")
    for url in (args.builtin_imagegen_url, args.flux_server_url):
        if _is_loopback_url(url) and urlparse(url).port == int(args.port):
            raise ValueError("image provider and bridge must use different ports")
    for key, value in vars(args).items():
        if key.endswith("device") and isinstance(value, str) and value.startswith("cuda") and value not in {"cuda", "cuda:0"}:
            raise ValueError("shared bridge exposes the selected physical GPU as logical cuda:0")
    proof = shared.shared_proof_dir.expanduser().resolve()
    if Trellis2BridgeRuntime._path_is_temporary_storage(proof):
        raise ValueError("--shared-proof-dir must be persistent, outside /tmp and /var/tmp")
    policy = SharedGpuPolicy(required_peak_gib=shared.shared_required_peak_gib, gpu_reserve_gib=shared.shared_gpu_reserve_gib, max_runtime_seconds=shared.shared_max_runtime_seconds)
    maximum_bytes = int(args.maximum_cgroup_memory_gib * GIB)
    admission = select_shared_gpu(policy, maximum_cgroup_memory_bytes=maximum_bytes)
    append_evidence(proof / "admissions.jsonl", {"event": "startup_admission", "admission": admission, "policy": asdict(policy)})
    if not admission["accepted"]:
        raise SystemExit("shared GPU startup rejected: " + admission["status"])
    gpu = admission["gpu"]
    # UUID avoids CUDA/NVML physical-index ordering ambiguity. No torch/model
    # load occurs until after this binding and watchdog startup.
    os.environ["CUDA_VISIBLE_DEVICES"] = gpu["uuid"]
    args.gpu_index = int(gpu["gpu_index"])
    for name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE", "HF_HUB_DISABLE_TELEMETRY"):
        os.environ.setdefault(name, "1")
    runtime = Trellis2BridgeRuntime(args)
    evidence_root = runtime._persistent_evidence_root()
    jobs = JobStore(evidence_root / "bridge_jobs")
    lease_path = Path(args.heavy_job_lease_state) if args.heavy_job_lease_state else Path(args.output_dir) / "heavy_job_lease.json"
    broker = SharedGpuBroker(lease_path, policy=policy, selected_gpu=gpu, evidence_path=proof / "admissions.jsonl", lease_ttl_seconds=float(args.heavy_job_lease_ttl), maximum_cgroup_memory_bytes=maximum_bytes)
    config = {"policy": asdict(policy), "owner_identity": process_identity(os.getpid()), "selected_gpu": gpu, "maximum_cgroup_memory_bytes": maximum_bytes, "evidence_path": str(proof / "watchdog.jsonl"), "job_store_root": str(evidence_root / "bridge_jobs"), "lease_path": str(lease_path)}
    append_evidence(proof / "runtime.jsonl", {"event": "runtime_binding", **config, "startup_admission": admission})
    watchdog, stop_event = start_watchdog(config)
    try:
        with ThreadingHTTPServer((args.host, args.port), build_handler(jobs, runtime, broker)) as server:
            print(f"[trellis2-shared] serving http://{args.host}:{args.port}; physical GPU {gpu['gpu_index']} {gpu['uuid']}; {policy.required_peak_gib:g} GiB peak + {policy.gpu_reserve_gib:g} GiB reserve", flush=True)
            server.serve_forever()
    finally:
        stop_event.set()
        watchdog.join(timeout=2)


if __name__ == "__main__":
    main()
