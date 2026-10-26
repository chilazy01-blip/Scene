"""Audit a staged SONIC v1.1 readmission without running physics.

The audit binds the recovered source tree, pinned Hugging Face artifacts,
CPU-only ONNX structure checks, local host capabilities, and the explicit
29-DoF/body versus Dex3-hand boundary into one fail-closed report.  It does
not download resources, build the native runtime, render, train, or actuate a
simulator.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .audit_candidates import canonical_sha256, sha256_file, write_json_atomic


SCHEMA = "sonic-readmission/v1"
SOURCE_COMMIT = "b042411fae38ee4d1af9aac82a37a1f8d14d6dd0"
SOURCE_ARCHIVE_SHA256 = (
    "362d61a1e9b4962f64c187c5db65ac2c6c89e5ae07453baf8203d8c3c71066bc"
)
SOURCE_REPOSITORY = "https://github.com/NVlabs/GR00T-WholeBodyControl.git"
HF_REPOSITORY = "nvidia/GEAR-SONIC"
HF_REVISION = "6733128a3d8a523b1418b06bca3cdf61c8b0987f"

EXPECTED_ARTIFACTS: dict[str, dict[str, Any]] = {
    "model_encoder": {
        "relative_path": "weights/sonic_v1_1/model_encoder.onnx",
        "size_bytes": 50_117_796,
        "sha256": "fb97de22819b2057b41459802128d91723d91a25f0ad73e7bfc41a9cf8365bae",
        "security_status": "safe",
    },
    "model_decoder": {
        "relative_path": "weights/sonic_v1_1/model_decoder.onnx",
        "size_bytes": 149_778_638,
        "sha256": "34bae8570d4a4421a5391a5c2befd745d4a02d182ec539e5f9da44c091c67509",
        "security_status": "safe",
    },
    "observation_config": {
        "relative_path": "weights/sonic_v1_1/observation_config.yaml",
        "size_bytes": 2_475,
        "sha256": "4a67713b310932e50aca81f19188c8d76013148e98b15c8b5bbea995f12e59f0",
        "security_status": "safe",
    },
    "hf_config": {
        "relative_path": "metadata/hf_config.json",
        "size_bytes": 2_428,
        "sha256": "326dcc509ad93509cf262871256a74f508f43a8430f61ec6abe8034e985ce948",
        "security_status": "metadata",
    },
    "hf_license": {
        "relative_path": "metadata/HF_LICENSE",
        "size_bytes": 8_886,
        "sha256": "24ab66be50d1aca4fc5e029ef76ce4ceaac6557ea21665caf4b140695a76ffee",
        "security_status": "metadata",
    },
}

EXPECTED_INTERFACES = {
    "model_encoder": {
        "input_name": "obs_dict",
        "input_shape": [1, 1751],
        "output_name": "encoded_tokens",
        "output_shape": [1, 64],
        "zero_output_sha256": (
            "6019343b6130bea8c91244797cb7eea261105fa6b2303eaafc35d94a2009214d"
        ),
    },
    "model_decoder": {
        "input_name": "obs_dict",
        "input_shape": [1, 994],
        "output_name": "action",
        "output_shape": [1, 29],
        "zero_output_sha256": (
            "6516a22ec5e7f3098cb37ef40ed4923a454dc3193af1794924547f227d395eec"
        ),
    },
}

PLANNER_POLICY = {
    "relative_path": "weights/planner_sonic.onnx",
    "expected_size_bytes": 773_952_989,
    "expected_sha256": (
        "39b553e197f62f077975ba38512bc04781a3fc37c2af7c6756e04629f760edea"
    ),
    "protect_ai_status": "suspicious",
    "protect_ai_rule": "PAIT-ONNX-200",
    "download_authorized": False,
}

TRAINING_CHECKPOINT_POLICY = {
    "relative_path": "weights/sonic_v1_1/last.pt",
    "expected_size_bytes": 1_138_000_000,
    "protect_ai_status": "unsafe",
    "protect_ai_rule": "PAIT-PYTCH-100",
    "download_authorized": False,
    "needed_for_current_stage": False,
}

LFS_HEADER = b"version https://git-lfs.github.com/spec/v1\n"
GIT_TREE_ROW = re.compile(rb"([0-7]{6}) ([a-z]+) ([0-9a-f]{40})\t(.*)", re.DOTALL)
NVIDIA_SMI_ROW = re.compile(
    r"^(?P<index>\d+)\s*,\s*(?P<name>.*?)\s*,\s*(?P<memory_total>\d+)\s*,\s*"
    r"(?P<memory_used>\d+)\s*,\s*(?P<utilization>\d+)\s*,\s*(?P<driver>[^,]+)$"
)

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


def _run_command(
    args: Sequence[str],
    *,
    timeout_s: float = 15.0,
    runner: CommandRunner = subprocess.run,
) -> dict[str, Any]:
    """Run one bounded read-only probe and retain compact diagnostics."""

    try:
        completed = runner(
            list(args),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "argv": list(args),
            "returncode": None,
            "stdout": "",
            "stderr": str(exc),
            "succeeded": False,
        }
    return {
        "argv": list(args),
        "returncode": completed.returncode,
        "stdout": completed.stdout[-4000:].strip(),
        "stderr": completed.stderr[-4000:].strip(),
        "succeeded": completed.returncode == 0,
    }


def inspect_artifacts(run_root: Path) -> dict[str, Any]:
    artifacts: dict[str, Any] = {}
    for name, expected in EXPECTED_ARTIFACTS.items():
        path = run_root / expected["relative_path"]
        exists = path.is_file()
        size = path.stat().st_size if exists else 0
        digest = sha256_file(path) if exists else None
        artifacts[name] = {
            "path": str(path),
            "exists": exists,
            "size_bytes": size,
            "expected_size_bytes": expected["size_bytes"],
            "size_matches": size == expected["size_bytes"],
            "sha256": digest,
            "expected_sha256": expected["sha256"],
            "sha256_matches": digest == expected["sha256"],
            "security_status": expected["security_status"],
            "ready": bool(
                exists
                and size == expected["size_bytes"]
                and digest == expected["sha256"]
            ),
        }
    return artifacts


def _git_blob_sha1(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data, usedforsecurity=False).hexdigest()


def load_git_tree(
    git_dir: Path,
    commit: str = SOURCE_COMMIT,
    *,
    runner: CommandRunner = subprocess.run,
) -> tuple[dict[str, dict[str, str]], dict[str, Any]]:
    command = [
        "git",
        f"--git-dir={git_dir}",
        "ls-tree",
        "-r",
        "-z",
        "--full-tree",
        commit,
    ]
    try:
        completed = runner(
            command,
            check=False,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {}, {
            "git_dir": str(git_dir),
            "commit": commit,
            "commit_object_available": False,
            "error": str(exc),
        }
    if completed.returncode != 0:
        return {}, {
            "git_dir": str(git_dir),
            "commit": commit,
            "commit_object_available": False,
            "error": completed.stderr.decode("utf-8", errors="replace")[-2000:],
        }
    entries: dict[str, dict[str, str]] = {}
    malformed = 0
    for raw in completed.stdout.split(b"\0"):
        if not raw:
            continue
        match = GIT_TREE_ROW.fullmatch(raw)
        if match is None:
            malformed += 1
            continue
        path = match.group(4).decode("utf-8", errors="surrogateescape")
        entries[path] = {
            "mode": match.group(1).decode("ascii"),
            "type": match.group(2).decode("ascii"),
            "oid": match.group(3).decode("ascii"),
        }
    return entries, {
        "git_dir": str(git_dir),
        "commit": commit,
        "commit_object_available": bool(entries) and malformed == 0,
        "tree_entry_count": len(entries),
        "malformed_tree_rows": malformed,
    }


def _read_path_bytes(path: Path) -> tuple[str, bytes, int]:
    if path.is_symlink():
        data = os.readlink(path).encode("utf-8", errors="surrogateescape")
        return "symlink", data, len(data)
    data = path.read_bytes()
    executable = bool(path.stat().st_mode & stat.S_IXUSR)
    return "executable" if executable else "file", data, len(data)


def inspect_source_tree(
    source_root: Path,
    *,
    git_entries: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    if not source_root.is_dir():
        return {
            "path": str(source_root),
            "exists": False,
            "commit_tree_exact_match": False,
            "lfs_pointer_count": 0,
        }

    manifest = hashlib.sha256()
    pointer_paths = hashlib.sha256()
    lfs_groups: collections.Counter[str] = collections.Counter()
    local_paths: set[str] = set()
    blob_mismatches: list[str] = []
    mode_mismatches: list[str] = []
    file_count = 0
    total_bytes = 0
    lfs_pointer_count = 0
    lfs_claimed_bytes = 0
    regular_file_count = 0
    symlink_count = 0
    native_deploy_lfs_pointer_count = 0
    native_robot_model_lfs_pointer_count = 0

    for path in sorted(source_root.rglob("*")):
        if not (path.is_file() or path.is_symlink()):
            continue
        relative = path.relative_to(source_root).as_posix()
        local_paths.add(relative)
        kind, data, size = _read_path_bytes(path)
        file_count += 1
        if kind == "symlink":
            symlink_count += 1
        else:
            regular_file_count += 1
        total_bytes += size
        digest = hashlib.sha256(data).hexdigest()
        manifest.update(
            f"{relative}\0{kind}\0{size}\0{digest}\n".encode(
                "utf-8", errors="surrogateescape"
            )
        )
        if data.startswith(LFS_HEADER):
            lfs_pointer_count += 1
            if relative.startswith("gear_sonic_deploy/"):
                native_deploy_lfs_pointer_count += 1
            if relative.startswith("gear_sonic_deploy/g1/"):
                native_robot_model_lfs_pointer_count += 1
            pointer_paths.update((relative + "\n").encode("utf-8"))
            parts = relative.split("/")
            lfs_groups["/".join(parts[: min(3, len(parts))])] += 1
            size_match = re.search(rb"^size (\d+)$", data, flags=re.MULTILINE)
            if size_match:
                lfs_claimed_bytes += int(size_match.group(1))

        if git_entries is not None:
            expected = git_entries.get(relative)
            if expected is None:
                continue
            if expected.get("type") != "blob" or _git_blob_sha1(data) != expected.get(
                "oid"
            ):
                if len(blob_mismatches) < 20:
                    blob_mismatches.append(relative)
            actual_mode = (
                "120000"
                if kind == "symlink"
                else "100755" if kind == "executable" else "100644"
            )
            if actual_mode != expected.get("mode") and len(mode_mismatches) < 20:
                mode_mismatches.append(relative)

    expected_paths = set(git_entries or {})
    missing = sorted(expected_paths - local_paths)
    extra = sorted(local_paths - expected_paths)
    commit_tree_exact = bool(git_entries) and not (
        missing or extra or blob_mismatches or mode_mismatches
    )
    return {
        "path": str(source_root),
        "exists": True,
        "file_count": file_count,
        "regular_file_count": regular_file_count,
        "symlink_count": symlink_count,
        "total_bytes": total_bytes,
        "tree_manifest_sha256": manifest.hexdigest(),
        "lfs_pointer_count": lfs_pointer_count,
        "native_deploy_lfs_pointer_count": native_deploy_lfs_pointer_count,
        "native_robot_model_lfs_pointer_count": native_robot_model_lfs_pointer_count,
        "lfs_pointer_claimed_content_bytes": lfs_claimed_bytes,
        "lfs_pointer_paths_sha256": pointer_paths.hexdigest(),
        "lfs_pointer_groups": [
            {"path_prefix": prefix, "count": count}
            for prefix, count in sorted(
                lfs_groups.items(), key=lambda item: (-item[1], item[0])
            )
        ],
        "expected_git_entry_count": (
            len(expected_paths) if git_entries is not None else None
        ),
        "missing_from_extracted_tree_count": len(missing),
        "extra_in_extracted_tree_count": len(extra),
        "blob_mismatch_count": len(blob_mismatches),
        "mode_mismatch_count": len(mode_mismatches),
        "missing_from_extracted_tree_sample": missing[:20],
        "extra_in_extracted_tree_sample": extra[:20],
        "blob_mismatch_sample": blob_mismatches,
        "mode_mismatch_sample": mode_mismatches,
        "commit_tree_exact_match": commit_tree_exact,
    }


CPU_WORKER = r"""
import hashlib
import json
import resource
import statistics
import sys
import time

