from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ..asset_source_policy import (
    IMAGE_REFERENCE_EVIDENCE_SCHEMA,
    NATIVE_ALPHA_REFERENCE_EVIDENCE_SCHEMA,
    REFERENCE_EVIDENCE_SCHEMA,
    audit_asset_source_policy,
    validate_builtin_raw_artifact_evidence,
    validate_reference_evidence,
    validate_trellis_generation_provenance,
)
from ..content_chain import content_hash, file_binding


def _evidence(root: Path, *, origin: str = "flux_generated") -> dict:
    files = {}
    for name in ("source_rgb", "prepared_rgba", "alpha_mask", "normalized_white_rgb"):
        path = root / f"{name}.bin"
        path.write_bytes(f"evidence:{name}".encode("utf-8"))
        files[name] = {"path": str(path), **file_binding(path)}
    alpha_metadata_path = root / "alpha_metadata.json"
    alpha_metadata_path.write_text(
        json.dumps(
            {
                "normalized_white_image_path": files["normalized_white_rgb"]["path"],
                "source_white_background": {
                    "enforced": True,
                    "ok": True,
                    "conforms": True,
                },
                "white_background_isolation": {
                    "ok": True,
                    "exact_white_for_all_alpha_zero_pixels": True,
                    "trellis_input_uses_transparent_rgba": True,
                    "normalized_white_rgb_path": files["normalized_white_rgb"]["path"],
                },
            }
        ),
        encoding="utf-8",
    )
    files["alpha_metadata"] = {
        "path": str(alpha_metadata_path),
        **file_binding(alpha_metadata_path),
    }
    manifest_payload = {
        "schema": REFERENCE_EVIDENCE_SCHEMA,
        "parent_job_id": "job",
        "reference_job_id": "reference",
        "reference_origin": origin,
        "upstream_reference": None,
        "files": files,
        "complete": True,
    }
    manifest = root / "manifest.json"
    manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")
    return {**manifest_payload, "manifest": {"path": str(manifest), **file_binding(manifest)}}


def _generated_metadata(evidence: dict) -> dict:
    source_path = evidence["files"]["source_rgb"]["path"]
    prepared_path = evidence["files"]["prepared_rgba"]["path"]
    attempt = {
        "reference_job_id": evidence["reference_job_id"],
        "alpha_quality_ok": True,
        "source_image_path": source_path,
        "prepared_image_path": prepared_path,
        "persistent_evidence": evidence,
    }
    result = {
        "job_id": evidence["parent_job_id"],
        "bridge_metadata": {
            "job_id": evidence["parent_job_id"],
            "status": "done",
            "alpha_quality_ok": True,
            "selected_reference_job_id": evidence["reference_job_id"],
            "source_image_path": source_path,
            "reference_image_path": prepared_path,
            "selected_reference_evidence": evidence,
            "reference_attempts": [attempt],
        },
    }
    if evidence.get("image_provider"):
        for row in (attempt, result["bridge_metadata"]):
            row["image_provider"] = evidence["image_provider"]
            if "image_provider_metadata" in evidence:
                row["image_provider_metadata"] = evidence["image_provider_metadata"]
    if evidence.get("reference_origin") == "reprocessed_builtin_imagegen_reference":
        attempt.update(generated=False, replay_reference_evidence=evidence["replay_reference_evidence"])
        for row in (attempt, result["bridge_metadata"]):
            row["processing_contract"] = evidence["processing_contract"]
    return result


def _write_json(path: Path, payload: dict) -> dict:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return {"path": str(path), **file_binding(path)}


def _rewrite_manifest(evidence: dict) -> None:
    evidence["manifest"] = _write_json(
        Path(evidence["manifest"]["path"]),
        {name: value for name, value in evidence.items() if name != "manifest"},
    )


def _rewrite_provider_metadata(evidence: dict) -> None:
    record = evidence["files"]["image_provider_metadata"]
    evidence["files"]["image_provider_metadata"] = _write_json(
        Path(record["path"]), evidence["image_provider_metadata"]
    )
    _rewrite_manifest(evidence)


