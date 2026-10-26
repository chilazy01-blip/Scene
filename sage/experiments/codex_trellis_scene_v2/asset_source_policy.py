"""Fail-closed furniture source and generated-evidence admission policy."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .content_chain import content_hash, file_binding


SOURCE_POLICY_SCHEMA = "scene-v2-furniture-source-policy/v1"
REFERENCE_EVIDENCE_SCHEMA = "scene-v2-flux-trellis-reference-evidence/v1"
IMAGE_REFERENCE_EVIDENCE_SCHEMA = "scene-v2-image-trellis-reference-evidence/v2"
NATIVE_ALPHA_REFERENCE_EVIDENCE_SCHEMA = "scene-v2-image-trellis-reference-evidence/v3"
BUILTIN_EVIDENCE_SCHEMAS = (
    IMAGE_REFERENCE_EVIDENCE_SCHEMA,
    NATIVE_ALPHA_REFERENCE_EVIDENCE_SCHEMA,
)
REPROCESSED_BUILTIN_REFERENCE_ORIGIN = "reprocessed_builtin_imagegen_reference"
ALLOWED_REFERENCE_ORIGINS = {
    "flux_generated",
    "persisted_flux_generated_reference",
}
BUILTIN_REFERENCE_ORIGINS = {
    "builtin_imagegen_generated",
    "persisted_builtin_imagegen_reference",
}
REQUIRED_GENERATION_EVIDENCE = (
    "source_rgb",
    "prepared_rgba",
    "alpha_mask",
    "alpha_metadata",
    "normalized_white_rgb",
)
NATIVE_ALPHA_GENERATION_EVIDENCE = (
    "source_raw",
    "source_visible_white_rgb",
    "native_alpha_mask",
    "input_normalization_metadata",
)


def _bound_file_ok(record: Any) -> bool:
    if not isinstance(record, dict) or not str(record.get("path") or ""):
        return False
    try:
        path = Path(str(record["path"])).expanduser()
        if not path.is_file():
            return False
        actual = file_binding(path)
        size = int(record.get("bytes", -1))
    except (OSError, ValueError, TypeError, OverflowError):
        return False
    return actual == {
        "bytes": size,
        "sha256": str(record.get("sha256") or ""),
    }


def _read_bound_json(record: Any) -> dict[str, Any] | None:
    if not _bound_file_ok(record):
        return None
    try:
        value = json.loads(Path(str(record["path"])).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return None
    return value if isinstance(value, dict) else None


def _same_file_content(left: Any, right: Any) -> bool:
    return (
        isinstance(left, dict)
        and isinstance(right, dict)
        and left.get("bytes") == right.get("bytes")
        and left.get("sha256") == right.get("sha256")
    )


def _validate_builtin_provider_evidence(
    evidence: dict[str, Any], files: dict[str, Any]
) -> list[str]:
    """Verify the durable spool attestation and its request/image content chain.

    The spool verifies its local record signatures before serving a result.
    These persisted bindings prove content/selection consistency; they do not
    claim a vendor-signed receipt or a verified backend model identity.
    """
    failures: list[str] = []
    metadata = evidence.get("image_provider_metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    stored = _read_bound_json(files.get("image_provider_metadata"))
    if stored is None:
        failures.append("image_provider_metadata_file")
    elif stored != metadata:
        failures.append("image_provider_metadata_content")
    for key, expected in (
        ("schema", "builtin_imagegen_artifact_v1"),
        ("status", "done"),
        ("provider", "builtin_imagegen"),
        ("transport", "codex_session_tool_spool"),
        ("tool", "image_gen.imagegen"),
        ("provenance_verification", "executor_attestation"),
        ("model_identity_status", "unverified"),
    ):
        if metadata.get(key) != expected:
            failures.append(f"builtin_metadata:{key}")
    if metadata.get("strict_model_identity_verified") is not False:
        failures.append("builtin_metadata:strict_model_identity_verified")
    for key in ("requested_model", "backend_model_id"):
        if key not in metadata or metadata[key] is not None:
            failures.append(f"builtin_metadata:{key}")
    for key in ("job_id", "request_id", "upstream_job_id", "attempt_id", "tool_call_id"):
        if not isinstance(metadata.get(key), str) or not metadata[key].strip():
            failures.append(f"builtin_metadata:{key}")
    source = files.get("source_rgb")
    source = source if isinstance(source, dict) else {}
    for name in ("image_sha256", "source_image_sha256"):
        if not source.get("sha256") or metadata.get(name) != source.get("sha256"):
            failures.append(f"builtin_source_binding:{name}")
    if metadata.get("image_bytes") != source.get("bytes"):
        failures.append("builtin_source_binding:image_bytes")
    request_file = metadata.get("request_file")
    request = _read_bound_json(request_file)
    if request is None:
        failures.append("builtin_request_file")
    else:
        if (
            metadata.get("request_path") != request_file.get("path")
            or metadata.get("request_file_sha256") != request_file.get("sha256")
        ):
            failures.append("builtin_request_file_binding")
        inputs = request.get("input")
        inputs = inputs if isinstance(inputs, dict) else {}
        try:
            request_sha256 = content_hash(inputs)
        except (TypeError, ValueError):
            request_sha256 = None
        prompt = request.get("prompt")
        try:
            prompt_sha256 = (
                hashlib.sha256(prompt.encode("utf-8")).hexdigest()
                if isinstance(prompt, str) and prompt.strip()
                else None
            )
        except UnicodeError:
            prompt_sha256 = None
        if (
            request.get("schema") != "builtin_imagegen_request_v1"
            or request.get("provider") != "builtin_imagegen"
            or inputs.get("provider") != "builtin_imagegen"
        ):
            failures.append("builtin_request_provider")
        if (
            request_sha256 is None
            or request.get("request_sha256") != request_sha256
            or metadata.get("request_sha256") != request_sha256
        ):
            failures.append("builtin_request_hash")
        if (
            prompt_sha256 is None
            or inputs.get("prompt") != prompt
            or metadata.get("prompt") != prompt
            or request.get("prompt_sha256") != prompt_sha256
            or metadata.get("prompt_sha256") != prompt_sha256
        ):
            failures.append("builtin_prompt_hash")
        if (
            metadata.get("job_id") != f"builtin_{request_sha256}"
            or request.get("job_id") != metadata.get("job_id")
        ):
            failures.append("builtin_request_job_binding")
        for key in ("request_id", "upstream_job_id"):
            if inputs.get(key) != metadata.get(key):
                failures.append(f"builtin_request_binding:{key}")
    if evidence.get("reference_origin") == "builtin_imagegen_generated":
        for key, evidence_key in (
            ("request_id", "reference_job_id"),
            ("upstream_job_id", "parent_job_id"),
        ):
            if metadata.get(key) != evidence.get(evidence_key):
                failures.append(f"builtin_evidence_binding:{evidence_key}")
    return failures


def _validate_builtin_upstream(
    evidence: dict[str, Any],
    files: dict[str, Any],
    seen_manifests: frozenset[str],
) -> list[str]:
    failures: list[str] = []
    upstream = evidence.get("upstream_reference")
    upstream = upstream if isinstance(upstream, dict) else {}
    upstream_manifest = _read_bound_json(upstream.get("manifest"))
    if upstream_manifest is None:
        return ["upstream_reference_manifest_content"]
    upstream_evidence = {**upstream_manifest, "manifest": upstream["manifest"]}
    result = validate_reference_evidence(
        upstream_evidence, _seen_manifests=seen_manifests
    )
    failures.extend(f"upstream:{failure}" for failure in result["failures"])
    if (
        upstream_manifest.get("schema") not in BUILTIN_EVIDENCE_SCHEMAS
        or upstream_manifest.get("image_provider") != "builtin_imagegen"
    ):
        failures.append("upstream_reference_provider")
    upstream_files = upstream_manifest.get("files")
    upstream_files = upstream_files if isinstance(upstream_files, dict) else {}
    source = upstream_files.get("source_rgb")
    if upstream.get("reference") != source:
        failures.append("upstream_reference_source_binding")
    if not _same_file_content(source, files.get("source_rgb")):
        failures.append("upstream_reference_source_content")
    if upstream_manifest.get("image_provider_metadata") != evidence.get("image_provider_metadata"):
        failures.append("upstream_reference_provider_metadata")
    return failures


def validate_builtin_raw_artifact_evidence(
    evidence: Any, *, _seen_manifests: frozenset[str] = frozenset()
) -> list[str]:
    """Check original builtin artifact provenance, without admitting any asset.

    A failed historical QA result can supply raw bytes for a new attempt. Only
    manifest, raw, provider metadata and original request bindings are relevant
    here; prepared images and historical acceptance are deliberately not used.
    """
    evidence = evidence if isinstance(evidence, dict) else {}
    failures: list[str] = []
    schema = evidence.get("schema")
    origin = evidence.get("reference_origin")
    allowed_origins = set(BUILTIN_REFERENCE_ORIGINS)
    if schema == NATIVE_ALPHA_REFERENCE_EVIDENCE_SCHEMA:
        allowed_origins.add(REPROCESSED_BUILTIN_REFERENCE_ORIGIN)
    if schema not in BUILTIN_EVIDENCE_SCHEMAS:
        failures.append("evidence_schema")
    if evidence.get("image_provider") != "builtin_imagegen":
        failures.append("evidence_image_provider")
    if origin not in tuple(allowed_origins):
        failures.append("reference_origin")
    for name in ("parent_job_id", "reference_job_id"):
        if not isinstance(evidence.get(name), str) or not evidence[name].strip():
            failures.append(f"evidence_{name}")
    manifest = evidence.get("manifest")
    stored = _read_bound_json(manifest)
    if stored is None:
        failures.append("evidence_manifest_binding")
    elif stored != {key: value for key, value in evidence.items() if key != "manifest"}:
        failures.append("evidence_manifest_content_mismatch")
    manifest_path = str(manifest.get("path") or "") if isinstance(manifest, dict) else ""
    if manifest_path in _seen_manifests or len(_seen_manifests) >= 32:
        return list(dict.fromkeys(failures + ["upstream_reference_cycle"]))
    files = evidence.get("files")
    files = files if isinstance(files, dict) else {}
    if not _bound_file_ok(files.get("source_rgb")):
        failures.append("evidence_file:source_rgb")
    if schema == NATIVE_ALPHA_REFERENCE_EVIDENCE_SCHEMA:
        if not _bound_file_ok(files.get("source_raw")):
            failures.append("evidence_file:source_raw")
        if files.get("source_raw") != files.get("source_rgb"):
            failures.append("native_alpha_raw_alias")
    failures.extend(_validate_builtin_provider_evidence(evidence, files))
    if origin in ("persisted_builtin_imagegen_reference", REPROCESSED_BUILTIN_REFERENCE_ORIGIN):
        failures.extend(_validate_builtin_raw_upstream(
            evidence, files, _seen_manifests | {manifest_path}
        ))
    return list(dict.fromkeys(failures))


def _validate_builtin_raw_upstream(
    evidence: dict[str, Any], files: dict[str, Any], seen_manifests: frozenset[str]
) -> list[str]:
    failures: list[str] = []
    upstream = evidence.get("upstream_reference")
    upstream = upstream if isinstance(upstream, dict) else {}
    parent = _read_bound_json(upstream.get("manifest"))
    if parent is None:
        return ["upstream_reference_manifest_content"]
    parent_evidence = {**parent, "manifest": upstream["manifest"]}
    failures.extend(f"upstream:{failure}" for failure in validate_builtin_raw_artifact_evidence(
        parent_evidence, _seen_manifests=seen_manifests
    ))
    parent_files = parent.get("files")
    parent_files = parent_files if isinstance(parent_files, dict) else {}
    source = parent_files.get("source_rgb")
    if upstream.get("reference") != source or not _bound_file_ok(upstream.get("reference")):
        failures.append("upstream_reference_source_binding")
    if not _same_file_content(source, files.get("source_rgb")):
        failures.append("upstream_reference_source_content")
    if parent.get("image_provider_metadata") != evidence.get("image_provider_metadata"):
        failures.append("upstream_reference_provider_metadata")
    if evidence.get("reference_origin") == REPROCESSED_BUILTIN_REFERENCE_ORIGIN:
        if evidence.get("replay_reference_evidence") != upstream:
            failures.append("replay_reference_evidence_binding")
        for name in ("parent_job_id", "reference_job_id"):
            if evidence.get(name) == parent.get(name):
                failures.append(f"replay_new_{name}")
    return failures


def _validate_native_alpha_evidence(
    alpha_metadata: dict[str, Any], files: dict[str, Any], source_white: dict[str, Any]
) -> list[str]:
    from .native_alpha_normalization import validate_native_alpha_normalization

    failures: list[str] = []
    normalization = _read_bound_json(files.get("input_normalization_metadata"))
    if normalization is None:
        failures.append("native_alpha_normalization_metadata_file")
    elif normalization != alpha_metadata.get("native_alpha_normalization"):
        failures.append("native_alpha_normalization_metadata_content")
    failures.extend(validate_native_alpha_normalization(normalization, files))
    visible = files.get("source_visible_white_rgb")
    visible = visible if isinstance(visible, dict) else {}
    if not visible.get("path") or alpha_metadata.get("source_white_input_path") != visible.get("path"):
        failures.append("native_alpha_source_white_input_path")
    if source_white.get("input_semantics") != "native_alpha_visible_white":
        failures.append("native_alpha_source_white_input_semantics")
    if source_white.get("source_image_path") != visible.get("path"):
        failures.append("native_alpha_source_white_report_path")
    if not visible.get("sha256") or source_white.get("source_image_sha256") != visible.get("sha256"):
        failures.append("native_alpha_source_white_report_content")
    quality = alpha_metadata.get("alpha_quality")
    if not isinstance(quality, dict) or quality.get("ok") is not True or quality.get("reasons") != []:
        failures.append("native_alpha_quality_failed")
    if not failures:
        failures.extend(_validate_native_alpha_source_white_report(source_white, files))
    return failures


def _validate_native_alpha_source_white_report(
    report: dict[str, Any], files: dict[str, Any]
) -> list[str]:
    """Reproduce the unchanged white-background gate in the native source frame."""
    import math

    import numpy as np
    from PIL import Image

    try:
        alpha_max = report["alpha_max"]
        if type(alpha_max) is not int or not 0 <= alpha_max <= 8:
            return ["native_alpha_source_white_thresholds"]
        limits = report["limits"]
        baseline = {
            "minimum_channel": 232.0,
            "maximum_chroma_range": 18.0,
            "minimum_near_white_fraction": 0.96,
            "maximum_median_deviation": 18.0,
        }
        if not isinstance(limits, dict) or set(limits) != set(baseline):
            return ["native_alpha_source_white_thresholds"]
        for key, default in baseline.items():
            value = limits[key]
            if type(value) not in (int, float) or not math.isfinite(value):
                return ["native_alpha_source_white_thresholds"]
            if value < 0 or (key.startswith("minimum_") and value < default) or (
                key.startswith("maximum_") and value > default
            ):
                return ["native_alpha_source_white_thresholds"]
        if limits["minimum_channel"] > 255 or limits["minimum_near_white_fraction"] > 1:
            return ["native_alpha_source_white_thresholds"]
        with Image.open(files["native_alpha_mask"]["path"]) as image:
            alpha = np.asarray(image)
        with Image.open(files["source_visible_white_rgb"]["path"]) as image:
            rgb = np.asarray(image)
        pixels = rgb[alpha <= alpha_max].astype(np.float32)
        minimum_samples = max(64, int(round(alpha.size * 0.02)))
        expected: dict[str, Any] = {
            "schema": "scene-v2-source-white-background/v1",
            "enforced": True,
            "sample_count": int(len(pixels)),
            "minimum_sample_count": minimum_samples,
        }
        reasons: list[str] = []
        if len(pixels) < minimum_samples:
            reasons.append("insufficient_removed_background_samples")
        else:
            chroma = pixels.max(axis=1) - pixels.min(axis=1)
            near_white = (
                (pixels.min(axis=1) >= limits["minimum_channel"])
                & (chroma <= limits["maximum_chroma_range"])
            )
            median = np.median(pixels, axis=0)
            fraction = float(np.mean(near_white))
            deviation = float(np.median(np.linalg.norm(pixels - median[None, :], axis=1)))
            if fraction < limits["minimum_near_white_fraction"]:
                reasons.append("source_background_not_uniform_near_white")
            if deviation > limits["maximum_median_deviation"]:
                reasons.append("source_background_nonuniform")
            expected.update(
                median_background_rgb=[round(float(value), 3) for value in median],
                near_white_fraction=round(fraction, 6),
                median_rgb_deviation=round(deviation, 4),
            )
        expected.update(ok=not reasons, conforms=not reasons, reasons=reasons, diagnostic_reasons=reasons)
        if any(report.get(key) != value for key, value in expected.items()):
            return ["native_alpha_source_white_report_recompute"]
    except (OSError, ValueError, TypeError, KeyError, IndexError):
        return ["native_alpha_source_white_report_invalid"]
    return []


def _validate_reprocessing_contract(evidence: dict[str, Any], files: dict[str, Any]) -> list[str]:
    normalization = _read_bound_json(files.get("input_normalization_metadata")) or {}
    source = files.get("source_raw")
    source = source if isinstance(source, dict) else {}
    provider = evidence.get("image_provider_metadata")
    provider = provider if isinstance(provider, dict) else {}
    expected = {
        "schema": "scene-v2-native-alpha-reprocessing-contract/v1",
        "native_alpha_normalization_content_key": normalization.get("content_key"),
        "source_raw_sha256": source.get("sha256"),
        "original_request_sha256": provider.get("request_sha256"),
    }
    if evidence.get("processing_contract") != expected or any(
        not expected[key] for key in expected if key != "schema"
    ):
        return ["replay_processing_contract_binding"]
    return []


def validate_reference_evidence(
    evidence: Any, *, _seen_manifests: frozenset[str] = frozenset()
) -> dict[str, Any]:
    evidence = evidence if isinstance(evidence, dict) else {}
    failures: list[str] = []
    schema = evidence.get("schema")
    origin = evidence.get("reference_origin")
    native_alpha = schema == NATIVE_ALPHA_REFERENCE_EVIDENCE_SCHEMA
    builtin = schema in BUILTIN_EVIDENCE_SCHEMAS
    if schema not in (REFERENCE_EVIDENCE_SCHEMA, *BUILTIN_EVIDENCE_SCHEMAS):
        failures.append("evidence_schema")
    allowed_origins = set(BUILTIN_REFERENCE_ORIGINS if builtin else ALLOWED_REFERENCE_ORIGINS)
    if native_alpha:
        allowed_origins.add(REPROCESSED_BUILTIN_REFERENCE_ORIGIN)
    if origin not in tuple(allowed_origins):
        failures.append("reference_origin")
    provider = (
        "builtin_imagegen" if builtin
        else evidence.get("image_provider", "flux1-schnell")
    )
    if (
        (builtin and evidence.get("image_provider") != provider)
        or (not builtin and provider not in ("flux1-schnell", "flux2-klein"))
    ):
        failures.append("evidence_image_provider")
    for name in ("parent_job_id", "reference_job_id"):
        if not str(evidence.get(name) or ""):
            failures.append(f"evidence_{name}")
    if origin in (
        "persisted_flux_generated_reference",
        "persisted_builtin_imagegen_reference",
        REPROCESSED_BUILTIN_REFERENCE_ORIGIN,
    ):
        upstream = evidence.get("upstream_reference")
        upstream = upstream if isinstance(upstream, dict) else {}
        if not _bound_file_ok(upstream.get("manifest")):
            failures.append("upstream_reference_manifest")
        if not _bound_file_ok(upstream.get("reference")):
            failures.append("upstream_reference_file")
    if evidence.get("complete") is not True:
        failures.append("evidence_incomplete")
    files = evidence.get("files")
    files = files if isinstance(files, dict) else {}
    for name in REQUIRED_GENERATION_EVIDENCE:
        if not _bound_file_ok(files.get(name)):
            failures.append(f"evidence_file:{name}")
    if native_alpha:
        for name in NATIVE_ALPHA_GENERATION_EVIDENCE:
            if not _bound_file_ok(files.get(name)):
                failures.append(f"evidence_file:{name}")
    alpha_metadata: dict[str, Any] = {}
    if _bound_file_ok(files.get("alpha_metadata")):
        value = _read_bound_json(files["alpha_metadata"])
        if value is None:
            failures.append("alpha_metadata_parse")
        else:
            alpha_metadata = value
    if builtin:
        for metadata_name, file_name in (
            ("source_image_path", "source_rgb"),
            ("prepared_image_path", "prepared_rgba"),
            ("mask_path", "alpha_mask"),
        ):
            record = files.get(file_name)
            expected_path = record.get("path") if isinstance(record, dict) else None
            if not expected_path or alpha_metadata.get(metadata_name) != expected_path:
                failures.append(f"alpha_metadata_evidence_path:{file_name}")
    source_white = alpha_metadata.get("source_white_background")
    source_white = source_white if isinstance(source_white, dict) else {}
    if native_alpha:
        failures.extend(_validate_native_alpha_evidence(alpha_metadata, files, source_white))
        if origin == REPROCESSED_BUILTIN_REFERENCE_ORIGIN:
            failures.extend(_validate_reprocessing_contract(evidence, files))
    if source_white.get("enforced") is not True:
        failures.append("source_white_background_not_enforced")
    if source_white.get("ok") is not True or source_white.get("conforms") is not True:
        failures.append("source_white_background_failed")
    isolation = alpha_metadata.get("white_background_isolation")
    isolation = isolation if isinstance(isolation, dict) else {}
    if isolation.get("ok") is not True:
        failures.append("white_background_isolation_failed")
    if isolation.get("exact_white_for_all_alpha_zero_pixels") is not True:
        failures.append("normalized_background_not_exact_white")
    if isolation.get("trellis_input_uses_transparent_rgba") is not True:
        failures.append("trellis_transparent_input_unverified")
    normalized_record = files.get("normalized_white_rgb")
    normalized_record = normalized_record if isinstance(normalized_record, dict) else {}
    normalized_path = str(normalized_record.get("path") or "")
    if str(alpha_metadata.get("normalized_white_image_path") or "") != normalized_path:
        failures.append("normalized_white_evidence_path")
    if str(isolation.get("normalized_white_rgb_path") or "") != normalized_path:
        failures.append("normalized_white_isolation_path")
    manifest = evidence.get("manifest")
    if not _bound_file_ok(manifest):
        failures.append("evidence_manifest_binding")
    else:
        stored = _read_bound_json(manifest)
        if stored is None:
            failures.append("evidence_manifest_parse")
        else:
            if stored.get("schema") != schema:
                failures.append("evidence_manifest_schema")
            if stored.get("files") != files:
                failures.append("evidence_manifest_files_mismatch")
            if stored.get("reference_origin") != evidence.get("reference_origin"):
                failures.append("evidence_manifest_origin_mismatch")
            if stored.get("image_provider") != evidence.get("image_provider"):
                failures.append("evidence_manifest_provider_mismatch")
            for name in ("parent_job_id", "reference_job_id", "complete", "upstream_reference"):
                if stored.get(name) != evidence.get(name):
                    failures.append(f"evidence_manifest_{name}_mismatch")
            if builtin and stored != {
                name: value for name, value in evidence.items() if name != "manifest"
            }:
                failures.append("evidence_manifest_content_mismatch")
    if builtin:
        failures.extend(_validate_builtin_provider_evidence(evidence, files))
        if origin in ("persisted_builtin_imagegen_reference", REPROCESSED_BUILTIN_REFERENCE_ORIGIN):
            manifest_path = str(manifest.get("path") or "") if isinstance(manifest, dict) else ""
            if manifest_path in _seen_manifests or len(_seen_manifests) >= 32:
                failures.append("upstream_reference_cycle")
            else:
                validator = (
                    _validate_builtin_raw_upstream
                    if origin == REPROCESSED_BUILTIN_REFERENCE_ORIGIN
                    else _validate_builtin_upstream
                )
                failures.extend(
                    validator(
                        evidence, files, _seen_manifests | {manifest_path}
                    )
                )
    return {
        "ok": not failures,
        "failures": list(dict.fromkeys(failures)),
        "reference_origin": evidence.get("reference_origin"),
        "parent_job_id": evidence.get("parent_job_id"),
        "reference_job_id": evidence.get("reference_job_id"),
        "image_provider": provider,
    }


def _primary_generation_metadata(metadata: Any) -> dict[str, Any]:
    metadata = metadata if isinstance(metadata, dict) else {}
    primary = metadata.get("primary_generation_metadata")
    return primary if isinstance(primary, dict) else metadata


def validate_trellis_generation_provenance(metadata: Any) -> dict[str, Any]:
    primary = _primary_generation_metadata(metadata)
    failures: list[str] = []
    job_id = str(primary.get("job_id") or "")
    if not job_id:
        failures.append("trellis_job_id")
    bridge = primary.get("bridge_metadata")
    bridge = bridge if isinstance(bridge, dict) else {}
    if bridge.get("status") != "done":
        failures.append("trellis_status")
    if str(bridge.get("job_id") or "") != job_id:
        failures.append("bridge_job_binding")
    if bridge.get("alpha_quality_ok") is not True:
        failures.append("selected_alpha_quality")
    selected_id = str(bridge.get("selected_reference_job_id") or "")
    if not selected_id:
        failures.append("selected_reference_job_id")
    attempts = bridge.get("reference_attempts")
    attempts = attempts if isinstance(attempts, list) else []
    matching_attempts = [
        row
        for row in attempts
        if isinstance(row, dict)
        and str(row.get("reference_job_id") or "") == selected_id
    ]
    selected = matching_attempts[0] if len(matching_attempts) == 1 else None
    if selected is None:
        failures.append("selected_reference_attempt")
        evidence_result = validate_reference_evidence({})
    else:
        if selected.get("alpha_quality_ok") is not True:
            failures.append("selected_attempt_alpha_quality")
        selected_evidence = selected.get("persistent_evidence")
        evidence_result = validate_reference_evidence(selected_evidence)
        selected_evidence = (
            selected_evidence if isinstance(selected_evidence, dict) else {}
        )
        if str(selected_evidence.get("parent_job_id") or "") != job_id:
            failures.append("evidence_parent_job_binding")
        if str(selected_evidence.get("reference_job_id") or "") != selected_id:
            failures.append("evidence_reference_job_binding")
        builtin = selected_evidence.get("schema") in BUILTIN_EVIDENCE_SCHEMAS
        provider = evidence_result["image_provider"]
        provider_required = builtin or "image_provider" in selected_evidence
        for name, row in (("bridge", bridge), ("selected", selected)):
            if (provider_required or "image_provider" in row) and row.get(
                "image_provider"
            ) != provider:
                failures.append(f"{name}_image_provider_binding")
        if primary.get("image_provider") is not None and primary.get("image_provider") != provider:
            failures.append("generation_image_provider_binding")
        if builtin and selected.get("image_provider_metadata") != selected_evidence.get(
            "image_provider_metadata"
        ):
            failures.append("selected_provider_metadata_binding")
        if builtin and bridge.get("image_provider_metadata") != selected_evidence.get(
            "image_provider_metadata"
        ):
            failures.append("bridge_provider_metadata_binding")
        evidence_files = selected_evidence.get("files")
        evidence_files = evidence_files if isinstance(evidence_files, dict) else {}
        source_record = evidence_files.get("source_rgb")
        source_record = source_record if isinstance(source_record, dict) else {}
        prepared_record = evidence_files.get("prepared_rgba")
        prepared_record = prepared_record if isinstance(prepared_record, dict) else {}
        source_path = str(source_record.get("path") or "")
        prepared_path = str(prepared_record.get("path") or "")
        if str(selected.get("source_image_path") or "") != source_path:
            failures.append("selected_source_evidence_path")
        if str(selected.get("prepared_image_path") or "") != prepared_path:
            failures.append("selected_rgba_evidence_path")
        if str(bridge.get("source_image_path") or "") != source_path:
            failures.append("bridge_source_evidence_path")
        if str(bridge.get("reference_image_path") or "") != prepared_path:
            failures.append("bridge_rgba_evidence_path")
        if selected_evidence.get("reference_origin") == REPROCESSED_BUILTIN_REFERENCE_ORIGIN:
            if selected.get("generated") is not False:
                failures.append("replay_attempt_generated")
            if selected.get("replay_reference_evidence") != selected_evidence.get("upstream_reference"):
                failures.append("selected_replay_reference_evidence_binding")
            for name, row in (("bridge", bridge), ("selected", selected)):
                if row.get("processing_contract") != selected_evidence.get("processing_contract"):
                    failures.append(f"{name}_processing_contract_binding")
        if selected.get("persistent_evidence") != bridge.get(
            "selected_reference_evidence"
        ):
            failures.append("selected_evidence_binding")
    failures.extend(evidence_result["failures"])
    return {
        "ok": not failures,
        "job_id": job_id or None,
        "selected_reference_job_id": selected_id or None,
        "reference_evidence": evidence_result,
        "image_provider": evidence_result["image_provider"],
        "failures": list(dict.fromkeys(failures)),
    }


def audit_asset_source_policy(asset_report: dict[str, Any]) -> dict[str, Any]:
    """Allow curated furniture or images with complete provider/TRELLIS evidence."""

    mode = str(asset_report.get("mode") or "")
    rows: list[dict[str, Any]] = []
    for item in asset_report.get("results", []):
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "")
        failures: list[str] = []
        route = ""
        generation = None
        if status == "reused":
            route = "curated_existing_asset"
            if str(item.get("asset_lifecycle_status") or "") != "curated":
                failures.append("reused_asset_not_curated")
            source = Path(str(item.get("source") or ""))
            if not source.is_file():
                failures.append("curated_source_missing")
        elif status == "generated":
            generation = validate_trellis_generation_provenance(
                item.get("metadata")
            )
            route = (
                "builtin_imagegen_trellis_generated_asset"
                if generation["image_provider"] == "builtin_imagegen"
                else "flux_trellis_generated_asset"
            )
            failures.extend(generation["failures"])
        elif status == "planned_missing" and mode == "plan":
            route = "planned_flux_trellis_generation"
        else:
            route = "forbidden_or_unknown_source"
            failures.append("source_route_not_allowed")
        rows.append(
            {
                "object_id": str(item.get("object_id") or ""),
                "category": str(item.get("category") or ""),
                "status": status,
                "route": route,
                "generation_provenance": generation,
                "ok": not failures,
                "failures": list(dict.fromkeys(failures)),
            }
        )
    failures = [
        f"{row['object_id']}:{failure}"
        for row in rows
        for failure in row["failures"]
    ]
    return {
        "schema": SOURCE_POLICY_SCHEMA,
        "allowed_routes": [
            "curated_existing_asset",
            "flux_trellis_generated_asset",
            "builtin_imagegen_trellis_generated_asset",
        ],
        "blender_furniture_geometry_generation_allowed": False,
        "ok": not failures,
        "failures": failures,
        "rows": rows,
    }