import numpy as np
import onnxruntime as ort

models = json.loads(sys.argv[1])
warmups = int(sys.argv[2])
runs = int(sys.argv[3])
result = {
    "python_executable": sys.executable,
    "python_version": sys.version.split()[0],
    "onnxruntime_version": ort.__version__,
    "available_providers": ort.get_available_providers(),
    "requested_provider": "CPUExecutionProvider",
    "warmup_runs_per_model": warmups,
    "measured_runs_per_model": runs,
    "models": {},
}

options = ort.SessionOptions()
options.intra_op_num_threads = 1
options.inter_op_num_threads = 1
options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL

for name, path in models.items():
    session = ort.InferenceSession(
        path,
        sess_options=options,
        providers=["CPUExecutionProvider"],
    )
    inputs = session.get_inputs()
    outputs = session.get_outputs()
    if len(inputs) != 1 or len(outputs) != 1:
        raise RuntimeError(f"{name} expected one input and one output")
    input_shape = [int(value) for value in inputs[0].shape]
    feed = {inputs[0].name: np.zeros(input_shape, dtype=np.float32)}
    for _ in range(warmups):
        session.run(None, feed)
    timings_ms = []
    output = None
    for _ in range(runs):
        started = time.perf_counter_ns()
        output = session.run(None, feed)[0]
        timings_ms.append((time.perf_counter_ns() - started) / 1_000_000.0)
    result["models"][name] = {
        "inputs": [
            {"name": item.name, "shape": list(item.shape), "type": item.type}
            for item in inputs
        ],
        "outputs": [
            {"name": item.name, "shape": list(item.shape), "type": item.type}
            for item in outputs
        ],
        "output_shape_observed": list(output.shape),
        "output_dtype_observed": str(output.dtype),
        "output_all_finite": bool(np.isfinite(output).all()),
        "zero_output_sha256": hashlib.sha256(output.tobytes()).hexdigest(),
        "latency_ms": {
            "minimum": min(timings_ms),
            "median": statistics.median(timings_ms),
            "maximum": max(timings_ms),
        },
    }

