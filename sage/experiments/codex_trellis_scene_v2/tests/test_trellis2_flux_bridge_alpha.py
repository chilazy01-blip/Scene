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