def _builtin_evidence(root: Path) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    evidence = _evidence(root, origin="builtin_imagegen_generated")
    evidence["schema"] = IMAGE_REFERENCE_EVIDENCE_SCHEMA
    evidence["image_provider"] = "builtin_imagegen"
    inputs = {
        "provider": "builtin_imagegen",
        "prompt": "A single chair on pure white",
        "request_id": "reference",
        "upstream_job_id": "job",
    }
    request_sha256 = content_hash(inputs)
    prompt_sha256 = hashlib.sha256(inputs["prompt"].encode()).hexdigest()
    request = {
        "schema": "builtin_imagegen_request_v1",
        "job_id": f"builtin_{request_sha256}",
        "provider": "builtin_imagegen",
        "input": inputs,
        "prompt": inputs["prompt"],
        "request_sha256": request_sha256,
        "prompt_sha256": prompt_sha256,
    }
    request_file = _write_json(root / "request.json", request)
    metadata = {
        "schema": "builtin_imagegen_artifact_v1",
        "status": "done",
        "provider": "builtin_imagegen",
        "transport": "codex_session_tool_spool",
        "job_id": f"builtin_{request_sha256}",
        "request_sha256": request_sha256,
        "prompt": request["prompt"],
        "prompt_sha256": prompt_sha256,
        "request_id": "reference",
        "upstream_job_id": "job",
        "attempt_id": "claim-attempt-1",
        "tool": "image_gen.imagegen",
        "tool_call_id": "tool-call-1",
        "requested_model": None,
        "backend_model_id": None,
        "model_identity_status": "unverified",
        "strict_model_identity_verified": False,
        "provenance_verification": "executor_attestation",
        "image_path": evidence["files"]["source_rgb"]["path"],
        "image_sha256": evidence["files"]["source_rgb"]["sha256"],
        "image_bytes": evidence["files"]["source_rgb"]["bytes"],
        "source_image_path": "/tmp/original-tool-output.png",
        "source_image_sha256": evidence["files"]["source_rgb"]["sha256"],
        "width": 512,
        "height": 512,
        "mime_type": "image/png",
        "request_file": request_file,
        "request_path": request_file["path"],
        "request_file_sha256": request_file["sha256"],
    }
    evidence["image_provider_metadata"] = metadata
    evidence["files"]["image_provider_metadata"] = _write_json(
        root / "image_provider_metadata.json", metadata
    )
    alpha_path = Path(evidence["files"]["alpha_metadata"]["path"])
    alpha_metadata = json.loads(alpha_path.read_text())
    for name, file_name in (
        ("source_image_path", "source_rgb"),
        ("prepared_image_path", "prepared_rgba"),
        ("mask_path", "alpha_mask"),
    ):
        alpha_metadata[name] = evidence["files"][file_name]["path"]
    evidence["files"]["alpha_metadata"] = _write_json(alpha_path, alpha_metadata)
    _rewrite_manifest(evidence)
    return evidence


def _native_alpha_evidence(root: Path, *, opacity: int = 255, reviewed: bool = False) -> dict:
    import numpy as np
    from PIL import Image

    from ..native_alpha_normalization import prepare_native_alpha_evidence

    evidence = _builtin_evidence(root)
    evidence["schema"] = NATIVE_ALPHA_REFERENCE_EVIDENCE_SCHEMA
    source_path = Path(evidence["files"]["source_rgb"]["path"])
    rgba = np.zeros((32, 32, 4), dtype=np.uint8)
    rgba[:, :, :3] = [17, 5, 44]  # Invisible native RGB is intentionally not white.
    rgba[8:24, 8:24] = [20, 60, 110, opacity]
    Image.fromarray(rgba, "RGBA").save(source_path, format="PNG")
    source = {"path": str(source_path), **file_binding(source_path)}
    evidence["files"].update(source_rgb=source, source_raw=source)
    metadata = evidence["image_provider_metadata"]
    metadata.update(
        image_sha256=source["sha256"], source_image_sha256=source["sha256"],
        image_bytes=source["bytes"], width=32, height=32,
    )
    review = None
    if reviewed:
        review = {
            "decision": "accept", "reviewer": "synthetic-test-fixture",
            "reason": "Synthetic near-opaque fixture has no translucent material.",
            "source_raw_sha256": source["sha256"],
            "alpha_pixel_sha256": hashlib.sha256(rgba[:, :, 3].tobytes()).hexdigest(),
        }
    _, _, normalization = prepare_native_alpha_evidence(source_path, root, "native", review=review)
    evidence["files"].update(normalization["records"])
    # Normalizer records use resolved paths, including the raw compatibility alias.
    evidence["files"]["source_rgb"] = evidence["files"]["source_raw"]
    evidence["files"]["input_normalization_metadata"] = _write_json(
        root / "input_normalization_metadata.json", normalization
    )
    alpha_path = Path(evidence["files"]["alpha_metadata"]["path"])
    alpha = json.loads(alpha_path.read_text())
    visible = evidence["files"]["source_visible_white_rgb"]
    alpha.update(
        source_image_path=evidence["files"]["source_raw"]["path"],
        source_white_input_path=visible["path"],
        native_alpha_normalization=normalization,
        alpha_quality={"ok": True, "reasons": []},
        source_white_background={
            "schema": "scene-v2-source-white-background/v1", "enforced": True,
            "ok": True, "conforms": True, "reasons": [], "diagnostic_reasons": [],
            "input_semantics": "native_alpha_visible_white", "alpha_max": 8,
            "source_image_path": visible["path"], "source_image_sha256": visible["sha256"],
            "sample_count": 768, "minimum_sample_count": 64,
            "median_background_rgb": [255.0, 255.0, 255.0],
            "near_white_fraction": 1.0, "median_rgb_deviation": 0.0,
            "limits": {
                "minimum_channel": 232.0, "maximum_chroma_range": 18.0,
                "minimum_near_white_fraction": 0.96, "maximum_median_deviation": 18.0,
            },
        },
    )
    evidence["files"]["alpha_metadata"] = _write_json(alpha_path, alpha)
    _rewrite_provider_metadata(evidence)
    return evidence