result["model_forwards"] = len(models) * (warmups + runs)
result["max_rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
print(json.dumps(result, sort_keys=True))
"""


def run_cpu_structural_inference(
    *,
    python_executable: Path,
    artifacts: Mapping[str, Mapping[str, Any]],
    warmups: int = 2,
    runs: int = 20,
    runner: CommandRunner = subprocess.run,
) -> dict[str, Any]:
    models = {
        name: str(row["path"])
        for name, row in artifacts.items()
        if name in EXPECTED_INTERFACES
    }
    command = [
        str(python_executable),
        "-c",
        CPU_WORKER,
        json.dumps(models, sort_keys=True),
        str(warmups),
        str(runs),
    ]
    try:
        completed = runner(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "executed": False,
            "error": str(exc),
            "model_forwards": 0,
            "contract_matches": False,
        }
    if completed.returncode != 0:
        return {
            "executed": False,
            "returncode": completed.returncode,
            "stdout": completed.stdout[-2000:],
            "stderr": completed.stderr[-4000:],
            "model_forwards": 0,
            "contract_matches": False,
        }
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return {
            "executed": False,
            "error": f"invalid worker JSON: {exc}",
            "stdout": completed.stdout[-2000:],
            "model_forwards": 0,
            "contract_matches": False,
        }
    return validate_inference_report(report)


def validate_inference_report(report: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(report)
    checks: dict[str, Any] = {}
    models = report.get("models", {})
    for name, expected in EXPECTED_INTERFACES.items():
        observed = models.get(name, {})
        inputs = observed.get("inputs", [])
        outputs = observed.get("outputs", [])
        checks[name] = {
            "single_input_output": len(inputs) == 1 and len(outputs) == 1,
            "input_name_matches": bool(inputs)
            and inputs[0].get("name") == expected["input_name"],
            "input_shape_matches": bool(inputs)
            and inputs[0].get("shape") == expected["input_shape"],
            "output_name_matches": bool(outputs)
            and outputs[0].get("name") == expected["output_name"],
            "output_shape_matches": bool(outputs)
            and outputs[0].get("shape") == expected["output_shape"],
            "observed_output_shape_matches": observed.get("output_shape_observed")
            == expected["output_shape"],
            "output_all_finite": observed.get("output_all_finite") is True,
            "zero_output_sha256_matches": observed.get("zero_output_sha256")
            == expected["zero_output_sha256"],
        }
        checks[name]["passed"] = all(checks[name].values())
    result["contract_checks"] = checks
    result["executed"] = True
    result["contract_matches"] = bool(checks) and all(
        row["passed"] for row in checks.values()
    )
    result["quality_boundary"] = (
        "All-zero observations verify file integrity, interfaces, deterministic "
        "CPU execution, and finite outputs only. They are not valid robot "
        "observations or evidence of behavior, stability, real-time performance, "
        "physics success, or task success."
    )
    return result


def _find_binary(name: str, candidates: Sequence[Path] = ()) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def _glob_existing(patterns: Iterable[str]) -> list[str]:
    found: set[str] = set()
    for pattern in patterns:
        for path in Path("/").glob(pattern.lstrip("/")):
            if path.is_file():
                found.add(str(path))
    return sorted(found)


def probe_host_capabilities(
    *,
    probe_context: str,
    runner: CommandRunner = subprocess.run,
) -> dict[str, Any]:
    binaries = {
        "cmake": _find_binary("cmake"),
        "uv": _find_binary("uv"),
        "g++": _find_binary("g++"),
        "docker": _find_binary("docker"),
        "nvidia-smi": _find_binary("nvidia-smi"),
        "nvcc": _find_binary(
            "nvcc",
            (
                Path("/usr/local/cuda/bin/nvcc"),
                Path("/usr/local/cuda-13.0/bin/nvcc"),
            ),
        ),
    }
    gpu_probe = (
        _run_command(
            [
                binaries["nvidia-smi"],
                "--query-gpu=index,name,memory.total,memory.used,utilization.gpu,driver_version",
                "--format=csv,noheader,nounits",
            ],
            runner=runner,
        )
        if binaries["nvidia-smi"]
        else {"succeeded": False, "stderr": "nvidia-smi not found"}
    )
    gpu_rows = []
    if gpu_probe.get("succeeded"):
        for line in gpu_probe.get("stdout", "").splitlines():
            match = NVIDIA_SMI_ROW.match(line.strip())
            if match:
                values = match.groupdict()
                gpu_rows.append(
                    {
                        "index": int(values["index"]),
                        "name": values["name"],
                        "memory_total_mib": int(values["memory_total"]),
                        "memory_used_mib": int(values["memory_used"]),
                        "utilization_percent": int(values["utilization"]),
                        "driver_version": values["driver"].strip(),
                    }
                )
    nvcc_probe = (
        _run_command([binaries["nvcc"], "--version"], runner=runner)
        if binaries["nvcc"]
        else {"succeeded": False, "stderr": "nvcc not found"}
    )
    cmake_probe = (
        _run_command([binaries["cmake"], "--version"], runner=runner)
        if binaries["cmake"]
        else {"succeeded": False, "stderr": "cmake not found"}
    )
    docker_probe = (
        _run_command([binaries["docker"], "version"], runner=runner)
        if binaries["docker"]
        else {"succeeded": False, "stderr": "docker not found"}
    )
    tensorrt = {
        "headers": _glob_existing(
            (
                "/usr/include/NvInfer.h",
                "/usr/local/include/NvInfer.h",
                "/usr/local/TensorRT*/include/NvInfer.h",
                "/usr/local/MATLAB/*/sys/cuda/glnxa64/tensorrt/include/NvInfer.h",
            )
        ),
        "nvinfer": _glob_existing(
            (
                "/usr/lib/x86_64-linux-gnu/libnvinfer.so*",
                "/usr/local/lib/libnvinfer.so*",
                "/usr/local/MATLAB/*/bin/glnxa64/libnvinfer.so*",
            )
        ),
        "nvinfer_plugin": _glob_existing(
            (
                "/usr/lib/x86_64-linux-gnu/libnvinfer_plugin.so*",
                "/usr/local/lib/libnvinfer_plugin.so*",
                "/usr/local/MATLAB/*/bin/glnxa64/libnvinfer_plugin.so*",
            )
        ),
        "nvonnxparser": _glob_existing(
            (
                "/usr/lib/x86_64-linux-gnu/libnvonnxparser.so*",
                "/usr/local/lib/libnvonnxparser.so*",
                "/usr/local/MATLAB/*/bin/glnxa64/libnvonnxparser.so*",
            )
        ),
        "nvparsers": _glob_existing(
            (
                "/usr/lib/x86_64-linux-gnu/libnvparsers.so*",
                "/usr/local/lib/libnvparsers.so*",
                "/usr/local/MATLAB/*/bin/glnxa64/libnvparsers.so*",
            )
        ),
    }
    tensorrt["complete_for_source_find_module"] = all(
        tensorrt[name]
        for name in (
            "headers",
            "nvinfer",
            "nvinfer_plugin",
            "nvonnxparser",
            "nvparsers",
        )
    )
    onnxruntime_cpp = {
        "headers": _glob_existing(
            (
                "/usr/include/onnxruntime*/onnxruntime_cxx_api.h",
                "/usr/local/include/onnxruntime*/onnxruntime_cxx_api.h",
            )
        ),
        "libraries": _glob_existing(
            (
                "/usr/lib/x86_64-linux-gnu/libonnxruntime.so*",
                "/usr/local/lib/libonnxruntime.so*",
            )
        ),
    }
    onnxruntime_cpp["complete"] = bool(
        onnxruntime_cpp["headers"] and onnxruntime_cpp["libraries"]
    )
    return {
        "probe_context": probe_context,
        "platform": platform.platform(),
        "binaries": binaries,
        "gpu": {
            "accessible": bool(gpu_rows),
            "devices": gpu_rows,
            "probe": gpu_probe,
        },
        "cuda_toolkit": {
            "nvcc_available": nvcc_probe.get("succeeded") is True,
            "nvcc_path": binaries["nvcc"],
            "probe": nvcc_probe,
        },
        "cmake": {
            "available": cmake_probe.get("succeeded") is True,
            "path": binaries["cmake"],
            "probe": cmake_probe,
        },
        "uv": {"available": binaries["uv"] is not None, "path": binaries["uv"]},
        "cxx": {"available": binaries["g++"] is not None, "path": binaries["g++"]},
        "docker": {
            "client_available": binaries["docker"] is not None,
            "daemon_accessible": docker_probe.get("succeeded") is True,
            "probe": docker_probe,
        },
        "tensorrt": tensorrt,
        "onnxruntime_cpp": onnxruntime_cpp,
    }


def _xml_joint_actuator_summary(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path), "exists": False}
    root = ET.parse(path).getroot()
    joints = root.findall(".//joint")
    actuators = root.findall(".//actuator/*")
    hand_tokens = ("hand", "thumb", "index", "middle")

    def is_hand(name: str | None) -> bool:
        lowered = (name or "").lower()
        return any(token in lowered for token in hand_tokens)

    hand_joints = [item.get("name") for item in joints if is_hand(item.get("name"))]
    hand_actuators = [
        item.get("name") for item in actuators if is_hand(item.get("name"))
    ]
    return {
        "path": str(path),
        "exists": True,
        "joint_elements": len(joints),
        "actuator_count": len(actuators),
        "hand_joint_count": len(hand_joints),
        "hand_actuator_count": len(hand_actuators),
        "hand_joint_names": hand_joints,
        "hand_actuator_names": hand_actuators,
    }


def inspect_control_boundary(source_root: Path) -> dict[str, Any]:
    deploy = source_root / "gear_sonic_deploy"
    body_model = _xml_joint_actuator_summary(deploy / "g1" / "g1_29dof.xml")
    hand_model = _xml_joint_actuator_summary(deploy / "g1" / "g1_29dof_with_hand.xml")
    controller = deploy / "src/g1/g1_deploy_onnx_ref/src/g1_deploy_onnx_ref.cpp"
    hand_header = deploy / "src/g1/g1_deploy_onnx_ref/include/dex3_hands.hpp"
    controller_text = controller.read_text(encoding="utf-8", errors="replace")
    hand_text = hand_header.read_text(encoding="utf-8", errors="replace")
    markers = {
        "external_left_hand_pose": "GetHandPose(true)" in controller_text,
        "external_right_hand_pose": "GetHandPose(false)" in controller_text,
        "separate_hand_command": "setAllJointsCommand" in controller_text,
        "hand_delta_limit_0_25_rad": "MAX_DELTA_Q = 0.25" in hand_text,
        "hand_close_ratio_limit": "max_close_ratio_" in hand_text,
        "object_contact_feedback": any(
            token in hand_text
            for token in ("contact_force", "object_contact", "penetration_depth")
        ),
    }
    return {
        "policy_action_dimension": 29,
        "control_frequency_hz": 50,
        "body_only_mujoco_model": body_model,
        "with_hand_mujoco_model": hand_model,
        "source_markers": markers,
        "sonic_policy_controls_dex3_fingers": False,
        "dex3_targets_are_external_inputs": all(
            markers[name]
            for name in (
                "external_left_hand_pose",
                "external_right_hand_pose",
                "separate_hand_command",
            )
        ),
        "contact_aware_grasp_closed_loop_present": markers["object_contact_feedback"],
        "boundary": (
            "The staged v1.1 policy emits 29 body targets. The repository also "
            "contains a 43-actuator MuJoCo model with 14 hand actuators, but the "
            "deployment code receives those hand targets from an external input "
            "interface. This does not provide an autonomous, contact-aware grasp "
            "controller."
        ),
    }


def build_gates(
    *,
    artifacts: Mapping[str, Mapping[str, Any]],
    source_tree: Mapping[str, Any],
    inference: Mapping[str, Any],
    host: Mapping[str, Any],
    control: Mapping[str, Any],
    planner_present: bool,
) -> tuple[dict[str, bool], list[dict[str, str]]]:
    policy_weights_ready = all(
        artifacts[name]["ready"]
        for name in ("model_encoder", "model_decoder", "observation_config")
    )
    cpu_ready = policy_weights_ready and inference.get("contract_matches") is True
    native_conditions = {
        "source_tree_matches_commit": source_tree.get("commit_tree_exact_match")
        is True,
        "native_deploy_lfs_objects_materialized": source_tree.get(
            "native_deploy_lfs_pointer_count"
        )
        == 0,
        "gpu_accessible_in_probe_context": host["gpu"]["accessible"] is True,
        "cuda_compiler_available": host["cuda_toolkit"]["nvcc_available"] is True,
        "cmake_available": host["cmake"]["available"] is True,
        "tensorrt_complete": host["tensorrt"]["complete_for_source_find_module"]
        is True,
        "onnxruntime_cpp_complete": host["onnxruntime_cpp"]["complete"] is True,
        "planner_present_and_reviewed": planner_present,
        "policy_weights_ready": policy_weights_ready,
    }
    official_native_ready = all(native_conditions.values())
    grasp_conditions = {
        "official_native_runtime_ready": official_native_ready,
        "physical_hand_model_exists": control["with_hand_mujoco_model"].get(
            "hand_actuator_count"
        )
        == 14,
        "common_external_hand_controller_frozen": False,
        "contact_aware_grasp_loop_present": control[
            "contact_aware_grasp_closed_loop_present"
        ]
        is True,
        "matched_grasp_task_integrated": False,
    }
    gates = {
        "policy_weights_ready": policy_weights_ready,
        "cpu_structural_inference_ready": cpu_ready,
        "official_native_runtime_ready": official_native_ready,
        "grasp_ab_ready": all(grasp_conditions.values()),
        "production_accepted": False,
        "learning_validated": False,
        "long_run_authorized": False,
    }
    blockers: list[dict[str, str]] = []
    for name, passed in native_conditions.items():
        if not passed:
            blockers.append(
                {"gate": "official_native_runtime_ready", "condition": name}
            )
    for name, passed in grasp_conditions.items():
        if not passed:
            blockers.append({"gate": "grasp_ab_ready", "condition": name})
    return (
        {
            **gates,
            "native_conditions": native_conditions,
            "grasp_conditions": grasp_conditions,
        },
        blockers,
    )


def run_audit(
    *,
    run_root: Path,
    cpu_python: Path,
    source_git_dir: Path | None = None,
    output_path: Path | None = None,
    observed_at: str | None = None,
    probe_context: str = "current_process",
) -> dict[str, Any]:
    run_root = run_root.resolve()
    output_path = output_path or run_root / "SONIC_READMISSION.json"
    stamp = observed_at or datetime.now(timezone.utc).isoformat()
    artifacts = inspect_artifacts(run_root)
    git_entries: Mapping[str, Mapping[str, str]] | None = None
    if source_git_dir is not None:
        git_entries, git_identity = load_git_tree(source_git_dir, SOURCE_COMMIT)
    else:
        git_identity = {
            "git_dir": None,
            "commit": SOURCE_COMMIT,
            "commit_object_available": False,
            "error": "source_git_dir not supplied",
        }
    source_tree = inspect_source_tree(
        run_root / "source",
        git_entries=git_entries,
    )
    source_tree["git_identity"] = git_identity
    inference = run_cpu_structural_inference(
        python_executable=cpu_python,
        artifacts=artifacts,
    )
    host = probe_host_capabilities(probe_context=probe_context)
    control = inspect_control_boundary(run_root / "source")
    planner_path = run_root / PLANNER_POLICY["relative_path"]
    planner_present = planner_path.is_file()
    gates, blockers = build_gates(
        artifacts=artifacts,
        source_tree=source_tree,
        inference=inference,
        host=host,
        control=control,
        planner_present=planner_present,
    )
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "observed_at": stamp,
        "run_root": str(run_root),
        "implementation": {
            "path": str(Path(__file__).resolve()),
            "sha256": sha256_file(Path(__file__).resolve()),
        },
        "audit_scope": {
            "input_mutation": False,
            "network_accessed": False,
            "downloads": 0,
            "physics_steps": 0,
            "rendered_frames": 0,
            "training_steps": 0,
            "model_forwards": inference.get("model_forwards", 0),
        },
        "source_identity": {
            "repository": SOURCE_REPOSITORY,
            "expected_commit": SOURCE_COMMIT,
            "recorded_git_archive_sha256": SOURCE_ARCHIVE_SHA256,
            "recorded_archive_present": False,
            "source_tree": source_tree,
        },
        "model_identity": {
            "repository": HF_REPOSITORY,
            "revision": HF_REVISION,
            "variant": "sonic_v1_1",
            "artifacts": artifacts,
            "planner": {
                **PLANNER_POLICY,
                "path": str(planner_path),
                "present": planner_present,
                "reviewed_for_execution": False,
            },
            "training_checkpoint": TRAINING_CHECKPOINT_POLICY,
        },
        "cpu_structural_inference": inference,
        "host_capabilities": host,
        "control_boundary": control,
        "gates": gates,
        "blockers": blockers,
        "next_actions": [
            "Use the verified CPU interfaces to implement semantic observation assembly and 29-body-joint action scaling in a non-actuating shadow path.",
            "For an official native smoke, provision CMake, complete TensorRT and ONNX Runtime C++ dependencies, review the planner artifact, and materialize only the required LFS objects on a GPU-visible execution path.",
            "Before any grasp A/B, freeze one shared physical Dex3 model and one shared external hand controller; compare body control without mixing finger controllers.",
        ],
        "claim_boundary": (
            "This report establishes staged artifact integrity, exact extracted "
            "source-tree identity when the local Git object store is supplied, "
            "CPU structural executability, host dependency status, and control "
            "boundaries. It is not an official native reproduction, physics "
            "result, behavior result, grasp result, production admission, or "
            "learning validation."
        ),
    }
    report["content_sha256_excluding_this_field"] = canonical_sha256(report)
    write_json_atomic(output_path, report)
    return report


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--cpu-python", type=Path, required=True)
    parser.add_argument("--source-git-dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--observed-at")
    parser.add_argument("--probe-context", default="current_process")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    report = run_audit(
        run_root=args.run_root,
        cpu_python=args.cpu_python,
        source_git_dir=args.source_git_dir,
        output_path=args.output,
        observed_at=args.observed_at,
        probe_context=args.probe_context,
    )
    print(
        json.dumps(
            {
                "output": str(args.output or args.run_root / "SONIC_READMISSION.json"),
                "gates": report["gates"],
                "model_forwards": report["audit_scope"]["model_forwards"],
                "physics_steps": report["audit_scope"]["physics_steps"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
