from __future__ import annotations

import json
import io
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from urllib.error import URLError
from unittest.mock import patch

import numpy as np
from PIL import Image

from sage.server.trellis2_flux_bridge_server import Trellis2BridgeRuntime

from ..assets import (
    AssetRegistry,
    generate_trellis_asset,
    load_candidate_checkpoints,
    persist_candidate_checkpoint,
    resolve_assets,
)
from ..architecture import plan_architecture
from ..brief import (
    build_asset_generation_spec,
    build_baseline_brief,
    render_asset_prompt,
)
from ..scene_dna import (
    apply_scene_dna_to_generation_spec,
    build_harmony_certificate,
    build_scene_dna_contract,
    score_asset_candidate,
)
from ..scene_dna_materials import compile_material_applicability
from ..scene_dna_semantic import score_form_contract
from ..scene_dna_multiview import (
    evaluate_multiview_manifest,
    structure_profile_for_object,
)
from ..scene_dna_ablation import ABLATION_MODES, run_scene_dna_ablation
from ..scene_graph import build_typed_scene_graph


class SceneDNATest(unittest.TestCase):
    def test_candidate_checkpoint_resumes_only_verified_glb(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "candidates" / "floor_lamp"
            candidate = root / "attempt_00" / "assets" / "floor_lamp.glb"
            candidate.parent.mkdir(parents=True)
            candidate.write_bytes(b"verified candidate glb")
            obj = {"id": "floor_lamp", "category": "floor_lamp"}
            record = {
                "attempt": 0,
                "candidate_rank": 1,
                "seed": 17,
                "path": str(candidate),
                "metadata": {"job_id": "job-17", "bridge_metadata": {}},
                "multiview": {"automated_pixel_multiview_pass": True},
            }
            persist_candidate_checkpoint(root, obj, "contract-1", record)
            loaded = load_candidate_checkpoints(root, obj, "contract-1")
            self.assertEqual(loaded[(0, 1)]["metadata"]["job_id"], "job-17")

            candidate.write_bytes(b"tampered candidate glb")
            self.assertEqual(
                load_candidate_checkpoints(root, obj, "contract-1"),
                {},
            )

    def test_lamp_asset_prompt_excludes_visible_power_cords(self) -> None:
        prompt = render_asset_prompt(
            {
                "category": "floor_lamp",
                "shape_guidance": "one complete tall floor lamp",
                "style_tags": ["modern"],
                "appearance_terms": ["brass"],
                "target_proportion_ratio_w_l_h": [1.0, 1.0, 4.0],
                "integrated_component_requirements": [],
            }
        )
        self.assertIn("no visible power cord", prompt)

    @staticmethod
    def _bridge_args(output_dir: str) -> Namespace:
        return Namespace(
            output_dir=output_dir,
            flux_background_mode="contrast",
            flux_retry_count=2,
            alpha_quality_check=True,
            alpha_bbox_threshold=24,
            white_base_require_clean=True,
            alpha_require_quality=False,
        )

    def test_bridge_generates_requested_scene_dna_candidate_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Trellis2BridgeRuntime(self._bridge_args(tmp))
            fake_path = Path(tmp) / "candidate.png"
            Image.new("RGB", (16, 16), (128, 128, 128)).save(fake_path)
            payload = {
                "input_text": "one oak storage box",
                "seed": 3,
                "scene_dna": {
                    "contract_hash": "contract",
                    "candidate_funnel": {"isolated_2d_candidates": 4},
                },
            }
            with patch.object(runtime, "_wait_for_flux_image", return_value=fake_path):
                candidates = list(
                    runtime._reference_candidates_for_payload(payload, "job")
                )
        self.assertEqual(len(candidates), 4)
        self.assertEqual([item["attempt"] for item in candidates], [0, 1, 2, 3])
        self.assertEqual(len({item["seed"] for item in candidates}), 4)

    def test_bridge_flux_wait_tolerates_one_slow_poll(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            args = self._bridge_args(tmp)
            args.flux_server_url = "http://127.0.0.1:8083"
            args.flux_width = 16
            args.flux_height = 16
            args.flux_steps = 4
            args.flux_guidance_scale = 0.0
            args.flux_max_sequence_length = 32
            args.flux_timeout = 10.0
            runtime = Trellis2BridgeRuntime(args)
            encoded = io.BytesIO()
            Image.new("RGB", (16, 16), "gray").save(encoded, format="PNG")
            polls = iter([TimeoutError("slow inference"), (200, encoded.getvalue(), "image/png")])

            def fake_get(*_args, **_kwargs):
                value = next(polls)
                if isinstance(value, Exception):
                    raise value
                return value

            with patch(
                "sage.server.trellis2_flux_bridge_server.post_json",
                return_value=(202, {"job_id": "flux-job"}),
            ), patch(
                "sage.server.trellis2_flux_bridge_server.get_bytes",
                side_effect=fake_get,
            ), patch("sage.server.trellis2_flux_bridge_server.time.sleep"):
                path = runtime._wait_for_flux_image("one box", 3, "job")
        self.assertTrue(path.name == "job.png")

    def test_bridge_gray_mode_uses_one_neutral_background_for_all_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            args = self._bridge_args(tmp)
            args.flux_background_mode = "gray"
            runtime = Trellis2BridgeRuntime(args)
            fake_path = Path(tmp) / "candidate.png"
            Image.new("RGB", (16, 16), (128, 128, 128)).save(fake_path)
            payload = {
                "input_text": "one oak storage box",
                "seed": 3,
                "scene_dna": {
                    "contract_hash": "contract",
                    "candidate_funnel": {"isolated_2d_candidates": 4},
                },
            }
            with patch.object(runtime, "_wait_for_flux_image", return_value=fake_path):
                candidates = list(
                    runtime._reference_candidates_for_payload(payload, "job")
                )
        self.assertEqual(
            {item["background"] for item in candidates},
            {"simple solid light gray background"},
        )

    def test_bridge_scene_dna_pixel_score_prefers_warm_oak_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Trellis2BridgeRuntime(self._bridge_args(tmp))
            warm_path = Path(tmp) / "warm.png"
            cool_path = Path(tmp) / "cool.png"
            for path, color in (
                (warm_path, (181, 132, 78, 255)),
                (cool_path, (50, 82, 180, 255)),
            ):
                rgba = np.zeros((64, 64, 4), dtype=np.uint8)
                rgba[12:52, 12:52] = color
                Image.fromarray(rgba, mode="RGBA").save(path)
            metadata = {
                "alpha_quality": {
                    "ok": True,
                    "score": 1.0,
                    "reasons": [],
                    "white_base_artifact": {"ok": True},
                }
            }
            scene_dna = {
                "contract_hash": "contract",
                "global_tags": ["warm", "oak", "wood"],
                "individuality_tags": [],
            }
            warm = runtime._scene_dna_visual_candidate_score(
                warm_path, metadata, scene_dna
            )
            cool = runtime._scene_dna_visual_candidate_score(
                cool_path, metadata, scene_dna
            )
        self.assertGreater(warm["score"], cool["score"])
        self.assertGreater(warm["palette_score"], cool["palette_score"])
        self.assertFalse(warm["semantic_embedding_evaluated"])

    def test_bridge_selects_best_hard_eligible_scene_dna_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Trellis2BridgeRuntime(self._bridge_args(tmp))
            attempts = []
            for index, color in enumerate(
                ((181, 132, 78, 255), (50, 82, 180, 255))
            ):
                path = Path(tmp) / f"candidate_{index}.png"
                rgba = np.zeros((64, 64, 4), dtype=np.uint8)
                rgba[12:52, 12:52] = color
                Image.fromarray(rgba, mode="RGBA").save(path)
                attempts.append(
                    {
                        "reference_job_id": f"ref-{index}",
                        "attempt": index,
                        "prepared_image_path": str(path),
                        "alpha_quality_ok": True,
                        "alpha_metadata": {
                            "alpha_quality": {
                                "ok": True,
                                "score": 1.0,
                                "reasons": [],
                                "white_base_artifact": {"ok": True},
                            }
                        },
                    }
                )
            payload = {
                "scene_dna": {
                    "contract_hash": "contract",
                    "global_tags": ["warm", "oak"],
                    "individuality_tags": [],
                    "candidate_funnel": {
                        "isolated_2d_candidates": 4,
                        "max_candidates_promoted_to_trellis2": 2,
                    },
                }
            }
            selected, report = runtime._select_scene_dna_reference_attempt(
                attempts, payload
            )
        self.assertEqual(selected["reference_job_id"], "ref-0")
        self.assertEqual(report["actual_candidates_promoted_to_trellis2"], 1)
        self.assertEqual(report["ranking"][0]["reference_job_id"], "ref-0")
        self.assertFalse(report["semantic_embedding_evaluated"])

    def test_bridge_semantic_form_strategy_promotes_uncertain_top_two(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            args = self._bridge_args(tmp)
            args.scene_dna_form_scoring = True
            args.scene_dna_semantic_scoring = "off"
            args.scene_dna_uncertainty_margin = 0.03
            args.scene_dna_unload_scorers = True
            runtime = Trellis2BridgeRuntime(args)
            attempts = []
            for index, color in enumerate(((210, 190, 158, 255), (212, 192, 160, 255))):
                path = Path(tmp) / f"box_{index}.png"
                rgba = np.zeros((96, 96, 4), dtype=np.uint8)
                rgba[20:76, 14:82] = color
                Image.fromarray(rgba, mode="RGBA").save(path)
                attempts.append(
                    {
                        "reference_job_id": f"ref-{index}",
                        "attempt": index,
                        "prepared_image_path": str(path),
                        "alpha_quality_ok": True,
                        "alpha_metadata": {
                            "alpha_quality": {
                                "ok": True,
                                "score": 1.0,
                                "reasons": [],
                                "white_base_artifact": {"ok": True},
                            }
                        },
                    }
                )
            payload = {
                "scene_dna": {
                    "contract_hash": "contract",
                    "global_tags": ["beige", "warm"],
                    "individuality_tags": ["beige"],
                    "semantic_form_contract": {
                        "identity": "storage box",
                        "shape_profile": "compact_orthogonal",
                        "required_parts": ["box body", "lid"],
                        "forbidden_parts": [],
                        "hard_negative_identities": ["suitcase"],
                    },
                    "candidate_funnel": {
                        "isolated_2d_candidates": 2,
                        "max_candidates_promoted_to_trellis2": 2,
                    },
                }
            }
            _, report = runtime._select_scene_dna_reference_attempt(
                attempts, payload
            )
        self.assertTrue(report["form_contract_evaluated"])
        self.assertTrue(report["uncertainty"]["uncertain"])
        self.assertEqual(report["actual_candidates_promoted_to_trellis2"], 2)
        self.assertEqual(len(report["promoted_reference_image_paths"]), 2)

    def test_opt_in_form_guard_falls_back_and_promotes_legacy_control_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            args = self._bridge_args(tmp)
            args.scene_dna_form_scoring = True
            args.scene_dna_semantic_scoring = "off"
            args.scene_dna_form_improvement_guard = True
            args.scene_dna_minimum_form_improvement = 0.08
            runtime = Trellis2BridgeRuntime(args)
            attempts = []
            for index in range(2):
                path = Path(tmp) / f"candidate_{index}.png"
                Image.new("RGBA", (32, 32), "white").save(path)
                attempts.append(
                    {
                        "reference_job_id": f"ref-{index}",
                        "attempt": index,
                        "prepared_image_path": str(path),
                        "alpha_quality_ok": True,
                        "alpha_metadata": {
                            "alpha_quality": {
                                "ok": True,
                                "score": 1.0,
                                "white_base_artifact": {"ok": True},
                            }
                        },
                    }
                )
            scores = [
                {
                    "score": 0.70,
                    "legacy_pixel_score": 0.90,
                    "form": {"evaluated": True, "gate_passed": True, "score": 0.80},
                    "semantic_embedding_evaluated": False,
                },
                {
                    "score": 0.90,
                    "legacy_pixel_score": 0.70,
                    "form": {"evaluated": True, "gate_passed": True, "score": 0.85},
                    "semantic_embedding_evaluated": False,
                },
            ]
            payload = {
                "scene_dna": {
                    "contract_hash": "contract",
                    "candidate_funnel": {
                        "isolated_2d_candidates": 2,
                        "max_candidates_promoted_to_trellis2": 2,
                    },
                }
            }
            with patch.object(
                runtime,
                "_scene_dna_visual_candidate_score",
                side_effect=scores,
            ):
                selected, report = runtime._select_scene_dna_reference_attempt(
                    attempts, payload
                )
        self.assertEqual(report["combined_selector_reference_job_id"], "ref-1")
        self.assertEqual(report["legacy_control_reference_job_id"], "ref-0")
        self.assertEqual(selected["reference_job_id"], "ref-0")
        self.assertEqual(report["promoted_reference_job_ids"][0], "ref-0")
        self.assertEqual(
            report["selection_guard"]["decision"],
            "fallback_to_legacy_control",
        )

    def test_opt_in_vnext_selects_balanced_candidate_and_stays_auditable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            args = self._bridge_args(tmp)
            args.scene_dna_form_scoring = True
            args.scene_dna_semantic_scoring = "off"
            args.scene_dna_vnext_selector = True
            runtime = Trellis2BridgeRuntime(args)
            attempts = []
            for index in range(2):
                path = Path(tmp) / f"candidate_{index}.png"
                Image.new("RGBA", (32, 32), "white").save(path)
                attempts.append(
                    {
                        "reference_job_id": f"ref-{index}",
                        "attempt": index,
                        "prepared_image_path": str(path),
                        "alpha_quality_ok": True,
                        "alpha_metadata": {
                            "alpha_quality": {
                                "ok": True,
                                "score": 1.0,
                                "white_base_artifact": {"ok": True},
                            }
                        },
                    }
                )
            scores = [
                {
                    "score": 0.92,
                    "legacy_pixel_score": 0.92,
                    "form": {"evaluated": True, "gate_passed": True, "score": 0.8},
                    "generability": {
                        "hard_gate_passed": True,
                        "score": 0.8,
                        "reliability_floor": 0.3,
                    },
                },
                {
                    "score": 0.78,
                    "legacy_pixel_score": 0.78,
                    "form": {"evaluated": True, "gate_passed": True, "score": 0.8},
                    "generability": {
                        "hard_gate_passed": True,
                        "score": 0.76,
                        "reliability_floor": 0.7,
                    },
                },
            ]
            payload = {
                "scene_dna": {
                    "contract_hash": "contract",
                    "candidate_funnel": {
                        "isolated_2d_candidates": 2,
                        "max_candidates_promoted_to_trellis2": 2,
                    },
                }
            }
            with patch.object(
                runtime,
                "_scene_dna_visual_candidate_score",
                side_effect=scores,
            ):
                selected, report = runtime._select_scene_dna_reference_attempt(
                    attempts, payload
                )
        self.assertEqual(report["combined_selector_reference_job_id"], "ref-0")
        self.assertEqual(report["vnext_selector_reference_job_id"], "ref-1")
        self.assertEqual(selected["reference_job_id"], "ref-1")
        self.assertTrue(report["vnext_selection"]["selection_changed"])
        self.assertEqual(report["promoted_reference_job_ids"][0], "ref-1")

    def test_vnext_can_rescue_generic_candidate_when_old_form_gate_rejects_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            args = self._bridge_args(tmp)
            args.scene_dna_form_scoring = True
            args.scene_dna_semantic_scoring = "required"
            args.scene_dna_vnext_selector = True
            runtime = Trellis2BridgeRuntime(args)
            path = Path(tmp) / "candidate.png"
            Image.new("RGBA", (32, 32), "white").save(path)
            attempt = {
                "reference_job_id": "rescued",
                "attempt": 0,
                "prepared_image_path": str(path),
                "alpha_quality_ok": True,
                "alpha_metadata": {
                    "alpha_quality": {
                        "ok": True,
                        "score": 1.0,
                        "white_base_artifact": {"ok": True},
                    }
                },
            }
            score = {
                "score": 0.7,
                "legacy_pixel_score": 0.7,
                "form": {"evaluated": True, "gate_passed": False, "score": 0.4},
                "semantic": {"evaluated": True, "gate_passed": True, "score": 0.8},
                "generability": {
                    "hard_gate_passed": True,
                    "score": 0.75,
                    "reliability_floor": 0.7,
                },
            }
            payload = {
                "scene_dna": {
                    "contract_hash": "contract",
                    "candidate_funnel": {
                        "isolated_2d_candidates": 1,
                        "max_candidates_promoted_to_trellis2": 1,
                    },
                }
            }
            with patch.object(
                runtime,
                "_scene_dna_visual_candidate_score",
                return_value=score,
            ):
                selected, report = runtime._select_scene_dna_reference_attempt(
                    [attempt], payload
                )
        self.assertEqual(selected["reference_job_id"], "rescued")
        self.assertTrue(report["current_selector_batch_rejected"])
        self.assertEqual(report["current_selector_hard_eligible_candidate_count"], 0)
        self.assertIsNone(report["combined_selector_reference_job_id"])

    def test_trellis_request_forwards_scene_dna_candidate_contract(self) -> None:
        obj = {
            "id": "box",
            "asset_prompt": "one isolated warm oak storage box",
            "asset_generation_spec": {
                "scene_dna": {
                    "contract_hash": "contract",
                    "global_tags": ["warm", "oak"],
                    "candidate_funnel": {"isolated_2d_candidates": 4},
                }
            },
        }
        metadata_payload = {
            "selected_reference_job_id": "ref-2",
            "reference_attempts": [],
            "scene_dna_candidate_selection": {
                "schema": "scene_dna_2d_candidate_selection_v1"
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "box.glb"
            with patch(
                "sage.experiments.codex_trellis_scene_v2.assets._post_json",
                return_value=(202, {"job_id": "job-1"}),
            ) as post_mock, patch(
                "sage.experiments.codex_trellis_scene_v2.assets._get",
                side_effect=[
                    (200, b"glb", "model/gltf-binary"),
                    (200, json.dumps(metadata_payload).encode("utf-8"), "application/json"),
                ],
            ):
                result = generate_trellis_asset(
                    obj,
                    destination,
                    trellis_url="http://127.0.0.1:8082",
                    seed=1,
                    timeout=2,
                    steps=1,
                    texture_size=64,
                    decimation_target=100,
                    pipeline_type="512",
                    preprocess_image=False,
                )
            request_payload = post_mock.call_args.args[1]
        self.assertEqual(request_payload["scene_dna_candidate_count"], 4)
        self.assertEqual(request_payload["scene_dna"]["contract_hash"], "contract")
        self.assertEqual(
            result["bridge_metadata"]["scene_dna_candidate_selection"]["schema"],
            "scene_dna_2d_candidate_selection_v1",
        )

    def test_trellis_request_retries_supervised_bridge_restart_gap(self) -> None:
        obj = {"id": "box", "asset_prompt": "one isolated storage box"}
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "box.glb"
            with patch(
                "sage.experiments.codex_trellis_scene_v2.assets._post_json",
                side_effect=[
                    URLError(ConnectionRefusedError(111, "connection refused")),
                    (202, {"job_id": "job-after-restart"}),
                ],
            ) as post_mock, patch(
                "sage.experiments.codex_trellis_scene_v2.assets._get",
                side_effect=[
                    (200, b"glb", "model/gltf-binary"),
                    (200, b"{}", "application/json"),
                ],
            ), patch(
                "sage.experiments.codex_trellis_scene_v2.assets.time.sleep"
            ):
                result = generate_trellis_asset(
                    obj,
                    destination,
                    trellis_url="http://127.0.0.1:8082",
                    seed=1,
                    timeout=2,
                    steps=1,
                    texture_size=64,
                    decimation_target=100,
                    pipeline_type="512",
                    preprocess_image=False,
                )
        self.assertEqual(post_mock.call_count, 2)
        self.assertEqual(result["job_id"], "job-after-restart")

    def test_resolver_writes_2d_candidate_audit_into_certificate(self) -> None:
        brief = build_baseline_brief(
            "A warm modern bedroom with exactly one storage box."
        )
        box = next(obj for obj in brief["objects"] if obj["category"] == "storage_box")
        brief["objects"] = [box]
        brief["asset_inventory"] = [
            {
                "category": "storage_box",
                "requested_count": 1,
                "required_count": 1,
                "instance_ids": [box["id"]],
            }
        ]
        def fake_generate(obj: dict, *_args, **_kwargs) -> dict:
            output_path = Path(_args[0])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"glb")
            selection = {
                "schema": "scene_dna_2d_candidate_selection_v1",
                "contract_hash": obj["asset_generation_spec"]["scene_dna"][
                    "contract_hash"
                ],
                "requested_candidate_count": 4,
                "generated_candidate_count": 4,
                "selected_reference_job_id": "ref-3",
            }
            return {
                "job_id": "job-1",
                "bridge_metadata": {
                    "selected_reference_job_id": "ref-3",
                    "reference_attempts": [],
                    "scene_dna_candidate_selection": selection,
                },
            }

        with tempfile.TemporaryDirectory() as tmp, patch(
            "sage.experiments.codex_trellis_scene_v2.assets.bridge_health",
            return_value={"ok": True},
        ), patch(
            "sage.experiments.codex_trellis_scene_v2.assets.generate_trellis_asset",
            side_effect=fake_generate,
        ):
            report = resolve_assets(
                brief,
                Path(tmp),
                mode="trellis2",
                manifest_path=None,
                trellis_url="http://127.0.0.1:8082",
                seed=1,
                timeout=1,
                steps=1,
                texture_size=64,
                decimation_target=100,
                pipeline_type="512",
                preprocess_image=False,
                max_new_assets=1,
            )
            certificate = json.loads(
                Path(report["harmony_certificate"]).read_text(encoding="utf-8")
            )
        self.assertEqual(
            report["results"][0]["scene_dna_2d_candidate_selection"][
                "selected_reference_job_id"
            ],
            "ref-3",
        )
        self.assertTrue(certificate["records"][0]["pre_trellis_2d_evaluated"])
        self.assertTrue(
            certificate["records"][0]["pre_trellis_2d_contract_hash_matches"]
        )
        self.assertEqual(
            certificate["records"][0]["pre_trellis_2d_candidate_selection"][
                "generated_candidate_count"
            ],
            4,
        )
        self.assertFalse(certificate["claims_visual_harmony_pass"])

    def test_controlled_ablation_runs_all_four_modes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            summary = run_scene_dna_ablation(
                "A warm modern bedroom.",
                None,
                Path(tmp),
            )
        self.assertEqual(
            [item["mode"] for item in summary["modes"]],
            list(ABLATION_MODES),
        )
        self.assertTrue(
            all(summary["controlled_variables"].values())
        )
        self.assertTrue(
            all(not item["claims_visual_harmony_pass"] for item in summary["modes"])
        )

    def test_ablation_modes_isolate_style_sources(self) -> None:
        brief = build_baseline_brief(
            "A cool modern study with a desk and office chair."
        )
        architecture_plan = plan_architecture(brief)
        brief["scene_graph"] = build_typed_scene_graph(brief, architecture_plan)
        anchors = [
            {
                "object_id": "desk",
                "asset": {
                    "asset_id": "warm_classic_desk",
                    "category": "desk",
                    "styles": ["warm", "classic", "wood"],
                },
            }
        ]
        prompt_only = build_scene_dna_contract(
            brief,
            architecture_plan["architecture"],
            anchors,
            ablation_mode="user_prompt_only",
        )
        anchor_only = build_scene_dna_contract(
            brief,
            architecture_plan["architecture"],
            anchors,
            ablation_mode="global_anchor_only",
        )
        legacy = build_scene_dna_contract(
            brief,
            architecture_plan["architecture"],
            anchors,
            ablation_mode="legacy_coarse_tags",
        )
        self.assertEqual(
            set(prompt_only["global_profile"]["descriptors"]),
            {"cool", "modern"},
        )
        self.assertEqual(
            set(anchor_only["global_profile"]["descriptors"]),
            {"warm", "classic", "wood"},
        )
        self.assertFalse(prompt_only["local_aesthetic_groups"])
        self.assertFalse(anchor_only["local_aesthetic_groups"])
        self.assertFalse(legacy["selection_policy"]["style_reranking_enabled"])

    def test_non_style_render_words_do_not_leak_into_global_style(self) -> None:
        brief = build_baseline_brief(
            "Use reduced perspective distortion, minimal occlusion, and a modern room."
        )
        contract = build_scene_dna_contract(brief, brief.get("architecture"), [])
        descriptors = set(contract["global_profile"]["descriptors"])
        self.assertIn("modern", descriptors)
        self.assertNotIn("red", descriptors)
        self.assertNotIn("minimal", descriptors)

    def test_explicit_user_style_overrides_conflicting_anchor_consensus(self) -> None:
        brief = build_baseline_brief(
            "A warm modern bedroom with oak furniture and clean lines."
        )
        architecture_plan = plan_architecture(brief)
        brief["scene_graph"] = build_typed_scene_graph(brief, architecture_plan)
        anchors = [
            {
                "object_id": "bed",
                "asset": {
                    "asset_id": "cool_classic_bed",
                    "category": "bed",
                    "styles": ["cool", "classic", "metal"],
                },
            },
            {
                "object_id": "wardrobe",
                "asset": {
                    "asset_id": "cool_classic_wardrobe",
                    "category": "wardrobe",
                    "styles": ["cool", "classic", "metal"],
                },
            },
        ]
        contract = build_scene_dna_contract(
            brief, architecture_plan["architecture"], anchors
        )
        desired = {
            item["tag"]: item for item in contract["global_profile"]["desired_tags"]
        }
        self.assertEqual(desired["warm"]["source"], "user_prompt")
        self.assertEqual(desired["modern"]["source"], "user_prompt")
        self.assertNotIn("cool", desired)
        self.assertNotIn("classic", desired)
        self.assertTrue(contract["selection_policy"]["style_is_soft_reranking_only"])

    def test_typed_relations_create_local_aesthetic_groups(self) -> None:
        brief = build_baseline_brief(
            "A modern study with a desk, an office chair, and a mug on the desk."
        )
        architecture_plan = plan_architecture(brief)
        brief["scene_graph"] = build_typed_scene_graph(brief, architecture_plan)
        contract = build_scene_dna_contract(
            brief, architecture_plan["architecture"], []
        )
        groups = contract["local_aesthetic_groups"]
        self.assertTrue(groups)
        self.assertTrue(
            any(
                {"desk", "office_chair"}
                <= set(group["members"])
                for group in groups
            )
        )

    def test_category_local_prompt_appearance_becomes_object_individuality(self) -> None:
        brief = build_baseline_brief(
            "A warm white bedroom with exactly one beige woven fabric storage box."
        )
        contract = build_scene_dna_contract(brief, brief.get("architecture"), [])
        profile = contract["object_profiles"]["explicit_storage_box"]
        self.assertEqual(profile["individuality_source"], "category_local_prompt_term")
        self.assertIn("beige", profile["individuality_tags"])
        self.assertIn("fabric", profile["individuality_tags"])

    def test_material_applicability_scopes_metal_to_slipper_accents(self) -> None:
        semantic_form = {
            "shape_profile": "open_back_footwear",
            "required_parts": ["sole", "upper", "open back"],
        }
        plan = compile_material_applicability(
            semantic_form,
            ["gray", "matte metal"],
            style_tags=["cool", "industrial"],
        )
        rendered = " ".join(plan["prompt_appearance_terms"])
        self.assertIn("rubber sole", rendered)
        self.assertIn("fabric or leather upper", rendered)
        self.assertIn("accents only", rendered)
        self.assertIn("never a rigid metal foot-contact body", rendered)
        self.assertEqual(
            plan["redirected_or_scoped_materials"][0]["scope"],
            "small_hardware_or_trim",
        )

    def test_material_applicability_keeps_plant_material_on_pot(self) -> None:
        plan = compile_material_applicability(
            {"shape_profile": "organic_branching"},
            ["gray", "matte metal"],
        )
        rendered = " ".join(plan["prompt_appearance_terms"])
        self.assertIn("natural green foliage and stems", rendered)
        self.assertIn("matte metal plant pot only", rendered)
        self.assertNotIn("matte metal foliage", rendered)

    def test_skeletal_support_omits_physically_inapplicable_materials(self) -> None:
        plan = compile_material_applicability(
            {"shape_profile": "skeletal_support"},
            ["cream fabric", "oak", "ceramic"],
        )
        rendered = " ".join(plan["prompt_appearance_terms"])
        self.assertIn("cream fabric seat or back surface", rendered)
        self.assertIn("oak load bearing frame", rendered)
        self.assertNotIn("ceramic", rendered)
        self.assertEqual(
            plan["redirected_or_scoped_materials"][0]["scope"],
            "omitted_from_skeletal_support",
        )

    def test_skeletal_support_form_allows_connected_upholstered_silhouette(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "upholstered_chair.png"
            rgba = np.zeros((128, 128, 4), dtype=np.uint8)
            rgba[10:55, 30:98] = (220, 205, 180, 255)
            rgba[35:80, 15:30] = (220, 205, 180, 255)
            rgba[35:80, 98:113] = (220, 205, 180, 255)
            rgba[55:80, 25:103] = (220, 205, 180, 255)
            rgba[80:115, 25:40] = (155, 105, 65, 255)
            rgba[80:115, 88:103] = (155, 105, 65, 255)
            Image.fromarray(rgba, mode="RGBA").save(path)
            report = score_form_contract(
                path,
                {"shape_profile": "skeletal_support"},
            )
        self.assertEqual(report["features"]["internal_hole_count"], 0)
        self.assertTrue(report["gate_passed"], report)

    def test_generation_prompt_filters_nonlocal_scene_palette(self) -> None:
        spec = {
            "style_tags": ["modern", "warm", "ceramic", "green", "oak"],
            "appearance_terms": ["beige boucle upholstery", "readable seams"],
            "semantic_form_contract": {"shape_profile": "skeletal_support"},
        }
        contract = {
            "selection_policy": {"style_reranking_enabled": True},
            "generation_policy": {},
            "global_profile": {
                "desired_tags": [
                    {"tag": "modern"},
                    {"tag": "warm"},
                    {"tag": "ceramic"},
                    {"tag": "green"},
                    {"tag": "oak"},
                ]
            },
            "object_profiles": {
                "chair": {
                    "individuality_tags": ["beige", "boucle"],
                    "semantic_form_contract": {
                        "shape_profile": "skeletal_support"
                    },
                }
            },
            "local_aesthetic_groups": [],
        }
        enriched = apply_scene_dna_to_generation_spec(spec, contract, "chair")
        self.assertEqual(enriched["style_tags"], ["modern", "warm"])
        self.assertEqual(
            enriched["scene_dna"]["filtered_nonlocal_palette_tags"],
            ["ceramic", "green", "oak"],
        )

    def test_generation_prompt_uses_part_scoped_material_contract(self) -> None:
        obj = {
            "id": "slipper",
            "category": "slipper",
            "dimensions": {"width": 0.12, "length": 0.29, "height": 0.09},
        }
        original = (
            "slipper in cool gray with dark metal accents and restrained "
            "industrial detail"
        )
        spec = build_asset_generation_spec(
            obj, ["cool", "industrial", "clean lines"], original
        )
        contract = build_scene_dna_contract(
            {
                "original_prompt": original,
                "styles": ["cool", "industrial", "clean lines"],
                "objects": [obj],
                "relations": [],
            }
        )
        enriched = apply_scene_dna_to_generation_spec(spec, contract, "slipper")
        prompt = render_asset_prompt(enriched)
        self.assertIn("rubber sole and fabric or leather upper", prompt)
        self.assertIn("matte metal accents only", prompt)
        self.assertIn("material_applicability", enriched["scene_dna"])
        self.assertEqual(
            enriched["appearance_terms_original"], ["gray", "matte metal"]
        )

    def test_registry_uses_scene_dna_only_after_dimension_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("warm.glb", "cool.glb", "oversize.glb"):
                (root / name).write_bytes(name.encode("utf-8"))
            manifest = {
                "assets": [
                    {
                        "asset_id": "cool_modern",
                        "category": "desk",
                        "glb_path": "cool.glb",
                        "qa_status": "approved",
                        "styles": ["modern", "cool", "metal"],
                        "dimensions": {"width": 1.4, "length": 0.7, "height": 0.75},
                    },
                    {
                        "asset_id": "warm_oak",
                        "category": "desk",
                        "glb_path": "warm.glb",
                        "qa_status": "approved",
                        "styles": ["modern", "warm", "wood", "oak"],
                        "dimensions": {"width": 1.4, "length": 0.7, "height": 0.75},
                    },
                    {
                        "asset_id": "perfect_style_wrong_size",
                        "category": "desk",
                        "glb_path": "oversize.glb",
                        "qa_status": "approved",
                        "styles": ["modern", "warm", "wood", "oak", "clean_lines"],
                        "dimensions": {"width": 4.0, "length": 2.0, "height": 2.0},
                    },
                ]
            }
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            brief = build_baseline_brief("A warm modern oak study with clean lines.")
            contract = build_scene_dna_contract(brief, brief.get("architecture"), [])
            rejections: list[dict] = []
            selected = AssetRegistry(manifest_path).find(
                "desk",
                brief["styles"],
                target_dimensions={"width": 1.4, "length": 0.7, "height": 0.75},
                rejections=rejections,
                scene_dna_contract=contract,
                object_id="explicit_desk",
            )
        self.assertIsNotNone(selected)
        self.assertEqual(selected["asset_id"], "warm_oak")
        self.assertTrue(selected["_scene_dna_score"]["passes_soft_threshold"])
        self.assertEqual(
            {item["asset_id"] for item in rejections},
            {"perfect_style_wrong_size"},
        )

    def test_material_and_palette_contrast_do_not_force_style_collapse(self) -> None:
        brief = build_baseline_brief("A warm modern oak study.")
        contract = build_scene_dna_contract(brief, brief.get("architecture"), [])
        score = score_asset_candidate(
            {"styles": ["modern", "office", "black", "metal"]},
            contract,
            object_id="office_chair",
        )
        self.assertTrue(score["passes_soft_threshold"], score)
        self.assertEqual(
            score["facet_results"]["material"]["reason"],
            "allowed_object_contrast",
        )

    def test_plan_mode_writes_contract_funnel_and_nonpassing_certificate(self) -> None:
        brief = build_baseline_brief(
            "A warm modern bedroom with exactly two storage boxes."
        )
        with tempfile.TemporaryDirectory() as tmp:
            report = resolve_assets(
                brief,
                Path(tmp),
                mode="plan",
                manifest_path=None,
                trellis_url="http://127.0.0.1:8082",
                seed=1,
                timeout=1,
                steps=1,
                texture_size=64,
                decimation_target=100,
                pipeline_type="512",
                preprocess_image=False,
                max_new_assets=40,
            )
            contract = json.loads(Path(report["scene_dna_contract"]).read_text())
            generation_plan = json.loads(
                Path(report["missing_asset_generation_plan"]).read_text()
            )
            certificate = json.loads(
                Path(report["harmony_certificate"]).read_text()
            )
        self.assertEqual(
            generation_plan["scene_dna_contract_hash"], contract["contract_hash"]
        )
        self.assertEqual(generation_plan["candidate_funnel"]["isolated_2d_candidates"], 4)
        self.assertEqual(
            generation_plan["candidate_funnel"]["max_candidates_promoted_to_trellis2"],
            2,
        )
        self.assertTrue(
            all(
                entry["asset_generation_spec"]["scene_dna"][
                    "hard_constraints_remain_authoritative"
                ]
                for entry in generation_plan["generation_entries"]
            )
        )
        self.assertTrue(certificate["style_review_required"])
        self.assertFalse(certificate["claims_visual_harmony_pass"])

    def test_generated_asset_cannot_pass_without_multiview_evaluation(self) -> None:
        brief = build_baseline_brief("A modern warm bedroom.")
        contract = build_scene_dna_contract(brief, brief.get("architecture"), [])
        score = score_asset_candidate(
            {"styles": ["modern", "warm"]}, contract, object_id="bed"
        )
        certificate = build_harmony_certificate(
            contract,
            [
                {
                    "object_id": "bed",
                    "category": "bed",
                    "asset_id": "generated_bed",
                    "status": "generated",
                    "dimension_resolution": {"accepted": True},
                    "scene_dna_score": score,
                }
            ],
        )
        self.assertTrue(certificate["style_review_required"])
        self.assertFalse(certificate["claims_visual_harmony_pass"])
        self.assertEqual(
            certificate["records"][0]["acceptance"],
            "multiview_evaluation_required",
        )

    def test_multiview_compact_asset_passes_clean_rectangular_silhouettes(self) -> None:
        brief = build_baseline_brief("A warm beige modern bedroom.")
        contract = build_scene_dna_contract(brief, brief.get("architecture"), [])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            views = {}
            for axis in ("+x", "-x", "+y", "-y"):
                path = root / f"{axis}.png"
                rgba = np.zeros((96, 96, 4), dtype=np.uint8)
                rgba[20:78, 16:80] = (210, 190, 158, 255)
                Image.fromarray(rgba, mode="RGBA").save(path)
                views[axis] = str(path)
            report = evaluate_multiview_manifest(
                {
                    "views": {"box": views},
                    "normalization": {
                        "box": {"axis_scale_anisotropy": 1.2}
                    },
                },
                contract,
                object_id="box",
                category="storage_box",
                structure_profile={
                    "profile": "compact_orthogonal",
                    "compact_silhouette_required": True,
                    "minimum_bbox_fill": 0.88,
                    "maximum_detached_ratio": 0.0075,
                },
            )
        self.assertTrue(report["structure_gate_passed"], report)
        self.assertTrue(report["automated_pixel_multiview_pass"], report)
        self.assertFalse(report["semantic_category_verified"])

    def test_multiview_optional_semantic_scorer_verifies_category_and_style(self) -> None:
        class FakeScorer:
            model_name_or_path = "fake-siglip"

            def score(self, _path: Path, _contract: dict) -> dict:
                return {"evaluated": True, "score": 0.82, "gate_passed": True}

            def score_text_contrast(self, _path: Path, **_kwargs) -> dict:
                return {"evaluated": True, "score": 0.72}

        contract = {
            "contract_hash": "contract",
            "global_profile": {
                "desired_tags": [
                    {"tag": "warm"},
                    {"tag": "modern"},
                    {"tag": "clean_lines"},
                ]
            },
            "object_profiles": {
                "box": {
                    "individuality_tags": ["beige"],
                    "semantic_form_contract": {
                        "identity": "storage box",
                        "shape_profile": "compact_orthogonal",
                        "required_parts": ["box body", "lid"],
                    },
                }
            },
            "selection_policy": {"minimum_harmony_score": 0.55},
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            views = {}
            for axis in ("+x", "-x", "+y", "-y"):
                path = root / f"semantic_{axis}.png"
                rgba = np.zeros((96, 96, 4), dtype=np.uint8)
                rgba[20:78, 16:80] = (210, 190, 158, 255)
                Image.fromarray(rgba, mode="RGBA").save(path)
                views[axis] = str(path)
            report = evaluate_multiview_manifest(
                {
                    "views": {"box": views},
                    "normalization": {"box": {"axis_scale_anisotropy": 1.0}},
                },
                contract,
                object_id="box",
                category="storage_box",
                structure_profile=structure_profile_for_object(
                    {}, {"shape_profile": "compact_orthogonal"}
                ),
                semantic_scorer=FakeScorer(),
            )
        self.assertTrue(report["semantic_embedding_evaluated"])
        self.assertTrue(report["semantic_category_verified"])
        self.assertTrue(report["semantic_style_verified"])
        self.assertEqual(
            report["semantic_style_multiview"]["model"], "fake-siglip"
        )
        self.assertTrue(report["automated_pixel_multiview_pass"], report)

    def test_multiview_rejects_compact_asset_with_missing_side_and_fragment(self) -> None:
        brief = build_baseline_brief("A warm beige modern bedroom.")
        contract = build_scene_dna_contract(brief, brief.get("architecture"), [])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            views = {}
            for index, axis in enumerate(("+x", "-x", "+y", "-y")):
                path = root / f"view_{index}.png"
                rgba = np.zeros((96, 96, 4), dtype=np.uint8)
                rgba[20:78, 16:80] = (210, 190, 158, 255)
                if axis == "+y":
                    rgba[52:78, 34:70] = 0
                    rgba[82:88, 42:48] = (30, 30, 30, 255)
                Image.fromarray(rgba, mode="RGBA").save(path)
                views[axis] = str(path)
            report = evaluate_multiview_manifest(
                {
                    "views": {"box": views},
                    "normalization": {
                        "box": {"axis_scale_anisotropy": 1.2}
                    },
                },
                contract,
                object_id="box",
                category="storage_box",
                structure_profile={
                    "profile": "compact_orthogonal",
                    "compact_silhouette_required": True,
                    "minimum_bbox_fill": 0.88,
                    "maximum_detached_ratio": 0.0075,
                },
            )
        self.assertFalse(report["structure_gate_passed"])
        self.assertFalse(report["automated_pixel_multiview_pass"])
        self.assertEqual(report["acceptance"], "regenerate_or_style_review_required")

    def test_multiview_rejects_enclosed_holes_in_closed_compact_profile(self) -> None:
        brief = build_baseline_brief("A warm beige modern bedroom.")
        contract = build_scene_dna_contract(brief, brief.get("architecture"), [])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            views = {}
            for axis in ("+x", "-x", "+y", "-y"):
                path = root / f"compact_hole_{axis}.png"
                rgba = np.zeros((96, 96, 4), dtype=np.uint8)
                rgba[20:78, 16:80] = (210, 190, 158, 255)
                rgba[36:44, 42:50] = 0
                Image.fromarray(rgba, mode="RGBA").save(path)
                views[axis] = str(path)
            report = evaluate_multiview_manifest(
                {
                    "views": {"box": views},
                    "normalization": {"box": {"axis_scale_anisotropy": 1.2}},
                },
                contract,
                object_id="box",
                category="storage_box",
                structure_profile=structure_profile_for_object(
                    {}, {"shape_profile": "compact_orthogonal"}
                ),
            )
        self.assertFalse(report["structure_gate_passed"], report)
        self.assertFalse(report["structure_gate"]["internal_hole_passed"])

    def test_multiview_rejects_connected_staging_plane_below_slender_object(self) -> None:
        brief = build_baseline_brief("A warm modern room.")
        contract = build_scene_dna_contract(brief, brief.get("architecture"), [])
        profile = structure_profile_for_object(
            {}, {"shape_profile": "slender_radial"}
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            clean_views = {}
            staged_views = {}
            for axis in ("+x", "-x", "+y", "-y"):
                clean_path = root / f"clean_lamp_{axis}.png"
                clean = np.zeros((96, 96, 4), dtype=np.uint8)
                clean[10:25, 35:61] = (210, 190, 158, 255)
                clean[24:75, 46:50] = (210, 190, 158, 255)
                clean[72:78, 38:58] = (210, 190, 158, 255)
                Image.fromarray(clean, mode="RGBA").save(clean_path)
                clean_views[axis] = str(clean_path)

                staged_path = root / f"staged_lamp_{axis}.png"
                staged = clean.copy()
                staged[75:79, 5:91] = (210, 190, 158, 255)
                Image.fromarray(staged, mode="RGBA").save(staged_path)
                staged_views[axis] = str(staged_path)
            clean_report = evaluate_multiview_manifest(
                {
                    "views": {"lamp": clean_views},
                    "normalization": {"lamp": {"axis_scale_anisotropy": 1.0}},
                },
                contract,
                object_id="lamp",
                category="table_lamp",
                structure_profile=profile,
            )
            staged_report = evaluate_multiview_manifest(
                {
                    "views": {"lamp": staged_views},
                    "normalization": {"lamp": {"axis_scale_anisotropy": 1.0}},
                },
                contract,
                object_id="lamp",
                category="table_lamp",
                structure_profile=profile,
            )
        self.assertTrue(clean_report["structure_gate"]["lower_overhang_passed"])
        self.assertFalse(staged_report["structure_gate_passed"], staged_report)
        self.assertFalse(staged_report["structure_gate"]["lower_overhang_passed"])

    def test_multiview_rejects_full_width_platform_below_footwear(self) -> None:
        brief = build_baseline_brief("A warm modern room.")
        contract = build_scene_dna_contract(brief, brief.get("architecture"), [])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            views = {}
            for axis in ("+x", "-x", "+y", "-y"):
                path = root / f"footwear_platform_{axis}.png"
                rgba = np.zeros((96, 96, 4), dtype=np.uint8)
                rgba[30:62, 25:72] = (210, 190, 158, 255)
                rgba[60:78, 8:88] = (210, 190, 158, 255)
                Image.fromarray(rgba, mode="RGBA").save(path)
                views[axis] = str(path)
            report = evaluate_multiview_manifest(
                {
                    "views": {"slipper": views},
                    "normalization": {
                        "slipper": {
                            "axis_scale_anisotropy": 1.0,
                            "layered_footprint": {
                                "evaluated": True,
                                "lower_to_upper_footprint_area_ratio": 4.0,
                            },
                        }
                    },
                },
                contract,
                object_id="slipper",
                category="slipper",
                structure_profile=structure_profile_for_object(
                    {}, {"shape_profile": "open_back_footwear"}
                ),
            )
        self.assertFalse(report["structure_gate_passed"], report)
        self.assertFalse(report["structure_gate"]["lower_platform_passed"])

    def test_structure_profile_compiles_from_shape_language_not_category(self) -> None:
        compact = structure_profile_for_object(
            {
                "category": "unseen_container_name",
                "asset_generation_spec": {
                    "shape_guidance": "one closed rectangular object with straight edges"
                },
            }
        )
        open_object = structure_profile_for_object(
            {
                "category": "storage_box",
                "asset_generation_spec": {
                    "shape_guidance": "an open wire frame with separated legs"
                },
            }
        )
        self.assertEqual(compact["profile"], "compact_orthogonal")
        self.assertTrue(compact["compact_silhouette_required"])
        self.assertEqual(open_object["profile"], "general_object")
        self.assertFalse(open_object["compact_silhouette_required"])

    def test_structure_profile_allows_semantic_assembly_without_relaxing_lamp(self) -> None:
        chair = structure_profile_for_object(
            {}, {"shape_profile": "skeletal_support"}
        )
        lamp = structure_profile_for_object(
            {}, {"shape_profile": "slender_radial"}
        )
        self.assertEqual(chair["profile"], "skeletal_support")
        self.assertEqual(chair["maximum_detached_ratio"], 0.26)
        self.assertEqual(lamp["profile"], "slender_radial")
        self.assertLess(lamp["maximum_detached_ratio"], 0.08)

    def test_structure_profile_preserves_open_repeated_frame_contract(self) -> None:
        profile = structure_profile_for_object(
            {}, {"shape_profile": "open_repeated_frame"}
        )
        self.assertEqual(profile["profile"], "open_repeated_frame")
        self.assertFalse(profile["compact_silhouette_required"])
        self.assertEqual(
            profile["evidence"],
            "semantic_form_contract:open_repeated_frame",
        )

    def test_certificate_records_automated_multiview_without_semantic_claim(self) -> None:
        brief = build_baseline_brief("A warm modern bedroom.")
        contract = build_scene_dna_contract(brief, brief.get("architecture"), [])
        report = {
            "schema": "scene_dna_generated_asset_multiview_v1",
            "scene_dna_contract_hash": contract["contract_hash"],
            "evaluated": True,
            "automated_score": 0.82,
            "automated_pixel_multiview_pass": True,
            "semantic_embedding_evaluated": False,
        }
        certificate = build_harmony_certificate(
            contract,
            [
                {
                    "object_id": "box",
                    "category": "storage_box",
                    "asset_id": "generated_box",
                    "status": "generated",
                    "dimension_resolution": {"accepted": True},
                    "scene_dna_multiview": report,
                }
            ],
        )
        self.assertEqual(
            certificate["records"][0]["acceptance"],
            "automated_multiview_pass_semantic_review_required",
        )
        self.assertTrue(certificate["all_generated_automated_multiview_checks_pass"])
        self.assertFalse(certificate["claims_visual_harmony_pass"])

    def test_resolver_regenerates_after_multiview_failure_then_stops_on_pass(self) -> None:
        brief = build_baseline_brief(
            "A warm modern bedroom with exactly one storage box."
        )
        box = next(obj for obj in brief["objects"] if obj["category"] == "storage_box")
        brief["objects"] = [box]
        brief["asset_inventory"] = [
            {
                "category": "storage_box",
                "requested_count": 1,
                "required_count": 1,
                "instance_ids": [box["id"]],
            }
        ]
        render_count = 0

        def fake_generate(obj: dict, output_path: Path, *_args, **_kwargs) -> dict:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"glb")
            return {"job_id": f"job-{output_path.parent.parent.name}", "bridge_metadata": {}}

        def fake_multiview(**kwargs) -> dict:
            nonlocal render_count
            render_count += 1
            passed = render_count == 2
            return {
                "schema": "scene_dna_generated_asset_multiview_v1",
                "scene_dna_contract_hash": kwargs["contract"]["contract_hash"],
                "evaluated": True,
                "structure_gate_passed": passed,
                "automated_score": 0.8 if passed else 0.2,
                "automated_pixel_multiview_pass": passed,
                "semantic_embedding_evaluated": False,
            }

        with tempfile.TemporaryDirectory() as tmp, patch(
            "sage.experiments.codex_trellis_scene_v2.assets.bridge_health",
            return_value={"ok": True},
        ), patch(
            "sage.experiments.codex_trellis_scene_v2.assets.generate_trellis_asset",
            side_effect=fake_generate,
        ), patch(
            "sage.experiments.codex_trellis_scene_v2.assets.render_and_evaluate_generated_asset",
            side_effect=fake_multiview,
        ):
            fake_blender = Path(tmp) / "blender"
            fake_blender.write_bytes(b"executable placeholder")
            report = resolve_assets(
                brief,
                Path(tmp),
                mode="trellis2",
                manifest_path=None,
                trellis_url="http://127.0.0.1:8082",
                seed=1,
                timeout=1,
                steps=1,
                texture_size=64,
                decimation_target=100,
                pipeline_type="512",
                preprocess_image=False,
                max_new_assets=1,
                blender_bin=fake_blender,
            )
        result = report["results"][0]
        self.assertEqual(report["trellis_generation_attempt_count"], 2)
        self.assertEqual(result["scene_dna_harmonization"]["selected_attempt"], 1)
        self.assertTrue(
            result["scene_dna_multiview"]["automated_pixel_multiview_pass"]
        )

    def test_resolver_generates_uncertain_promoted_candidate_with_same_seed(self) -> None:
        brief = build_baseline_brief(
            "A warm modern bedroom with exactly one storage box."
        )
        box = next(obj for obj in brief["objects"] if obj["category"] == "storage_box")
        brief["objects"] = [box]
        brief["asset_inventory"] = [
            {
                "category": "storage_box",
                "requested_count": 1,
                "required_count": 1,
                "instance_ids": [box["id"]],
            }
        ]
        generation_calls: list[dict] = []

        def fake_generate(obj: dict, output_path: Path, *_args, **kwargs) -> dict:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"glb")
            generation_calls.append(dict(kwargs))
            if kwargs.get("reference_image_path") is not None:
                return {"job_id": "job-promoted", "bridge_metadata": {}}
            primary_reference = Path(tmp) / "primary.png"
            promoted_reference = Path(tmp) / "promoted.png"
            Image.new("RGBA", (8, 8), "white").save(primary_reference)
            Image.new("RGBA", (8, 8), "gray").save(promoted_reference)
            return {
                "job_id": "job-primary",
                "bridge_metadata": {
                    "reference_image_path": str(primary_reference),
                    "scene_dna_candidate_selection": {
                        "promoted_reference_image_paths": [
                            str(primary_reference),
                            str(promoted_reference),
                        ]
                    },
                },
            }

        def fake_multiview(**kwargs) -> dict:
            promoted = "candidate_02" in str(kwargs["output_dir"])
            return {
                "schema": "scene_dna_generated_asset_multiview_v1",
                "scene_dna_contract_hash": kwargs["contract"]["contract_hash"],
                "evaluated": True,
                "structure_gate_passed": True,
                "automated_score": 0.9 if promoted else 0.8,
                "automated_pixel_multiview_pass": True,
                "semantic_embedding_evaluated": False,
            }

        with tempfile.TemporaryDirectory() as tmp, patch(
            "sage.experiments.codex_trellis_scene_v2.assets.bridge_health",
            return_value={"ok": True},
        ), patch(
            "sage.experiments.codex_trellis_scene_v2.assets.generate_trellis_asset",
            side_effect=fake_generate,
        ), patch(
            "sage.experiments.codex_trellis_scene_v2.assets.render_and_evaluate_generated_asset",
            side_effect=fake_multiview,
        ):
            fake_blender = Path(tmp) / "blender"
            fake_blender.write_bytes(b"executable placeholder")
            report = resolve_assets(
                brief,
                Path(tmp),
                mode="trellis2",
                manifest_path=None,
                trellis_url="http://127.0.0.1:8082",
                seed=11,
                timeout=1,
                steps=1,
                texture_size=64,
                decimation_target=100,
                pipeline_type="512",
                preprocess_image=False,
                max_new_assets=1,
                blender_bin=fake_blender,
            )
        result = report["results"][0]
        self.assertEqual(len(generation_calls), 2)
        self.assertEqual(generation_calls[0]["seed"], generation_calls[1]["seed"])
        self.assertEqual(
            result["scene_dna_harmonization"]["selected_candidate_rank"], 2
        )


if __name__ == "__main__":
    unittest.main()