def _rewrite_alpha_metadata(evidence: dict, alpha: dict) -> None:
    path = Path(evidence["files"]["alpha_metadata"]["path"])
    evidence["files"]["alpha_metadata"] = _write_json(path, alpha)
    _rewrite_manifest(evidence)


def _read_alpha_metadata(evidence: dict) -> dict:
    return json.loads(Path(evidence["files"]["alpha_metadata"]["path"]).read_text())


def _reprocessed_evidence(root: Path, *, upstream: dict | None = None) -> tuple[dict, dict]:
    if upstream is None:
        upstream = _native_alpha_evidence(root / "original")
        # Frozen v2 original, with real raw and provider bindings, rejected by old QA.
        upstream["schema"] = IMAGE_REFERENCE_EVIDENCE_SCHEMA
        alpha = _read_alpha_metadata(upstream)
        alpha["source_white_background"].update(ok=False, conforms=False)
        alpha["alpha_quality"] = {"ok": False, "reasons": ["source_background_nonuniform"]}
        _rewrite_alpha_metadata(upstream, alpha)
    evidence = _native_alpha_evidence(root / "reprocessed")
    normalization = _read_alpha_metadata(evidence)["native_alpha_normalization"]
    reference = {"manifest": upstream["manifest"], "reference": upstream["files"]["source_rgb"]}
    evidence.update(
        parent_job_id="new-job", reference_job_id="new-reference",
        reference_origin="reprocessed_builtin_imagegen_reference",
        upstream_reference=reference, replay_reference_evidence=reference,
        image_provider_metadata=copy.deepcopy(upstream["image_provider_metadata"]),
        processing_contract={
            "schema": "scene-v2-native-alpha-reprocessing-contract/v1",
            "native_alpha_normalization_content_key": normalization["content_key"],
            "source_raw_sha256": evidence["files"]["source_raw"]["sha256"],
            "original_request_sha256": upstream["image_provider_metadata"]["request_sha256"],
        },
    )
    _rewrite_provider_metadata(evidence)
    return evidence, upstream


