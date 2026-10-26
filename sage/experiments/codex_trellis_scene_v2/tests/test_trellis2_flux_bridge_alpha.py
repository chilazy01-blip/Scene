from __future__ import annotations

import unittest
from io import BytesIO
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
from PIL import Image

from ..io_utils import write_json
from ..scene_dna_alpha_reprocess import reprocess_existing_candidates
from ..alpha_hygiene import (
    audit_sanitized_alpha_edges,
    clean_chromatic_alpha_edges,
    composite_on_review_background,
)
from sage.server.trellis2_flux_bridge_server import (
    JobStore,
    Trellis2BridgeRuntime,
    build_handler,
)
from ..asset_source_policy import validate_reference_evidence


def _runtime(output_dir: Path | None = None) -> Trellis2BridgeRuntime:
    return Trellis2BridgeRuntime(
        Namespace(
            output_dir=str(output_dir) if output_dir is not None else ".",
            alpha_bbox_threshold=24,
            alpha_content_scale=0.84,
            alpha_quality_check=True,
            alpha_min_foreground_ratio=0.012,
            alpha_max_foreground_ratio=0.68,
            alpha_max_border_foreground_ratio=0.015,
            white_base_quality_check=True,
            white_base_auto_repair=True,
        )
    )


class Trellis2FluxBridgeAlphaTest(unittest.TestCase):
    def test_host_allocator_trim_is_best_effort_and_boolean(self) -> None:
        self.assertIsInstance(
            Trellis2BridgeRuntime._trim_host_allocator("unit test"),
            bool,
        )

    def test_recycle_gate_rejects_new_jobs_after_metadata_delivery(self) -> None:
        with TemporaryDirectory() as tmp:
            jobs = JobStore()
            runtime = SimpleNamespace(
                args=SimpleNamespace(exit_after_metadata_responses=1, output_dir=tmp)
            )
            timer = MagicMock()
            handler = build_handler(jobs, runtime)
            with patch(
                "sage.server.trellis2_flux_bridge_server.threading.Timer",
                return_value=timer,
            ):
                handler.schedule_process_recycle_for_test()
            instance = handler.__new__(handler)
            instance.path = "/generate"
            instance._send_json = MagicMock()
            instance.do_POST()
            instance._send_json.assert_called_once_with(
                503,
                {
                    "error": "bridge process is draining before supervised restart",
                    "retryable": True,
                },
            )

    def test_broker_backpressure_returns_http_429_without_worker(self) -> None:
        jobs = JobStore()
        runtime = SimpleNamespace(
            args=SimpleNamespace(exit_after_metadata_responses=0, output_dir=".")
        )
        broker = MagicMock()
        broker.acquire.return_value = {
            "accepted": False,
            "status": "queue_full",
            "retryable": True,
        }
        handler = build_handler(jobs, runtime, broker)
        instance = handler.__new__(handler)
        instance.path = "/generate"
        instance.headers = {"Content-Length": "2"}
        instance.rfile = BytesIO(b"{}")
        instance._send_json = MagicMock()
        instance.do_POST()
        status, payload = instance._send_json.call_args.args
        self.assertEqual(status, 429)
        self.assertEqual(payload["admission"]["status"], "queue_full")
        self.assertEqual(jobs._jobs, {})

    def test_opt_in_scene_dna_scoring_releases_cached_pipeline(self) -> None:
        class FakeCuda:
            def __init__(self) -> None:
                self.empty_cache_calls = 0

            @staticmethod
            def is_available() -> bool:
                return True

            def empty_cache(self) -> None:
                self.empty_cache_calls += 1

        class FakeTorch:
            def __init__(self) -> None:
                self.cuda = FakeCuda()

        runtime = _runtime()
        runtime.args.scene_dna_release_pipeline_before_scoring = True
        runtime._pipeline = object()
        runtime._torch = FakeTorch()

        runtime._release_pipeline_before_scene_dna_scoring()

        self.assertIsNone(runtime._pipeline)
        self.assertEqual(runtime._torch.cuda.empty_cache_calls, 1)

    def test_magenta_matte_is_cleaned_and_hidden_rgb_is_zeroed(self) -> None:
        rgba = np.zeros((128, 128, 4), dtype=np.uint8)
        rgba[:, :, :3] = (230, 10, 105)
        rgba[36:92, 36:92, :3] = (205, 175, 135)
        rgba[36:92, 36:92, 3] = 255
        rgba[34:94, 34:94, 3] = np.maximum(rgba[34:94, 34:94, 3], 128)
        rgba[34:94, 34:94, :3] = (
            rgba[34:94, 34:94, :3].astype(np.float32) * 0.5
            + np.array((205, 175, 135), dtype=np.float32) * 0.5
        ).astype(np.uint8)

        cleaned, report = clean_chromatic_alpha_edges(rgba)

        self.assertTrue(report["cleanup_applied"], report)
        self.assertTrue(report["ok"], report)
        self.assertGreater(report["hidden_rgb_zeroed_pixel_count"], 0)
        self.assertTrue(np.all(cleaned[:, :, :3][cleaned[:, :, 3] == 0] == 0))
        self.assertLessEqual(
            report["after"]["visible_spill_fraction"],
            report["before"]["visible_spill_fraction"],
        )
        composited = composite_on_review_background(cleaned)
        self.assertEqual(composited.mode, "RGB")
        self.assertEqual(composited.getpixel((0, 0)), (224, 224, 224))

        cleaned_again, second_report = clean_chromatic_alpha_edges(cleaned)
        self.assertTrue(second_report["ok"], second_report)
        self.assertFalse(second_report["cleanup_applied"], second_report)
        self.assertTrue(np.array_equal(cleaned, cleaned_again))

    def test_near_transparent_warm_subject_edge_is_not_background_evidence(self) -> None:
        rgba = np.zeros((128, 128, 4), dtype=np.uint8)
        rgba[30:98, 30:98, :3] = (255, 235, 150)
        rgba[30:98, 30:98, 3] = 4
        rgba[34:94, 34:94, :3] = (225, 180, 105)
        rgba[34:94, 34:94, 3] = 255

        cleaned, report = clean_chromatic_alpha_edges(rgba)

        self.assertTrue(report["ok"], report)
        self.assertFalse(report["background_estimate"]["evaluated"], report)
        self.assertFalse(report["cleanup_applied"], report)
        self.assertTrue(np.array_equal(rgba, cleaned))

    def test_recorded_neutral_background_protects_warm_subject_edge(self) -> None:
        rgba = np.zeros((128, 128, 4), dtype=np.uint8)
        rgba[30:98, 30:98, :3] = (255, 235, 150)
        rgba[30:98, 30:98, 3] = 4
        rgba[34:94, 34:94, :3] = (225, 180, 105)
        rgba[34:94, 34:94, 3] = 255

        report = audit_sanitized_alpha_edges(rgba, [224, 224, 224])

        self.assertTrue(report["ok"], report)
        self.assertFalse(report["spill"]["chromatic_background"], report)

    def test_recorded_chroma_background_detects_residual_edge_spill(self) -> None:
        rgba = np.zeros((128, 128, 4), dtype=np.uint8)
        rgba[28:100, 28:100, :3] = (230, 10, 105)
        rgba[28:100, 28:100, 3] = 96
        rgba[36:92, 36:92, :3] = (190, 160, 120)
        rgba[36:92, 36:92, 3] = 255

        report = audit_sanitized_alpha_edges(rgba, [230, 10, 105])

        self.assertFalse(report["ok"], report)
        self.assertIn("residual_chromatic_edge_spill", report["reasons"])

    def test_bridge_records_source_background_and_audits_final_pixels(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            rgba = np.zeros((128, 128, 4), dtype=np.uint8)
            rgba[:, :, :3] = (215, 212, 207)
            rgba[30:98, 42:86, :3] = (55, 55, 55)
            rgba[30:98, 42:86, 3] = 255
            runtime = _runtime(root)
            prepared = runtime._save_prepared_rgba(
                rgba,
                root / "source.png",
                "job",
                "test",
                object_text="one complete dark table lamp",
            )
            metadata = runtime._read_alpha_metadata("job")
            saved = np.asarray(Image.open(prepared).convert("RGBA"))

        hygiene = metadata["alpha_quality"]["chroma_spill_hygiene"]
        self.assertEqual(hygiene["schema"], "scene_dna_alpha_chroma_hygiene_provenance_v2")
        self.assertEqual(hygiene["background_rgb"], [215.0, 212.0, 207.0])
        self.assertTrue(hygiene["prepared_audit"]["ok"], hygiene)
        self.assertTrue(np.all(saved[:, :, :3][saved[:, :, 3] == 0] == 0))

    def test_complete_pale_box_body_is_not_a_white_platform(self) -> None:
        rgba = np.zeros((256, 256, 4), dtype=np.uint8)
        rgba[50:210, 40:216, :3] = (230, 215, 190)
        rgba[50:210, 40:216, 3] = 255
        report = _runtime()._alpha_quality_report(
            rgba,
            "one complete light beige fabric storage box with a visible lid",
        )
        white_report = report["white_base_artifact"]
        protected = [
            row
            for row in white_report["candidates"]
            if row["decision"] == "protected_connected_subject_region"
        ]
        self.assertTrue(report["ok"], report)
        self.assertTrue(protected, white_report)
        self.assertGreater(
            protected[0]["topology"]["maximum_support_occupancy_ratio"],
            protected[0]["topology"][
                "maximum_allowed_support_occupancy_ratio"
            ],
        )

    def test_connected_wide_sofa_base_is_rejected_even_when_fused(self) -> None:
        rgba = np.zeros((256, 256, 4), dtype=np.uint8)
        # Dark upholstered body and a full-width dark connector make the pale
        # lower slab topologically continuous with the sofa.
        rgba[45:165, 48:208, :3] = (90, 75, 65)
        rgba[45:165, 48:208, 3] = 255
        rgba[158:168, 34:222, :3] = (90, 75, 65)
        rgba[158:168, 34:222, 3] = 255
        rgba[168:198, 34:222, :3] = (232, 226, 216)
        rgba[168:198, 34:222, 3] = 255
        rgba[198:214, 58:70, :3] = (90, 75, 65)
        rgba[198:214, 58:70, 3] = 255
        rgba[198:214, 186:198, :3] = (90, 75, 65)
        rgba[198:214, 186:198, 3] = 255

        report = _runtime()._alpha_quality_report(
            rgba,
            "one complete sofa with visible legs; no platform or floor slab",
        )

        self.assertFalse(report["ok"], report)
        self.assertIn("illegal_white_base_or_platform", report["reasons"])
        connected = [
            row
            for row in report["white_base_artifact"]["candidates"]
            if row["decision"] == "illegal_connected_base_candidate"
        ]
        self.assertTrue(connected, report["white_base_artifact"])
        self.assertEqual(
            connected[0]["topology"]["maximum_support_occupancy_ratio"],
            1.0,
        )

    def test_dark_connected_sofa_base_fails_colour_independent_support_gap(self) -> None:
        rgba = np.zeros((256, 256, 4), dtype=np.uint8)
        rgba[45:165, 48:208, :3] = (75, 62, 55)
        rgba[45:165, 48:208, 3] = 255
        rgba[165:198, 34:222, :3] = (52, 45, 42)
        rgba[165:198, 34:222, 3] = 255
        rgba[198:214, 58:70, :3] = (52, 45, 42)
        rgba[198:214, 58:70, 3] = 255
        rgba[198:214, 186:198, :3] = (52, 45, 42)
        rgba[198:214, 186:198, 3] = 255

        report = _runtime()._alpha_quality_report(
            rgba,
            "one complete dark sofa with visible separated legs; no platform",
        )

        self.assertFalse(report["ok"], report)
        self.assertIn(
            "exposed_support_background_gap_missing", report["reasons"]
        )
        gap = report["exposed_support_background_gap"]
        self.assertLess(
            gap["open_column_fraction"], gap["minimum_open_column_fraction"]
        )

    def test_visible_separated_sofa_legs_pass_support_gap(self) -> None:
        rgba = np.zeros((256, 256, 4), dtype=np.uint8)
        rgba[45:165, 48:208, :3] = (75, 62, 55)
        rgba[45:165, 48:208, 3] = 255
        for x0 in (58, 92, 158, 192):
            rgba[165:214, x0 : x0 + 10, :3] = (52, 45, 42)
            rgba[165:214, x0 : x0 + 10, 3] = 255

        report = _runtime()._alpha_quality_report(
            rgba,
            "one complete dark sofa with visible separated legs; no platform",
        )

        self.assertTrue(report["ok"], report)
        gap = report["exposed_support_background_gap"]
        self.assertGreaterEqual(
            gap["open_column_fraction"], gap["minimum_open_column_fraction"]
        )

    def test_enforced_white_source_and_exact_normalized_preview(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            rgba = np.full((128, 128, 4), 255, dtype=np.uint8)
            rgba[:, :, 3] = 0
            rgba[30:98, 42:86, :3] = (60, 55, 50)
            rgba[30:98, 42:86, 3] = 255
            runtime = _runtime(root)
            runtime._save_prepared_rgba(
                rgba,
                root / "source.png",
                "job",
                "test",
                object_text="one complete cabinet",
                enforce_white_background=True,
            )
            metadata = runtime._read_alpha_metadata("job")
            normalized = np.asarray(
                Image.open(metadata["normalized_white_image_path"]).convert("RGB")
            )
            mask = np.asarray(Image.open(metadata["mask_path"]).convert("L"))

        self.assertTrue(metadata["source_white_background"]["ok"], metadata)
        self.assertTrue(metadata["source_white_background"]["conforms"], metadata)
        self.assertTrue(metadata["white_background_isolation"]["ok"], metadata)
        self.assertTrue(np.all(normalized[mask == 0] == 255))

    def test_enforced_gray_source_background_is_rejected(self) -> None:
        rgba = np.zeros((128, 128, 4), dtype=np.uint8)
        rgba[:, :, :3] = (210, 210, 210)
        rgba[30:98, 42:86, :3] = (60, 55, 50)
        rgba[30:98, 42:86, 3] = 255

        report = _runtime()._source_white_background_report(rgba, enforced=True)

        self.assertFalse(report["ok"], report)
        self.assertIn(
            "source_background_not_uniform_near_white", report["reasons"]
        )

    def test_temporary_bridge_output_requires_persistent_evidence_root(self) -> None:
        runtime = _runtime(Path("/tmp/scene-v2-volatile-evidence-test"))
        runtime.args.persistent_evidence_dir = ""
        with self.assertRaisesRegex(RuntimeError, "must be persistent"):
            runtime._persistent_evidence_root("job")

    def test_reference_evidence_survives_volatile_source_removal(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            volatile = root / "volatile"
            persistent = root / "persistent"
            source = volatile / "source.png"
            prepared = volatile / "prepared.png"
            mask = volatile / "mask.png"
            normalized = volatile / "normalized.png"
            source.parent.mkdir(parents=True)
            Image.new("RGB", (24, 24), "gray").save(source)
            Image.new("RGBA", (24, 24), (80, 80, 80, 255)).save(prepared)
            Image.new("L", (24, 24), 255).save(mask)
            Image.new("RGB", (24, 24), "white").save(normalized)
            runtime = _runtime(volatile)
            runtime.args.persistent_evidence_dir = str(persistent)
            with patch.object(
                runtime, "_path_is_temporary_storage", return_value=False
            ):
                attempt = runtime._persist_reference_attempt_evidence(
                    "parent-job",
                    {
                        "reference_job_id": "reference-job",
                        "generated": True,
                        "source_image_path": str(source),
                        "prepared_image_path": str(prepared),
                        "alpha_quality_ok": True,
                        "alpha_metadata": {
                            "source_image_path": str(source),
                            "prepared_image_path": str(prepared),
                            "mask_path": str(mask),
                            "normalized_white_image_path": str(normalized),
                            "source_white_background": {
                                "enforced": True,
                                "ok": True,
                                "conforms": True,
                            },
                            "white_background_isolation": {
                                "ok": True,
                                "exact_white_for_all_alpha_zero_pixels": True,
                                "trellis_input_uses_transparent_rgba": True,
                                "normalized_white_rgb_path": str(normalized),
                            },
                            "alpha_quality": {"ok": True},
                        },
                    },
                )
            source.unlink()
            prepared.unlink()
            mask.unlink()
            normalized.unlink()
            validation = validate_reference_evidence(
                attempt["persistent_evidence"]
            )

        self.assertTrue(validation["ok"], validation)

    def test_promoted_direct_reference_keeps_generated_model_provenance(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            persistent = root / "persistent"
            runtime = _runtime(root / "runtime")
            runtime.args.persistent_evidence_dir = str(persistent)
            raw = root / "raw.png"
            rgba = root / "rgba.png"
            mask = root / "mask.png"
            Image.new("RGB", (16, 16), "gray").save(raw)
            Image.new("RGBA", (16, 16), (60, 60, 60, 255)).save(rgba)
            Image.new("L", (16, 16), 255).save(mask)
            with patch.object(
                runtime, "_path_is_temporary_storage", return_value=False
            ):
                first = runtime._persist_reference_attempt_evidence(
                    "first-job",
                    {
                        "reference_job_id": "flux-reference",
                        "generated": True,
                        "source_image_path": str(raw),
                        "prepared_image_path": str(rgba),
                        "alpha_metadata": {"mask_path": str(mask)},
                    },
                )
                promoted_source = first["prepared_image_path"]
                promoted_prepared = root / "promoted-rgba.png"
                promoted_mask = root / "promoted-mask.png"
                Image.new("RGBA", (16, 16), (60, 60, 60, 255)).save(
                    promoted_prepared
                )
                Image.new("L", (16, 16), 255).save(promoted_mask)
                promoted = runtime._persist_reference_attempt_evidence(
                    "second-job",
                    {
                        "reference_job_id": "second-reference",
                        "generated": False,
                        "source_image_path": promoted_source,
                        "prepared_image_path": str(promoted_prepared),
                        "alpha_metadata": {"mask_path": str(promoted_mask)},
                    },
                )

        self.assertEqual(
            promoted["persistent_evidence"]["reference_origin"],
            "persisted_flux_generated_reference",
        )
        self.assertIsNotNone(
            promoted["persistent_evidence"]["upstream_reference"]
        )

    def test_detached_white_platform_is_detected_and_removed(self) -> None:
        rgba = np.zeros((256, 256, 4), dtype=np.uint8)
        rgba[30:165, 95:161, :3] = (65, 65, 65)
        rgba[30:165, 95:161, 3] = 255
        rgba[190:208, 40:216, :3] = (235, 235, 235)
        rgba[190:208, 40:216, 3] = 255
        runtime = _runtime()
        quality = runtime._alpha_quality_report(rgba, "one dark table lamp")
        self.assertFalse(quality["ok"], quality)
        self.assertIn("illegal_white_base_or_platform", quality["reasons"])
        repaired, repair = runtime._repair_white_base_artifacts(
            rgba, quality, "one dark table lamp"
        )
        self.assertTrue(repair["applied"], repair)
        self.assertTrue(repair["damage_audit"]["ok"], repair)
        self.assertFalse(np.any(repaired[190:208, 40:216, 3]))
        self.assertTrue(np.all(repaired[30:165, 95:161, 3] == 255))

    def test_sparse_chair_base_parts_are_not_treated_as_a_platform(self) -> None:
        rgba = np.zeros((256, 256, 4), dtype=np.uint8)
        rgba[30:150, 85:171, :3] = (70, 70, 70)
        rgba[30:150, 85:171, 3] = 255
        rgba[150:190, 125:131, :3] = (70, 70, 70)
        rgba[150:190, 125:131, 3] = 255
        rgba[190:198, 55:120, :3] = (235, 235, 235)
        rgba[190:198, 55:120, 3] = 255
        rgba[190:198, 136:201, :3] = (235, 235, 235)
        rgba[190:198, 136:201, 3] = 255
        report = _runtime()._alpha_quality_report(
            rgba,
            "one complete office chair with a stable wheeled or legged base",
        )
        self.assertTrue(report["ok"], report)
        decisions = {
            row["decision"]
            for row in report["white_base_artifact"]["candidates"]
        }
        self.assertNotIn("illegal_base_candidate", decisions)

    def test_damage_audit_rolls_back_forced_body_deletion(self) -> None:
        rgba = np.zeros((256, 256, 4), dtype=np.uint8)
        rgba[50:210, 40:216, :3] = (230, 215, 190)
        rgba[50:210, 40:216, 3] = 255
        forced_quality = {
            "white_base_artifact": {
                "violating_candidates": [
                    {
                        "bbox": [40, 143, 216, 210],
                        "top_ratio": 0.58,
                        "topology": {"separated_or_narrowly_supported": True},
                    }
                ]
            }
        }
        repaired, repair = _runtime()._repair_white_base_artifacts(
            rgba, forced_quality, "one complete light beige storage box"
        )
        self.assertFalse(repair["applied"], repair)
        self.assertTrue(repair["rolled_back"], repair)
        self.assertIn(
            "removed_foreground_fraction_too_large",
            repair["damage_audit"]["reasons"],
        )
        np.testing.assert_array_equal(repaired, rgba)

    def test_frozen_raw_candidate_reprocess_writes_rescore_compatible_case(self) -> None:
        class FakeRuntime:
            def __init__(self, root: Path) -> None:
                self.root = root
                self.metadata: dict[str, dict] = {}

            def _prepare_reference_with_rmbg(
                self, source, job_id, _pipeline, object_text=None
            ):
                output = self.root / f"{job_id}.png"
                Image.open(source).convert("RGBA").save(output)
                self.metadata[job_id] = {
                    "object_text": object_text,
                    "alpha_quality": {
                        "ok": True,
                        "white_base_artifact": {"candidates": []},
                    },
                    "white_base_repair": {
                        "applied": False,
                        "rolled_back": False,
                    },
                }
                return output

            def _read_alpha_metadata(self, job_id):
                return self.metadata[job_id]

            def _alpha_metadata_ok(self, metadata):
                return bool(metadata["alpha_quality"]["ok"])

            def _scene_dna_visual_candidate_score(
                self, _path, _metadata, _scene_dna
            ):
                return {"score": 0.75, "legacy_pixel_score": 0.75}

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "raw.png"
            Image.new("RGB", (16, 16), "beige").save(raw)
            plan = root / "plan.json"
            write_json(
                plan,
                {
                    "batches": [
                        {
                            "case_id": "case",
                            "style_condition": "warm_modern",
                            "object_prompt": "one complete box",
                            "semantic_form_contract": {
                                "shape_profile": "compact_orthogonal"
                            },
                        }
                    ]
                },
            )
            source = root / "source"
            write_json(
                source / "candidate_benchmark_results.json",
                {"results": [{"case_id": "case"}]},
            )
            write_json(
                source / "cases" / "case" / "candidate_batch_result.json",
                {
                    "reference_attempts": [
                        {
                            "attempt": 0,
                            "reference_job_id": "job",
                            "source_image_path": str(raw),
                            "alpha_metadata": {
                                "object_text": "one complete box"
                            },
                        }
                    ]
                },
            )
            output = root / "output"
            report = reprocess_existing_candidates(
                plan,
                source,
                output,
                runtime=FakeRuntime(root),  # type: ignore[arg-type]
            )
            result = output / "cases" / "case" / "candidate_batch_result.json"
            candidate = output / "cases" / "case" / "candidate_00.png"
            result_exists = result.is_file()
            candidate_exists = candidate.is_file()
        self.assertEqual(report["processed_case_count"], 1)
        self.assertEqual(report["processed_candidate_count"], 1)
        self.assertTrue(result_exists)
        self.assertTrue(candidate_exists)


if __name__ == "__main__":
    unittest.main()
