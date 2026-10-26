from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from ..native_alpha_normalization import (
    EVIDENCE_SCHEMA, decode_native_alpha, normalization_content_key,
    opacity_review_ok, prepare_native_alpha_evidence, record,
    validate_native_alpha_normalization, visible_white_rgb, write_immutable,
)
from .test_trellis2_flux_bridge_alpha import _runtime
from .test_image_provider_routing import handler_instance, runtime as provider_runtime
from sage.server.trellis2_flux_bridge_server import JobStore


class NativeAlphaNormalizationTest(unittest.TestCase):
    def image(self, root: Path, alpha: int = 255) -> tuple[Path, np.ndarray]:
        rgba = np.zeros((96, 96, 4), dtype=np.uint8)
        rgba[:, :, :3] = (19, 37, 58)
        rgba[25:70, 30:65] = (95, 85, 75, alpha)
        path = root / "tool.png"
        Image.fromarray(rgba, mode="RGBA").save(path)
        return path, rgba

    def files(self, metadata):
        return {**metadata["records"], "source_rgb": metadata["records"]["source_raw"]}

    def test_hidden_rgb_composited_only_for_audit_and_raw_is_immutable(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, original = self.image(root)
            before = source.read_bytes()
            raw, visible, metadata = prepare_native_alpha_evidence(source, root, "new-job")
            np.testing.assert_array_equal(raw, original)
            self.assertEqual(source.read_bytes(), before)
            self.assertTrue(np.all(visible[original[:, :, 3] == 0] == 255))
            np.testing.assert_array_equal(visible[original[:, :, 3] == 255], original[:, :, :3][original[:, :, 3] == 255])
            self.assertEqual(validate_native_alpha_normalization(metadata, self.files(metadata)), [])
            runtime = _runtime(root)
            with patch.object(runtime, "_save_prepared_rgba", return_value=root / "prepared.png") as save:
                runtime._prepare_reference_rgba(source, "another-job", None, enforce_white_background=True)
            np.testing.assert_array_equal(save.call_args.args[0], original)
            audit = save.call_args.kwargs["source_white_rgba"]
            np.testing.assert_array_equal(audit[:, :, 3], original[:, :, 3])
            self.assertTrue(runtime._source_white_background_report(audit, enforced=True)["ok"])
            self.assertFalse(runtime._source_white_background_report(original, enforced=True)["ok"])

    def test_partial_alpha_is_never_hardened_and_requires_bound_review(self):
        values = np.array([0, 1, 8, 24, 128, 253, 254, 255], dtype=np.uint8)
        rgba = np.full((1, len(values), 4), 20, dtype=np.uint8)
        rgba[0, :, 3] = values
        expected = np.array([(20 * int(a) + 255 * (255 - int(a)) + 127) // 255 for a in values])
        np.testing.assert_array_equal(visible_white_rgb(rgba)[0, :, 0], expected)
        np.testing.assert_array_equal(rgba[0, :, 3], values)
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, original = self.image(root, 253)
            raw, _, metadata = prepare_native_alpha_evidence(source, root, "job")
            self.assertEqual(int(raw[:, :, 3].max()), 253)
            self.assertFalse(opacity_review_ok(metadata))
            self.assertIn("native_alpha_opacity_review_required", validate_native_alpha_normalization(metadata, self.files(metadata)))
            review = {"decision": "accept", "source_raw_sha256": record(source)["sha256"],
                      "alpha_pixel_sha256": hashlib.sha256(original[:, :, 3].tobytes()).hexdigest(),
                      "reviewer": "unit-test", "reason": "Synthetic uniform near-opaque fixture."}
            _, _, accepted = prepare_native_alpha_evidence(source, root, "reviewed-job", review=review)
            self.assertNotEqual(accepted["content_key"], metadata["content_key"])
            self.assertEqual(validate_native_alpha_normalization(accepted, self.files(accepted)), [])
            accepted["opacity_review"]["source_raw_sha256"] = "0" * 64
            accepted["content_key"] = normalization_content_key(accepted)
            self.assertIn("native_alpha_opacity_review_required", validate_native_alpha_normalization(accepted, self.files(accepted)))

    def test_rebinding_tampered_canonical_does_not_forge_derivation(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, _ = self.image(root)
            _, _, metadata = prepare_native_alpha_evidence(source, root, "job")
            canonical = Path(metadata["records"]["source_visible_white_rgb"]["path"])
            Image.new("RGB", (96, 96), (255, 255, 255)).save(canonical)
            metadata["records"]["source_visible_white_rgb"] = record(canonical)
            metadata["visible_rgb_pixel_sha256"] = hashlib.sha256(np.full((96, 96, 3), 255, dtype=np.uint8).tobytes()).hexdigest()
            metadata["content_key"] = normalization_content_key(metadata)
            failures = validate_native_alpha_normalization(metadata, self.files(metadata))
            self.assertIn("native_alpha_recompute:source_visible_white_rgb", failures)
            self.assertIn("native_alpha_pixel_hash:source_visible_white_rgb", failures)

    def test_opaque_colored_background_never_becomes_white(self):
        rgba = np.full((96, 96, 4), 255, dtype=np.uint8)
        rgba[:, :, :3] = (20, 30, 40)
        rgba[0, 0, 3] = 0
        visible = visible_white_rgb(rgba)
        np.testing.assert_array_equal(visible[1:, :], rgba[1:, :, :3])
        runtime = _runtime()
        self.assertFalse(runtime._source_white_background_report(rgba, enforced=True)["ok"])

    def test_rgb_and_opaque_rgba_keep_existing_rmbg_path(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = _runtime(root)
            runtime.args.alpha_mode = "rembg"
            for mode in ("RGB", "RGBA"):
                source = root / f"{mode}.png"
                Image.new(mode, (32, 32), (40, 50, 60) if mode == "RGB" else (40, 50, 60, 255)).save(source)
                self.assertIsNone(decode_native_alpha(source))
                with patch.object(runtime, "_prepare_reference_with_rmbg", return_value=root / "prepared.png") as rmbg, patch.object(runtime, "_read_alpha_metadata", return_value={"alpha_quality": {"ok": True}}):
                    runtime._prepare_reference_rgba(source, "job", None)
                rmbg.assert_called_once()
                self.assertEqual(rmbg.call_args.args[0], source)

    def test_palette_and_luminance_transparency_are_detected(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for mode in ("P", "LA"):
                source = root / f"{mode}.png"
                image = Image.new(mode, (32, 32), 0 if mode == "P" else (80, 0))
                if mode == "P":
                    image.info["transparency"] = 0
                image.save(source)
                self.assertIsNotNone(decode_native_alpha(source))

    def test_immutable_commit_is_idempotent_and_conflicts_do_not_overwrite(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "raw.png"
            write_immutable(path, b"original")
            write_immutable(path, b"original")
            with self.assertRaisesRegex(ValueError, "conflict"):
                write_immutable(path, b"other")
            self.assertEqual(path.read_bytes(), b"original")

    def test_review_gate_cannot_be_disabled_by_alpha_quality_flag(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, _ = self.image(root, 253)
            _, _, normalization = prepare_native_alpha_evidence(source, root, "job")
            runtime = _runtime(root)
            runtime.args.alpha_quality_check = False
            metadata = {"native_alpha_normalization": normalization, "alpha_quality": {"ok": True}}
            self.assertFalse(runtime._alpha_metadata_ok(metadata))

    def test_cpu_entry_rejects_requests_that_could_need_a_model(self):
        runtime = _runtime()
        for payload in ({}, {"replay_reference_evidence": {"manifest": {}}, "scene_dna": {"contract_hash": "abc"}}):
            with patch.object(runtime, "generate") as generate:
                with self.assertRaisesRegex(ValueError, "CPU native-alpha replay"):
                    runtime.reprocess_native_alpha_candidate_cpu(payload, "new-job")
                generate.assert_not_called()

    def test_pre_normalization_bridge_contract_cannot_resume_as_v3(self):
        bridge = provider_runtime()
        old_contract = bridge.image_provider_contract("builtin_imagegen")
        old_contract.pop("native_alpha_normalization")
        jobs = JobStore()
        job = jobs.create("old-job", request={
            "image_provider": "builtin_imagegen", "input_text": "one chair",
            "image_provider_contract": old_contract,
        })
        jobs.update(job, status="interrupted")
        handler = handler_instance(jobs, bridge, f"/providers/builtin_imagegen/job/{job}/resume", {})
        with patch("sage.server.trellis2_flux_bridge_server.threading.Thread") as worker:
            handler.do_POST()
        self.assertEqual(handler._send_json.call_args.args[0], 400)
        worker.assert_not_called()
        self.assertEqual(jobs.get(job)["status"], "interrupted")

    def test_persisted_v3_paths_match_normalization_and_source_white_report(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, _ = self.image(root)
            runtime = _runtime(root)
            prepared = runtime._prepare_reference_rgba(source, "job", None, enforce_white_background=True)
            alpha = runtime._read_alpha_metadata("job")
            with patch.object(runtime, "_persistent_evidence_root", return_value=root / "durable"):
                attempt = runtime._persist_reference_attempt_evidence("job", {
                    "source_image_path": str(source), "prepared_image_path": str(prepared),
                    "reference_job_id": "job", "generated": True,
                    "image_provider": "builtin_imagegen", "image_provider_metadata": {},
                    "alpha_metadata": alpha,
                })
            evidence = attempt["persistent_evidence"]
            self.assertEqual(evidence["schema"], EVIDENCE_SCHEMA)
            files = evidence["files"]
            normalization = json.loads(Path(files["input_normalization_metadata"]["path"]).read_text())
            alpha = attempt["alpha_metadata"]
            self.assertEqual(normalization, alpha["native_alpha_normalization"])
            self.assertEqual(validate_native_alpha_normalization(normalization, files), [])
            self.assertEqual(files["source_rgb"], files["source_raw"])
            self.assertEqual(alpha["source_white_background"]["source_image_path"], files["source_visible_white_rgb"]["path"])
            self.assertEqual(alpha["source_white_background"]["source_image_sha256"], files["source_visible_white_rgb"]["sha256"])


if __name__ == "__main__":
    unittest.main()