class AssetSourcePolicyTest(unittest.TestCase):
    def test_v3_native_alpha_evidence_and_generation_pass_after_full_checks(self) -> None:
        with TemporaryDirectory() as tmp:
            evidence = _native_alpha_evidence(Path(tmp))
            result = validate_trellis_generation_provenance(_generated_metadata(evidence))
            self.assertTrue(result["ok"], result)
            self.assertEqual(validate_builtin_raw_artifact_evidence(evidence), [])

    def test_v3_requires_explicit_review_for_nonopaque_interior(self) -> None:
        for reviewed in (False, True):
            with self.subTest(reviewed=reviewed), TemporaryDirectory() as tmp:
                evidence = _native_alpha_evidence(Path(tmp), opacity=253, reviewed=reviewed)
                result = validate_reference_evidence(evidence)
                self.assertEqual(result["ok"], reviewed, result)
                if not reviewed:
                    self.assertIn("native_alpha_opacity_review_required", result["failures"])
                # Raw provenance is independent from the new opacity/asset admission.
                self.assertEqual(validate_builtin_raw_artifact_evidence(evidence), [])

    def test_v3_rejects_changed_derived_files_and_raw_alias(self) -> None:
        for name in ("source_raw", "source_visible_white_rgb", "native_alpha_mask", "input_normalization_metadata"):
            with self.subTest(name=name), TemporaryDirectory() as tmp:
                evidence = _native_alpha_evidence(Path(tmp))
                Path(evidence["files"][name]["path"]).write_bytes(b"changed-artifact")
                result = validate_reference_evidence(evidence)
                self.assertFalse(result["ok"], result)
                self.assertIn(f"evidence_file:{name}", result["failures"])
        with TemporaryDirectory() as tmp:
            evidence = _native_alpha_evidence(Path(tmp))
            evidence["files"]["source_raw"] = evidence["files"]["prepared_rgba"]
            _rewrite_manifest(evidence)
            self.assertIn("native_alpha_raw_alias", validate_builtin_raw_artifact_evidence(evidence))
            self.assertFalse(validate_reference_evidence(evidence)["ok"])

    def test_v3_recomputes_native_pixels_even_when_every_public_hash_is_rebound(self) -> None:
        from PIL import Image

        from ..native_alpha_normalization import normalization_content_key

        for name, mode in (("source_visible_white_rgb", "RGB"), ("native_alpha_mask", "L")):
            with self.subTest(name=name), TemporaryDirectory() as tmp:
                evidence = _native_alpha_evidence(Path(tmp))
                path = Path(evidence["files"][name]["path"])
                Image.new(mode, (32, 32), 255).save(path, format="PNG")
                evidence["files"][name] = {"path": str(path), **file_binding(path)}
                alpha = _read_alpha_metadata(evidence)
                normalization = alpha["native_alpha_normalization"]
                normalization["records"][name] = evidence["files"][name]
                hash_key = "visible_rgb_pixel_sha256" if mode == "RGB" else "alpha_pixel_sha256"
                with Image.open(path) as image:
                    normalization[hash_key] = hashlib.sha256(image.tobytes()).hexdigest()
                normalization["content_key"] = normalization_content_key(normalization)
                record = evidence["files"]["input_normalization_metadata"]
                evidence["files"]["input_normalization_metadata"] = _write_json(Path(record["path"]), normalization)
                if mode == "RGB":
                    alpha["source_white_background"]["source_image_sha256"] = evidence["files"][name]["sha256"]
                _rewrite_alpha_metadata(evidence, alpha)
                result = validate_reference_evidence(evidence)
                self.assertFalse(result["ok"], result)
                self.assertIn(f"native_alpha_recompute:{name}", result["failures"])

    def test_v3_rejects_metadata_swaps_and_source_white_report_tampering(self) -> None:
        mutations = (
            ("source_white_input_path", "wrong.png", "native_alpha_source_white_input_path"),
            ("native_alpha_normalization", {}, "native_alpha_normalization_metadata_content"),
            ("input_semantics", "raw_hidden_rgb", "native_alpha_source_white_input_semantics"),
            ("source_image_path", "preview.png", "native_alpha_source_white_report_path"),
            ("source_image_sha256", "0" * 64, "native_alpha_source_white_report_content"),
            ("sample_count", 999, "native_alpha_source_white_report_recompute"),
            ("near_white_fraction", 0.0, "native_alpha_source_white_report_recompute"),
            ("alpha_max", 255, "native_alpha_source_white_thresholds"),
        )
        for name, value, expected in mutations:
            with self.subTest(name=name), TemporaryDirectory() as tmp:
                evidence = _native_alpha_evidence(Path(tmp))
                alpha = _read_alpha_metadata(evidence)
                target = alpha if name in ("source_white_input_path", "native_alpha_normalization") else alpha["source_white_background"]
                target[name] = value
                _rewrite_alpha_metadata(evidence, alpha)
                result = validate_reference_evidence(evidence)
                self.assertFalse(result["ok"], result)
                self.assertIn(expected, result["failures"])
        with TemporaryDirectory() as tmp:
            evidence = _native_alpha_evidence(Path(tmp))
            alpha = _read_alpha_metadata(evidence)
            alpha["source_white_background"]["limits"]["minimum_channel"] = 0
            _rewrite_alpha_metadata(evidence, alpha)
            result = validate_reference_evidence(evidence)
            self.assertIn("native_alpha_source_white_thresholds", result["failures"])

    def test_replay_accepts_only_raw_from_rejected_old_qa_and_requires_new_qa(self) -> None:
        with TemporaryDirectory() as tmp:
            evidence, upstream = _reprocessed_evidence(Path(tmp))
            frozen_manifest = Path(upstream["manifest"]["path"]).read_bytes()
            self.assertFalse(validate_reference_evidence(upstream)["ok"])
            self.assertEqual(validate_builtin_raw_artifact_evidence(upstream), [])
            result = validate_trellis_generation_provenance(_generated_metadata(evidence))
            self.assertTrue(result["ok"], result)
            self.assertEqual(Path(upstream["manifest"]["path"]).read_bytes(), frozen_manifest)
            alpha = _read_alpha_metadata(evidence)
            alpha["alpha_quality"] = {"ok": False, "reasons": ["residual_chromatic_edge_spill"]}
            _rewrite_alpha_metadata(evidence, alpha)
            result = validate_trellis_generation_provenance(_generated_metadata(evidence))
            self.assertFalse(result["ok"], result)
            self.assertIn("native_alpha_quality_failed", result["failures"])

    def test_replay_recursively_retains_original_tool_request_and_rejects_forged_chain(self) -> None:
        for mutation in ("manifest", "raw", "provider", "request", "reference", "replay", "ids", "processing"):
            with self.subTest(mutation=mutation), TemporaryDirectory() as tmp:
                evidence, upstream = _reprocessed_evidence(Path(tmp))
                if mutation == "manifest":
                    Path(upstream["manifest"]["path"]).write_text("{}")
                elif mutation == "raw":
                    Path(upstream["files"]["source_rgb"]["path"]).write_bytes(b"forged-raw")
                elif mutation == "provider":
                    evidence["image_provider_metadata"]["tool_call_id"] = "invented-new-tool-call"
                    _rewrite_provider_metadata(evidence)
                elif mutation == "request":
                    request = evidence["image_provider_metadata"]["request_file"]
                    Path(request["path"]).write_text("{}")
                elif mutation == "reference":
                    evidence["upstream_reference"]["reference"] = upstream["files"]["prepared_rgba"]
                elif mutation == "replay":
                    evidence["replay_reference_evidence"] = {}
                elif mutation == "ids":
                    evidence["parent_job_id"] = upstream["parent_job_id"]
                else:
                    evidence["processing_contract"]["original_request_sha256"] = "0" * 64
                _rewrite_manifest(evidence)
                self.assertFalse(validate_reference_evidence(evidence)["ok"])

    def test_replay_new_attempt_must_not_claim_a_new_tool_generation_or_old_contract(self) -> None:
        for target in ("generated", "replay", "selected_contract", "bridge_contract"):
            with self.subTest(target=target), TemporaryDirectory() as tmp:
                evidence, _ = _reprocessed_evidence(Path(tmp))
                metadata = _generated_metadata(evidence)
                bridge = metadata["bridge_metadata"]
                selected = bridge["reference_attempts"][0]
                if target == "generated":
                    selected["generated"] = True
                    expected = "replay_attempt_generated"
                elif target == "replay":
                    selected["replay_reference_evidence"] = {}
                    expected = "selected_replay_reference_evidence_binding"
                else:
                    row = selected if target == "selected_contract" else bridge
                    row["processing_contract"] = {}
                    expected = target.replace("_contract", "_processing_contract_binding")
                result = validate_trellis_generation_provenance(metadata)
                self.assertFalse(result["ok"], result)
                self.assertIn(expected, result["failures"])

    def test_raw_replay_recurses_to_original_request_without_using_parent_qa(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            parent, original = _reprocessed_evidence(root / "first")
            evidence, _ = _reprocessed_evidence(root / "second", upstream=parent)
            evidence.update(parent_job_id="third-job", reference_job_id="third-reference")
            _rewrite_manifest(evidence)
            result = validate_reference_evidence(evidence)
            self.assertTrue(result["ok"], result)
            self.assertEqual(validate_builtin_raw_artifact_evidence(evidence), [])
            original_request = original["image_provider_metadata"]["request_file"]
            Path(original_request["path"]).write_text("{}")
            failures = validate_builtin_raw_artifact_evidence(evidence)
            self.assertIn("upstream:upstream:builtin_request_file", failures)
            self.assertFalse(validate_reference_evidence(evidence)["ok"])

    def test_v3_persisted_reference_still_requires_full_upstream_admission(self) -> None:
        with TemporaryDirectory() as tmp:
            evidence, upstream = _reprocessed_evidence(Path(tmp))
            evidence["reference_origin"] = "persisted_builtin_imagegen_reference"
            evidence.pop("replay_reference_evidence")
            evidence.pop("processing_contract")
            _rewrite_manifest(evidence)
            result = validate_reference_evidence(evidence)
            self.assertFalse(result["ok"], result)
            self.assertIn("upstream:source_white_background_failed", result["failures"])
            alpha = _read_alpha_metadata(upstream)
            alpha["source_white_background"].update(ok=True, conforms=True)
            _rewrite_alpha_metadata(upstream, alpha)
            evidence["upstream_reference"]["manifest"] = upstream["manifest"]
            _rewrite_manifest(evidence)
            result = validate_reference_evidence(evidence)
            self.assertTrue(result["ok"], result)

    def test_raw_only_validation_rejects_ambiguous_and_malformed_origins(self) -> None:
        for origin in (None, {}, [], "flux_generated"):
            with self.subTest(origin=origin), TemporaryDirectory() as tmp:
                evidence = _builtin_evidence(Path(tmp))
                evidence["reference_origin"] = origin
                _rewrite_manifest(evidence)
                self.assertIn("reference_origin", validate_builtin_raw_artifact_evidence(evidence))

    def test_v2_cannot_relabel_rejected_reference_as_v3_replay(self) -> None:
        with TemporaryDirectory() as tmp:
            evidence, _ = _reprocessed_evidence(Path(tmp))
            evidence["schema"] = IMAGE_REFERENCE_EVIDENCE_SCHEMA
            _rewrite_manifest(evidence)
            result = validate_reference_evidence(evidence)
            self.assertFalse(result["ok"], result)
            self.assertIn("reference_origin", result["failures"])

    def test_builtin_spool_metadata_integrates_without_model_or_field_translation(self) -> None:
        from PIL import Image

        from ..image_candidate_provider import ImageCandidateJobSpool

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = _builtin_evidence(root / "evidence")
            source = Path(evidence["files"]["source_rgb"]["path"])
            Image.new("RGB", (16, 16), "white").save(source, format="PNG")
            evidence["files"]["source_rgb"] = {"path": str(source), **file_binding(source)}
            spool = ImageCandidateJobSpool(root / "spool")
            job = spool.submit({
                "provider": "builtin_imagegen",
                "prompt": "A single chair on pure white",
                "request_id": evidence["reference_job_id"],
                "upstream_job_id": evidence["parent_job_id"],
            })
            claim = spool.claim(job["job_id"], owner="source-policy-test-fixture")
            spool.fulfil(
                job["job_id"], source,
                claim_token=claim["claim_token"],
                request_sha256=job["request_sha256"],
                prompt_sha256=job["prompt_sha256"],
                tool_call_id="synthetic-test-fixture-tool-call",
            )
            evidence["image_provider_metadata"] = spool.metadata(job["job_id"])
            _rewrite_provider_metadata(evidence)
            result = validate_trellis_generation_provenance(_generated_metadata(evidence))
            self.assertTrue(result["ok"], result)

    def test_builtin_route_accepts_complete_evidence_with_unknown_model(self) -> None:
        with TemporaryDirectory() as tmp:
            evidence = _builtin_evidence(Path(tmp))
            report = audit_asset_source_policy(
                {"mode": "trellis2", "results": [{
                    "object_id": "chair",
                    "status": "generated",
                    "metadata": _generated_metadata(evidence),
                }]}
            )
            self.assertTrue(report["ok"], report)
            self.assertEqual(
                report["rows"][0]["route"], "builtin_imagegen_trellis_generated_asset"
            )
            self.assertIsNone(evidence["image_provider_metadata"]["backend_model_id"])

    def test_builtin_requires_provider_file_and_matching_manifest_content(self) -> None:
        for modification, expected in (
            ("missing_file", "image_provider_metadata_file"),
            ("metadata_changed", "image_provider_metadata_content"),
            ("manifest_changed", "evidence_manifest_content_mismatch"),
        ):
            with self.subTest(modification=modification), TemporaryDirectory() as tmp:
                evidence = _builtin_evidence(Path(tmp))
                if modification == "missing_file":
                    evidence["files"].pop("image_provider_metadata")
                    _rewrite_manifest(evidence)
                elif modification == "metadata_changed":
                    evidence["image_provider_metadata"]["tool_call_id"] = "another-tool-call"
                    _rewrite_manifest(evidence)
                else:
                    evidence["image_provider_metadata"] = copy.deepcopy(evidence["image_provider_metadata"])
                    evidence["image_provider_metadata"]["tool_call_id"] = "another-tool-call"
                result = validate_reference_evidence(evidence)
                self.assertFalse(result["ok"], result)
                self.assertIn(expected, result["failures"])

    def test_builtin_source_hash_cannot_be_replaced_by_rebinding_only_manifest(self) -> None:
        with TemporaryDirectory() as tmp:
            evidence = _builtin_evidence(Path(tmp))
            source = Path(evidence["files"]["source_rgb"]["path"])
            source.write_bytes(b"different-original-image")
            evidence["files"]["source_rgb"] = {"path": str(source), **file_binding(source)}
            _rewrite_manifest(evidence)
            result = validate_reference_evidence(evidence)
            self.assertFalse(result["ok"], result)
            self.assertIn("builtin_source_binding:image_sha256", result["failures"])

    def test_builtin_provider_claims_and_hashes_are_verified_after_rebinding(self) -> None:
        cases = (
            ("status", "waiting_for_image_provider", "builtin_metadata:status"),
            ("provider", "flux1-schnell", "builtin_metadata:provider"),
            ("tool", "openai_image_api", "builtin_metadata:tool"),
            ("tool_call_id", "", "builtin_metadata:tool_call_id"),
            ("request_sha256", "a" * 64, "builtin_request_hash"),
            ("prompt_sha256", "b" * 64, "builtin_prompt_hash"),
            ("request_id", "other-reference", "builtin_evidence_binding:reference_job_id"),
            ("upstream_job_id", "other-parent", "builtin_evidence_binding:parent_job_id"),
            ("job_id", "other-spool-job", "builtin_request_job_binding"),
            ("backend_model_id", "gpt-image-2", "builtin_metadata:backend_model_id"),
        )
        for field, value, expected in cases:
            with self.subTest(field=field), TemporaryDirectory() as tmp:
                evidence = _builtin_evidence(Path(tmp))
                evidence["image_provider_metadata"][field] = value
                _rewrite_provider_metadata(evidence)
                result = validate_reference_evidence(evidence)
                self.assertFalse(result["ok"], result)
                self.assertIn(expected, result["failures"])

    def test_builtin_request_payload_is_rehashed_from_bound_file(self) -> None:
        with TemporaryDirectory() as tmp:
            evidence = _builtin_evidence(Path(tmp))
            metadata = evidence["image_provider_metadata"]
            path = Path(metadata["request_file"]["path"])
            request = json.loads(path.read_text())
            request["input"]["prompt"] = "A different object"
            metadata["request_file"] = _write_json(path, request)
            metadata["request_file_sha256"] = metadata["request_file"]["sha256"]
            _rewrite_provider_metadata(evidence)
            result = validate_reference_evidence(evidence)
            self.assertFalse(result["ok"], result)
            self.assertIn("builtin_request_hash", result["failures"])
            self.assertIn("builtin_prompt_hash", result["failures"])

    def test_selected_attempt_and_parent_are_bound_to_evidence_for_both_schemas(self) -> None:
        for factory in (_evidence, _builtin_evidence):
            for field, value, expected in (
                ("parent_job_id", "another-job", "evidence_parent_job_binding"),
                ("reference_job_id", "another-reference", "evidence_reference_job_binding"),
            ):
                with self.subTest(factory=factory.__name__, field=field), TemporaryDirectory() as tmp:
                    evidence = factory(Path(tmp))
                    metadata = _generated_metadata(evidence)
                    evidence[field] = value
                    _rewrite_manifest(evidence)
                    result = validate_trellis_generation_provenance(metadata)
                    self.assertFalse(result["ok"], result)
                    self.assertIn(expected, result["failures"])

    def test_provider_must_match_selected_attempt_bridge_and_generation(self) -> None:
        for target in ("bridge", "selected", "generation"):
            with self.subTest(target=target), TemporaryDirectory() as tmp:
                metadata = _generated_metadata(_builtin_evidence(Path(tmp)))
                row = {
                    "bridge": metadata["bridge_metadata"],
                    "selected": metadata["bridge_metadata"]["reference_attempts"][0],
                    "generation": metadata,
                }[target]
                row["image_provider"] = "flux1-schnell"
                result = validate_trellis_generation_provenance(metadata)
                self.assertFalse(result["ok"], result)
                self.assertIn(f"{target}_image_provider_binding", result["failures"])

    def test_duplicate_selected_attempt_is_ambiguous_and_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            metadata = _generated_metadata(_builtin_evidence(Path(tmp)))
            attempts = metadata["bridge_metadata"]["reference_attempts"]
            attempts.append(copy.deepcopy(attempts[0]))
            result = validate_trellis_generation_provenance(metadata)
            self.assertFalse(result["ok"], result)
            self.assertIn("selected_reference_attempt", result["failures"])

    def test_builtin_persisted_raw_reference_keeps_original_provider_identity(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            upstream = _builtin_evidence(root / "upstream")
            evidence = _builtin_evidence(root / "rebuild")
            evidence.update(
                parent_job_id="new-job",
                reference_job_id="new-reference",
                reference_origin="persisted_builtin_imagegen_reference",
                upstream_reference={
                    "manifest": upstream["manifest"],
                    "reference": upstream["files"]["source_rgb"],
                },
                image_provider_metadata=upstream["image_provider_metadata"],
            )
            _rewrite_provider_metadata(evidence)
            result = validate_trellis_generation_provenance(_generated_metadata(evidence))
            self.assertTrue(result["ok"], result)
            evidence["upstream_reference"]["reference"] = upstream["files"]["prepared_rgba"]
            _rewrite_manifest(evidence)
            result = validate_reference_evidence(evidence)
            self.assertFalse(result["ok"], result)
            self.assertIn("upstream_reference_source_binding", result["failures"])

    def test_builtin_persisted_reference_rejects_cross_provider_and_tampered_upstream(self) -> None:
        for cross_provider in (False, True):
            with self.subTest(cross_provider=cross_provider), TemporaryDirectory() as tmp:
                root = Path(tmp)
                upstream_root = root / "upstream"
                upstream_root.mkdir()
                upstream = (_evidence if cross_provider else _builtin_evidence)(upstream_root)
                evidence = _builtin_evidence(root / "rebuild")
                evidence["reference_origin"] = "persisted_builtin_imagegen_reference"
                evidence["upstream_reference"] = {
                    "manifest": upstream["manifest"],
                    "reference": upstream["files"]["source_rgb"],
                }
                if not cross_provider:
                    evidence["image_provider_metadata"] = upstream["image_provider_metadata"]
                    _rewrite_provider_metadata(evidence)
                    Path(upstream["files"]["prepared_rgba"]["path"]).write_bytes(b"tampered")
                _rewrite_manifest(evidence)
                result = validate_reference_evidence(evidence)
                self.assertFalse(result["ok"], result)
                self.assertIn(
                    "upstream_reference_provider" if cross_provider else "upstream:evidence_file:prepared_rgba",
                    result["failures"],
                )

    def test_builtin_cannot_use_legacy_flux_schema_by_adding_a_provider_label(self) -> None:
        with TemporaryDirectory() as tmp:
            evidence = _evidence(Path(tmp))
            evidence["image_provider"] = "builtin_imagegen"
            _rewrite_manifest(evidence)
            result = validate_reference_evidence(evidence)
            self.assertFalse(result["ok"], result)
            self.assertIn("evidence_image_provider", result["failures"])

    def test_legacy_flux_v1_explicit_providers_keep_generic_route(self) -> None:
        for provider in ("flux1-schnell", "flux2-klein"):
            with self.subTest(provider=provider), TemporaryDirectory() as tmp:
                evidence = _evidence(Path(tmp))
                evidence["image_provider"] = provider
                _rewrite_manifest(evidence)
                report = audit_asset_source_policy({
                    "mode": "trellis2", "results": [{
                        "object_id": "chair", "status": "generated",
                        "metadata": _generated_metadata(evidence),
                    }],
                })
                self.assertTrue(report["ok"], report)
                self.assertEqual(report["rows"][0]["route"], "flux_trellis_generated_asset")
                self.assertEqual(report["rows"][0]["generation_provenance"]["image_provider"], provider)

    def test_legacy_flux2_v1_rejects_provider_confusion_and_missing_bindings(self) -> None:
        for target in ("manifest", "bridge", "selected", "missing_bridge", "missing_selected"):
            with self.subTest(target=target), TemporaryDirectory() as tmp:
                evidence = _evidence(Path(tmp))
                evidence["image_provider"] = "flux2-klein"
                _rewrite_manifest(evidence)
                metadata = _generated_metadata(evidence)
                bridge = metadata["bridge_metadata"]
                if target == "manifest":
                    stored = json.loads(Path(evidence["manifest"]["path"]).read_text())
                    stored["image_provider"] = "flux1-schnell"
                    evidence["manifest"] = _write_json(Path(evidence["manifest"]["path"]), stored)
                    expected = "evidence_manifest_provider_mismatch"
                else:
                    row_name = target.removeprefix("missing_")
                    row = bridge if row_name == "bridge" else bridge["reference_attempts"][0]
                    if target.startswith("missing_"):
                        row.pop("image_provider")
                    else:
                        row["image_provider"] = "flux1-schnell"
                    expected = f"{row_name}_image_provider_binding"
                result = validate_trellis_generation_provenance(metadata)
                self.assertFalse(result["ok"], result)
                self.assertIn(expected, result["failures"])

    def test_legacy_v1_rejects_explicit_null_or_unknown_provider(self) -> None:
        for provider in (None, "unknown", "openai_image_api", "builtin_imagegen"):
            with self.subTest(provider=provider), TemporaryDirectory() as tmp:
                evidence = _evidence(Path(tmp))
                evidence["image_provider"] = provider
                _rewrite_manifest(evidence)
                result = validate_reference_evidence(evidence)
                self.assertFalse(result["ok"], result)
                self.assertIn("evidence_image_provider", result["failures"])

    def test_malformed_file_binding_and_json_fail_closed(self) -> None:
        with TemporaryDirectory() as tmp:
            evidence = _builtin_evidence(Path(tmp))
            evidence["files"]["source_rgb"]["bytes"] = "invalid"
            alpha = Path(evidence["files"]["alpha_metadata"]["path"])
            alpha.write_text("[]")
            evidence["files"]["alpha_metadata"] = {"path": str(alpha), **file_binding(alpha)}
            _rewrite_manifest(evidence)
            result = validate_reference_evidence(evidence)
            self.assertFalse(result["ok"], result)
            self.assertIn("evidence_file:source_rgb", result["failures"])
            self.assertIn("alpha_metadata_parse", result["failures"])

    def test_curated_and_hash_bound_flux_trellis_are_the_only_allowed_routes(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            curated = root / "curated.glb"
            curated.write_bytes(b"curated")
            evidence = _evidence(root)
            report = audit_asset_source_policy(
                {
                    "mode": "trellis2",
                    "results": [
                        {
                            "object_id": "chair",
                            "category": "accent_chair",
                            "status": "reused",
                            "asset_lifecycle_status": "curated",
                            "source": str(curated),
                        },
                        {
                            "object_id": "sofa",
                            "category": "sofa",
                            "status": "generated",
                            "metadata": _generated_metadata(evidence),
                        },
                    ],
                }
            )

        self.assertTrue(report["ok"], report)
        self.assertEqual(
            [row["route"] for row in report["rows"]],
            ["curated_existing_asset", "flux_trellis_generated_asset"],
        )
        self.assertFalse(report["blender_furniture_geometry_generation_allowed"])

    def test_procedural_or_unknown_furniture_source_is_rejected(self) -> None:
        report = audit_asset_source_policy(
            {
                "mode": "trellis2",
                "results": [
                    {
                        "object_id": "sofa",
                        "category": "sofa",
                        "status": "procedural_blender",
                    }
                ],
            }
        )
        self.assertFalse(report["ok"], report)
        self.assertIn("sofa:source_route_not_allowed", report["failures"])

    def test_missing_or_modified_generation_evidence_is_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = _evidence(root)
            Path(evidence["files"]["source_rgb"]["path"]).write_bytes(b"modified")
            validation = validate_reference_evidence(evidence)
            report = audit_asset_source_policy(
                {
                    "mode": "trellis2",
                    "results": [
                        {
                            "object_id": "sofa",
                            "category": "sofa",
                            "status": "generated",
                            "metadata": _generated_metadata(evidence),
                        }
                    ],
                }
            )

        self.assertFalse(validation["ok"], validation)
        self.assertIn("evidence_file:source_rgb", validation["failures"])
        self.assertFalse(report["ok"], report)

    def test_direct_unproven_reference_is_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            evidence = _evidence(
                Path(tmp), origin="direct_reference_requires_upstream_provenance"
            )
            report = audit_asset_source_policy(
                {
                    "mode": "trellis2",
                    "results": [
                        {
                            "object_id": "sofa",
                            "category": "sofa",
                            "status": "generated",
                            "metadata": _generated_metadata(evidence),
                        }
                    ],
                }
            )

        self.assertFalse(report["ok"], report)
        self.assertTrue(
            any(failure.endswith(":reference_origin") for failure in report["failures"]),
            report,
        )


if __name__ == "__main__":
    unittest.main()
