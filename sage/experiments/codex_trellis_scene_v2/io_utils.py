from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def extract_json(text: str) -> dict[str, Any]:
    value = text.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?", "", value).strip()
        value = re.sub(r"```$", "", value).strip()
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        start = value.find("{")
        end = value.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(value[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("Codex response must be a JSON object")
    return parsed


def slugify(value: str, fallback: str = "scene") -> str:
    slug = re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_").lower()
    return slug or fallback


def run_codex_json(
    prompt: str,
    output_dir: Path,
    *,
    stage: str,
    model: str,
    timeout: int = 600,
) -> dict[str, Any]:
    """Run one isolated Codex JSON stage with explicit artifacts and no fallback."""

    stage_dir = output_dir / "codex" / slugify(stage)
    stage_dir.mkdir(parents=True, exist_ok=True)
    request_path = stage_dir / "request.txt"
    response_path = stage_dir / "response.txt"
    request_path.write_text(prompt, encoding="utf-8")
    cmd = [
        "codex",
        "exec",
        "--model",
        model,
        "--ignore-user-config",
        "--ignore-rules",
        "--disable",
        "plugins",
        "--disable",
        "plugin_sharing",
        "--disable",
        "plugin_hooks",
        "-c",
        'model_reasoning_effort="low"',
        "--ephemeral",
        "--cd",
        str(Path.cwd()),
        "--sandbox",
        "read-only",
        "--output-last-message",
        str(response_path),
        prompt,
    ]
    proc = subprocess.run(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=int(os.environ.get("SAGE_CODEX_TIMEOUT", str(timeout))),
        check=False,
    )
    (stage_dir / "stdout.txt").write_text(proc.stdout, encoding="utf-8")
    (stage_dir / "stderr.txt").write_text(proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(
            f"Codex stage {stage!r} failed with code {proc.returncode}; "
            f"see {stage_dir / 'stderr.txt'}"
        )
    if not response_path.is_file():
        raise RuntimeError(f"Codex stage {stage!r} did not write {response_path}")
    return extract_json(response_path.read_text(encoding="utf-8"))
