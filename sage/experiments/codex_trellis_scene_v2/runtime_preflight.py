"""Verify every locked Scene V2 production runtime before work starts."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

from .content_chain import content_hash, file_binding
from .io_utils import write_json


LOCK_SCHEMA = "scene-v2-runtime-lock/v1"
LOCK_KEYS = {
    "schema",
    "release_manifest",
    "environments",
    "trellis",
    "model",
    "blender",
    "blender_tools",
}


def validate_runtime_lock_document(lock: dict[str, Any]) -> None:
    if lock.get("schema") != LOCK_SCHEMA:
        raise ValueError("runtime lock schema mismatch")
    if set(lock) != LOCK_KEYS:
        raise ValueError(f"runtime lock fields mismatch: {sorted(set(lock) ^ LOCK_KEYS)}")
    for name in ("orchestrator", "trellis", "research"):
        environment = lock.get("environments", {}).get(name)
        if not isinstance(environment, dict):
            raise ValueError(f"runtime environment missing: {name}")
        required = {"executable", "python", "pip_freeze_sha256"}
        if not required <= set(environment):
            raise ValueError(f"runtime environment fields missing: {name}")
    if set(lock.get("trellis", {})) != {"repository", "commit", "working_tree_patch_sha256"}:
        raise ValueError("TRELLIS repository lock fields mismatch")
    if set(lock.get("model", {})) != {"fingerprint"}:
        raise ValueError("model lock fields mismatch")
    if not isinstance(lock.get("blender_tools"), list) or not lock["blender_tools"]:
        raise ValueError("Blender tool bindings are required")


def _run(argv: list[str], *, cwd: Path | None = None, timeout: int = 300) -> subprocess.CompletedProcess[Any]:
    return subprocess.run(argv, cwd=cwd, check=False, capture_output=True, timeout=timeout)


def _probe_environment(executable: Path, *, probe_torch: bool) -> dict[str, Any]:
    source = (
        "import json,platform,sys;"
        "o={'python':platform.python_version(),'executable':sys.executable};"
        + (
            "import torch;o.update(torch=str(torch.__version__),torch_cuda=str(torch.version.cuda));"
            if probe_torch
            else ""
        )
        + "print(json.dumps(o,sort_keys=True))"
    )
    details = _run([str(executable), "-c", source])
    freeze = _run([str(executable), "-m", "pip", "freeze"])
    if details.returncode != 0 or freeze.returncode != 0:
        return {
            "ok": False,
            "probe_returncode": details.returncode,
            "freeze_returncode": freeze.returncode,
        }
    try:
        result = json.loads(details.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"ok": False, "probe_parse_failed": True}
    lines = sorted(
        line for line in freeze.stdout.decode("utf-8", errors="replace").splitlines() if line.strip()
    )
    result.update(ok=True, pip_freeze_sha256=content_hash(lines), pip_freeze_count=len(lines))
    return result


def _git_binding(repository: Path) -> dict[str, Any]:
    head = _run(["git", "rev-parse", "HEAD"], cwd=repository, timeout=30)
    patch = _run(["git", "diff", "--binary", "HEAD"], cwd=repository, timeout=120)
    return {
        "ok": head.returncode == 0 and patch.returncode == 0,
        "commit": head.stdout.decode("utf-8", errors="replace").strip(),
        "working_tree_patch_sha256": hashlib.sha256(patch.stdout).hexdigest(),
    }


def verify_runtime_lock(lock_path: Path, *, verify_model_bytes: bool = True) -> dict[str, Any]:
    reasons: list[str] = []
    checks: dict[str, Any] = {}
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        validate_runtime_lock_document(lock)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return {
            "schema": "scene-v2-runtime-preflight/v1",
            "ok": False,
            "reasons": [f"runtime_lock_invalid:{type(exc).__name__}:{exc}"],
            "checks": {},
            "lock": str(lock_path),
        }

    def check(name: str, actual: Any, expected: Any) -> None:
        ok = actual == expected
        checks[name] = {"ok": ok, "actual": actual, "expected": expected}
        if not ok:
            reasons.append(f"{name}_mismatch")

    release_lock = lock["release_manifest"]
    manifest_path = Path(str(release_lock["path"]))
    if not manifest_path.is_file():
        reasons.append("release_manifest_missing")
        manifest = None
    else:
        check("release_manifest_binding", file_binding(manifest_path), release_lock["binding"])
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = None
            reasons.append("release_manifest_invalid_json")
    if isinstance(manifest, dict):
        fingerprint_payload = {key: value for key, value in manifest.items() if key != "content_fingerprint"}
        check("release_manifest_content_fingerprint", content_hash(fingerprint_payload), manifest.get("content_fingerprint"))
        check("release_manifest_schema", manifest.get("schema"), "scene-v2-release-manifest/v1")

    for name, expected in lock["environments"].items():
        executable = Path(str(expected["executable"]))
        actual = _probe_environment(executable, probe_torch=name in {"orchestrator", "trellis"}) if executable.is_file() else {"ok": False}
        checks[f"environment_{name}"] = {"ok": bool(actual.get("ok")), "actual": actual, "expected": expected}
        if not actual.get("ok"):
            reasons.append(f"environment_{name}_probe_failed")
            continue
        for field in ("python", "pip_freeze_sha256", "torch", "torch_cuda"):
            if field in expected and actual.get(field) != expected[field]:
                reasons.append(f"environment_{name}_{field}_mismatch")
                checks[f"environment_{name}"]["ok"] = False
        if name == "orchestrator":
            check("orchestrator_current_executable", str(Path(sys.executable).resolve()), str(executable.resolve()))
            check("orchestrator_current_python", platform.python_version(), expected["python"])

    trellis_expected = lock["trellis"]
    trellis_actual = _git_binding(Path(str(trellis_expected["repository"])))
    checks["trellis_repository"] = {"ok": bool(trellis_actual["ok"]), "actual": trellis_actual, "expected": trellis_expected}
    for field in ("commit", "working_tree_patch_sha256"):
        if trellis_actual.get(field) != trellis_expected.get(field):
            reasons.append(f"trellis_{field}_mismatch")
            checks["trellis_repository"]["ok"] = False
    if isinstance(manifest, dict):
        external = manifest.get("external_trellis", {})
        check("trellis_manifest_commit", external.get("commit"), trellis_expected["commit"])
        check("trellis_manifest_patch", external.get("working_tree_patch_sha256"), trellis_expected["working_tree_patch_sha256"])
        check("trellis_compatibility_patch_applied", external.get("compatibility_patch_bundle", {}).get("matches_current_working_tree_patch"), True)
        check("model_manifest_fingerprint", manifest.get("model", {}).get("fingerprint"), lock["model"]["fingerprint"])

    blender = Path(str(lock["blender"]["path"]))
    blender_actual = file_binding(blender) if blender.is_file() else None
    check("blender_binary", blender_actual, lock["blender"]["binding"])
    for index, expected in enumerate(lock["blender_tools"]):
        path = Path(str(expected["path"]))
        check(f"blender_tool_{index}", file_binding(path) if path.is_file() else None, expected["binding"])

    if isinstance(manifest, dict) and verify_model_bytes:
        model_root = Path(str(manifest.get("model", {}).get("path") or ""))
        files = manifest.get("model", {}).get("files", [])
        model_ok = model_root.is_dir() and isinstance(files, list)
        checked_files = 0
        if not model_ok:
            reasons.append("model_root_or_manifest_files_missing")
        if model_ok:
            expected_paths = [str(item.get("path") or "") for item in files]
            actual_paths = sorted(
                path.relative_to(model_root).as_posix()
                for path in model_root.rglob("*")
                if path.is_file()
            )
            if actual_paths != expected_paths:
                reasons.append("model_file_set_mismatch")
                model_ok = False
        actual_records: list[dict[str, Any]] = []
        if model_ok:
            for item in files:
                path = model_root / str(item.get("path") or "")
                expected = {"bytes": item.get("bytes"), "sha256": item.get("sha256")}
                if not path.is_file() or file_binding(path) != expected:
                    reasons.append(f"model_file_mismatch:{item.get('path')}")
                    model_ok = False
                    break
                actual_records.append({"path": item["path"], **expected})
                checked_files += 1
        if model_ok and content_hash(actual_records) != lock["model"]["fingerprint"]:
            reasons.append("model_content_fingerprint_mismatch")
            model_ok = False
        checks["model_files"] = {"ok": model_ok, "checked_files": checked_files}
    else:
        checks["model_files"] = {"ok": True, "skipped_byte_verification": True}

    return {
        "schema": "scene-v2-runtime-preflight/v1",
        "ok": not reasons,
        "reasons": reasons,
        "checks": checks,
        "lock": str(lock_path.resolve()),
        "verify_model_bytes": bool(verify_model_bytes),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--skip-model-bytes", action="store_true")
    args = parser.parse_args()
    report = verify_runtime_lock(args.lock, verify_model_bytes=not args.skip_model_bytes)
    write_json(args.output, report)
    print(json.dumps({"ok": report["ok"], "reasons": report["reasons"], "output": str(args.output)}))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
