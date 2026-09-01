"""Create a machine-readable, content-addressed Scene V2 release manifest.

The manifest deliberately records external repositories and model files by content,
not merely by path.  It never serializes arbitrary environment variables.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import platform
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Iterable


SAFE_RUNTIME_ENV = (
    "ATTN_BACKEND",
    "SPARSE_ATTN_BACKEND",
    "SPARSE_CONV_BACKEND",
    "HF_HOME",
    "HF_HUB_CACHE",
)


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _run(argv: list[str], cwd: Path | None = None, timeout: int = 120) -> dict[str, Any]:
    try:
        result = subprocess.run(
            argv,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "argv": argv,
            "returncode": result.returncode,
            # Git porcelain uses a leading space as part of its XY status.  Keep
            # leading bytes intact while removing only line terminators.
            "stdout": result.stdout.rstrip("\r\n"),
            "stderr": result.stderr.strip(),
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"argv": argv, "returncode": None, "error": f"{type(exc).__name__}: {exc}"}


def _git_state(repo: Path) -> dict[str, Any]:
    head = _run(["git", "rev-parse", "HEAD"], cwd=repo)
    status = _run(["git", "status", "--short"], cwd=repo)
    try:
        diff = subprocess.run(
            ["git", "diff", "--binary", "HEAD"],
            cwd=repo,
            check=False,
            capture_output=True,
            timeout=120,
        )
        patch_bytes = diff.stdout if diff.returncode == 0 else b""
    except (OSError, subprocess.TimeoutExpired):
        patch_bytes = b""
    return {
        "path": str(repo.resolve()),
        "commit": head.get("stdout") if head.get("returncode") == 0 else None,
        "dirty": bool(status.get("stdout")),
        "status": status.get("stdout", "").splitlines(),
        "working_tree_patch_sha256": hashlib.sha256(patch_bytes).hexdigest(),
    }


def _file_records(paths: Iterable[Path], base: Path) -> list[dict[str, Any]]:
    records = []
    for path in sorted(paths, key=lambda item: item.as_posix()):
        if not path.is_file():
            continue
        records.append(
            {
                "path": path.relative_to(base).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return records


def _model_fingerprint(model_root: Path) -> dict[str, Any]:
    files = _file_records((path for path in model_root.rglob("*") if path.is_file()), model_root)
    return {
        "path": str(model_root.resolve()),
        "file_count": len(files),
        "total_bytes": sum(item["bytes"] for item in files),
        "files": files,
        "fingerprint": canonical_hash(files),
    }


def _python_environment(executable: Path) -> dict[str, Any]:
    probe = (
        "import json,platform;"
        "names=['torch','trimesh','numpy','PIL','scipy','transformers','safetensors'];"
        "out={'python':platform.python_version(),'executable':__import__('sys').executable,'packages':{}};"
        "exec(\"for n in names:\\n try:\\n  m=__import__(n); out['packages'][n]=getattr(m,'__version__','unknown')\\n except Exception as e: out['packages'][n]='unavailable:'+type(e).__name__\");"
        "exec(\"try:\\n import torch\\n out['torch_cuda']=torch.version.cuda\\n out['cuda_available']=torch.cuda.is_available()\\nexcept Exception: pass\");"
        "print(json.dumps(out,sort_keys=True))"
    )
    version = _run([str(executable), "-c", probe])
    freeze = _run([str(executable), "-m", "pip", "freeze"], timeout=300)
    try:
        details = json.loads(version.get("stdout", "{}"))
    except json.JSONDecodeError:
        details = {"probe": version}
    freeze_lines = sorted(line for line in freeze.get("stdout", "").splitlines() if line.strip())
    details["pip_freeze"] = freeze_lines
    details["pip_freeze_sha256"] = canonical_hash(freeze_lines)
    return details


def build_manifest(
    repo: Path,
    trellis_repo: Path,
    model_root: Path,
    flow_python: Path,
    trellis_python: Path,
    blender: Path,
) -> dict[str, Any]:
    release = _git_state(repo)
    external = _git_state(trellis_repo)
    modified_paths = []
    for status_line in external["status"]:
        relative = status_line[3:].strip()
        candidate = trellis_repo / relative
        if candidate.is_file():
            modified_paths.append(candidate)
    external["modified_file_contents"] = _file_records(modified_paths, trellis_repo)
    external["modified_files_fingerprint"] = canonical_hash(external["modified_file_contents"])
    patch_bundle = (
        repo
        / "sage/experiments/codex_trellis_scene_v2/release"
        / "trellis2_75fbf018_sdpa_compat.patch.b64"
    )
    encoded_patch = patch_bundle.read_bytes()
    decoded_patch = base64.b64decode(encoded_patch, validate=False)
    external["compatibility_patch_bundle"] = {
        "path": patch_bundle.relative_to(repo).as_posix(),
        "base64_sha256": hashlib.sha256(encoded_patch).hexdigest(),
        "decoded_patch_sha256": hashlib.sha256(decoded_patch).hexdigest(),
        "decoded_bytes": len(decoded_patch),
        "matches_current_working_tree_patch": hashlib.sha256(decoded_patch).hexdigest()
        == external["working_tree_patch_sha256"],
    }

    blender_version = _run([str(blender), "--version"], timeout=30)
    nvidia = _run(
        ["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"],
        timeout=30,
    )
    manifest: dict[str, Any] = {
        "schema": "scene-v2-release-manifest/v1",
        "release_git": release,
        "external_trellis": external,
        "model": _model_fingerprint(model_root),
        "environments": {
            "orchestrator": _python_environment(flow_python),
            "trellis": _python_environment(trellis_python),
        },
        "blender": {
            "path": str(blender.resolve()),
            "version_output": blender_version.get("stdout", "").splitlines(),
            "binary_sha256": sha256_file(blender),
        },
        "cuda_driver_probe": nvidia,
        "runtime_config": {name: os.environ.get(name) for name in SAFE_RUNTIME_ENV},
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
    }
    manifest["content_fingerprint"] = canonical_hash(manifest)
    return manifest


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--trellis-repo", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, required=True)
    parser.add_argument("--flow-python", type=Path, required=True)
    parser.add_argument("--trellis-python", type=Path, required=True)
    parser.add_argument("--blender", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = build_manifest(
        args.repo,
        args.trellis_repo,
        args.model_root,
        args.flow_python,
        args.trellis_python,
        args.blender,
    )
    write_json_atomic(args.output, manifest)
    print(json.dumps({"output": str(args.output), "content_fingerprint": manifest["content_fingerprint"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
