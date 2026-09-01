"""Canonical content keys and artifact certificates for resumable stages."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA = "scene-v2-content-certificate/v1"


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def file_binding(path: Path) -> dict[str, Any]:
    return {
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def build_generation_contract(
    *,
    category: str,
    prompt: str,
    target_dimensions_m: dict[str, Any],
    seed: int,
    model_fingerprint: str,
    rmbg_fingerprint: str,
    pipeline_type: str,
    steps: int,
    texture_size: int,
    decimation_target: int,
    preprocess_image: bool,
    code_version: str,
    reference_image: Path | None = None,
) -> dict[str, Any]:
    contract: dict[str, Any] = {
        "schema": "scene-v2-generation-contract/v1",
        "category": str(category),
        "prompt": str(prompt),
        "target_dimensions_m": target_dimensions_m,
        "seed": int(seed),
        "model_fingerprint": str(model_fingerprint),
        "rmbg_fingerprint": str(rmbg_fingerprint),
        "pipeline": {
            "type": str(pipeline_type),
            "steps": int(steps),
            "texture_size": int(texture_size),
            "decimation_target": int(decimation_target),
            "preprocess_image": bool(preprocess_image),
        },
        "code_version": str(code_version),
        "reference_image": file_binding(reference_image) if reference_image else None,
    }
    contract["content_key"] = content_hash(contract)
    return contract


def make_artifact_certificate(
    artifact: Path,
    *,
    upstream: dict[str, Any],
    rules: dict[str, Any],
    evidence: dict[str, Path] | None = None,
) -> dict[str, Any]:
    certificate: dict[str, Any] = {
        "schema": SCHEMA,
        "artifact": file_binding(artifact),
        "upstream": upstream,
        "rules": rules,
        "evidence": {
            name: file_binding(path) for name, path in sorted((evidence or {}).items())
        },
    }
    certificate["certificate_hash"] = content_hash(certificate)
    return certificate


def verify_artifact_certificate(
    certificate: dict[str, Any],
    artifact: Path,
    *,
    upstream: dict[str, Any],
    rules: dict[str, Any],
    evidence: dict[str, Path] | None = None,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if certificate.get("schema") != SCHEMA:
        reasons.append("certificate_schema_mismatch")
    expected = make_artifact_certificate(
        artifact,
        upstream=upstream,
        rules=rules,
        evidence=evidence,
    )
    for key in ("artifact", "upstream", "rules", "evidence", "certificate_hash"):
        if certificate.get(key) != expected.get(key):
            reasons.append(f"{key}_mismatch")
    return not reasons, reasons
