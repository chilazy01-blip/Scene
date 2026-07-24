from __future__ import annotations

import json
import tempfile
import unittest
from argparse import Namespace
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from sage.server.trellis2_flux_bridge_server import Trellis2BridgeRuntime

from ..architecture import plan_architecture
from ..assets import AssetRegistry, resolve_assets
from ..brief import (
    apply_expansion_grounding,
    build_asset_generation_spec,
    build_baseline_brief,
    expand_prompt,
)
from ..constraint_scopes import evaluate_constraint_scope_envelopes
from ..dimensions import dimension_policy_for_category, resolve_dimension_adaptation
from ..instance_groups import (
    apply_instance_group_postprocess,
    ground_instance_groups,
    validate_instance_groups,
)
from ..orientation import (
    evaluate_facing,
    evaluate_relation_facing,
    solve_facing_yaw,
)
from ..planner import rules_layout
from ..pilot_asset import PILOT_ASSET_DEFINITIONS
from ..policies import (
    FLOOR_MATERIAL_PRESETS,
    WALL_MATERIAL_PRESETS,
    detect_explicit_category_counts,
)
from ..repair import deterministic_repair
from ..scene_graph import build_typed_scene_graph, validate_typed_scene_graph
from ..spatial_constraints import evaluate_spatial_relations
from ..validator import validate_layout


class BriefTest(unittest.TestCase):
    def test_one_pair_of_slippers_means_two_physical_instances(self) -> None:
        counts = detect_explicit_category_counts(
            "Include exactly one pair of slippers neatly near the foot of the bed."
        )
        self.assertEqual(counts["slipper"], 2)

    def test_explicit_pair_creates_one_typed_execution_group(self) -> None:
        brief = build_baseline_brief(
            "A modern bedroom with exactly one pair of slippers near the foot of the bed."
        )
        groups = brief["instance_groups"]
        self.assertEqual(len(groups), 1)
        group = groups[0]
        self.assertEqual(group["group_kind"], "paired_instances")
        self.assertEqual(group["cardinality"], 2)
        self.assertEqual(
            {member["role"] for member in group["members"]},
            {"left_member", "right_member"},
        )
        self.assertEqual(group["asset_contract"]["match_mode"], "same_family")
        self.assertEqual(group["layout_contract"]["anchor_id"], "bed")
        self.assertEqual(group["layout_contract"]["anchor_zone"], "front")
        self.assertTrue(group["members_remain_independent_instances"])

    def test_sparse_bedroom_gets_functional_required_objects(self) -> None:
        brief = build_baseline_brief("A bedroom.")
        self.assertEqual(brief["room_type"], "bedroom")
        self.assertTrue(brief["under_specified"])
        ids = {obj["id"] for obj in brief["objects"]}
        self.assertTrue({"bed", "nightstand_left", "nightstand_right", "wardrobe"} <= ids)
        self.assertTrue(brief["asset_inventory"])
        self.assertTrue(all(not obj.get("asset_prompt") for obj in brief["objects"]))

    def test_kitchen_detection_adds_work_triangle_assets(self) -> None:
        brief = build_baseline_brief("一个现代厨房，需要冰箱、水槽和灶台。")
        self.assertEqual(brief["room_type"], "kitchen")
        ids = {obj["id"] for obj in brief["objects"]}
        self.assertTrue({"refrigerator", "sink_cabinet", "stove"} <= ids)

    def test_bedside_table_does_not_add_generic_side_table(self) -> None:
        brief = build_baseline_brief("A bedroom with balanced bedside tables.")
        ids = {obj["id"] for obj in brief["objects"]}
        self.assertNotIn("explicit_side_table", ids)

    def test_explicit_objects_are_preserved_above_automatic_target(self) -> None:
        brief = build_baseline_brief(
            "A bedroom with wall art, a window, an area rug, an accent chair and a floor lamp.",
            target_max_objects=10,
        )
        categories = {obj["category"] for obj in brief["objects"]}
        self.assertTrue({"wall_art", "window", "area_rug", "accent_chair", "floor_lamp"} <= categories)
        self.assertGreater(len(brief["objects"]), brief["object_budget"]["target_max"])

    def test_clear_plural_requirements_create_exact_instances(self) -> None:
        prompt_path = (
            Path(__file__).parents[1] / "prompts" / "bedroom_rgbd_front_strict.txt"
        )
        brief = build_baseline_brief(prompt_path.read_text(encoding="utf-8"))
        counts: dict[str, int] = {}
        for obj in brief["objects"]:
            counts[str(obj["category"])] = counts.get(str(obj["category"]), 0) + 1
        self.assertEqual(counts["nightstand"], 2)
        self.assertEqual(counts["table_lamp"], 2)
        self.assertEqual(counts["storage_box"], 2)
        self.assertNotIn("pillow", counts)
        self.assertEqual(counts["slipper"], 2)
        self.assertEqual(brief["explicit_category_counts"]["pillow"], 2)
        bed = next(obj for obj in brief["objects"] if obj["category"] == "bed")
        pillow_requirement = next(
            item
            for item in bed["component_requirements"]
            if item["category"] == "pillow"
        )
        self.assertEqual(pillow_requirement["requested_count"], 2)
        self.assertFalse(pillow_requirement["physical_instances_materialized"])
        self.assertEqual(
            brief["component_resolution"][0]["standalone_instances_removed"],
            ["explicit_pillow_1", "explicit_pillow_2"],
        )
        self.assertNotIn("potted_plant", counts)
        self.assertNotIn("alarm_clock", counts)
        self.assertGreater(len(brief["objects"]), brief["object_budget"]["target_max"])
        self.assertTrue(brief["camera_requirements"]["strict_front_facing"])
        self.assertTrue(brief["camera_requirements"]["centered_composition"])


class SemanticGroundingTest(unittest.TestCase):
    @staticmethod
    def _expanded_delta() -> dict:
        return {
            "expanded_description": "A grounded bedroom scene.",
            "styles": ["modern"],
            "optional_categories": [],
            "layout_preferences": [],
            "relation_updates": [
                {
                    "source": "bedside_mug",
                    "type": "supported_by",
                    "target": "explicit_desk",
                    "strength": "hard",
                    "parameters": {"support_offset": [0.38, 0.0]},
                    "source_evidence": "cup rests on the desktop",
                },
                {
                    "source": "explicit_office_chair",
                    "type": "faces",
                    "target": "explicit_desk",
                    "strength": "hard",
                    "parameters": {"tolerance_degrees": 25.0},
                    "source_evidence": "chair facing the desk",
                },
                {
                    "source": "explicit_desk",
                    "type": "against_wall",
                    "target": "east_wall",
                    "strength": "hard",
                    "source_evidence": "desk against the east wall",
                },
                {
                    "source": "wardrobe",
                    "type": "against_wall",
                    "target": "west_wall",
                    "strength": "hard",
                    "source_evidence": "wardrobe against the west wall",
                },
                {
                    "source": "nightstand_left",
                    "type": "left_of",
                    "target": "bed",
                    "strength": "hard",
                    "parameters": {"reference_frame": "target_local"},
                    "source_evidence": "on the left and right sides of the bed",
                },
                {
                    "source": "nightstand_right",
                    "type": "right_of",
                    "target": "bed",
                    "strength": "hard",
                    "parameters": {"reference_frame": "target_local"},
                    "source_evidence": "on the left and right sides of the bed",
                },
                {
                    "source": "nightstand_left",
                    "type": "aligned_with",
                    "target": "bed",
                    "strength": "hard",
                    "parameters": {
                        "source_anchor": "back_face",
                        "target_anchor": "back_face",
                        "axis": "depth",
                        "alignment_tolerance": 0.1,
                    },
                    "source_evidence": "bedside tables share the bed back edge",
                },
                {
                    "source": "nightstand_right",
                    "type": "aligned_with",
                    "target": "bed",
                    "strength": "hard",
                    "parameters": {
                        "source_anchor": "back_face",
                        "target_anchor": "back_face",
                        "axis": "depth",
                        "alignment_tolerance": 0.1,
                    },
                    "source_evidence": "bedside tables share the bed back edge",
                },
                {
                    "source": "nightstand_left",
                    "type": "mirror_symmetric",
                    "target": "nightstand_right",
                    "strength": "hard",
                    "parameters": {
                        "reference_id": "bed",
                        "axis": "left_right",
                        "alignment_tolerance": 0.1,
                    },
                    "source_evidence": "symmetrically on both sides of the bed",
                },
            ],
            "attribute_updates": [
                {
                    "object_id": "bedside_mug",
                    "appearance_terms": ["ceramic"],
                    "source_evidence": "ceramic cup",
                },
                {
                    "object_id": "explicit_book_stack",
                    "appearance_terms": [],
                    "source_evidence": "compact stack of books",
                },
            ],
            "component_updates": [
                {
                    "parent_id": "bed",
                    "component_category": "pillow",
                    "appearance_terms": [],
                    "source_evidence": "two pillows belong to the bed",
                }
            ],
        }

    def test_rigid_instance_group_membership_cannot_overlap(self) -> None:
        brief = build_baseline_brief(
            "A modern bedroom with two storage boxes and a pair of slippers."
        )
        slipper_ids = [
            str(obj["id"]) for obj in brief["objects"] if obj["category"] == "slipper"
        ]
        box_id = next(
            str(obj["id"]) for obj in brief["objects"] if obj["category"] == "storage_box"
        )
        report = ground_instance_groups(
            brief,
            [
                {
                    "group_id": "overlapping_set",
                    "group_kind": "matched_set",
                    "cardinality": 2,
                    "members": [
                        {"object_id": slipper_ids[0], "role": "member_1"},
                        {"object_id": box_id, "role": "member_2"},
                    ],
                    "asset_contract": {
                        "match_mode": "same_family",
                        "fallback": "same_asset_reuse",
                    },
                    "layout_contract": {"arrangement": "side_by_side"},
                    "source_evidence": "pair of slippers",
                }
            ],
        )
        self.assertEqual(report["accepted_count"], 0)
        self.assertEqual(report["rejected_count"], 1)
        self.assertIn(
            slipper_ids[0],
            report["rejected"][0]["overlapping_object_ids"],
        )

    def test_group_postprocess_compacts_roles_and_normalizes_asset_fronts(self) -> None:
        members = [
            {
                "id": "slipper_left",
                "category": "slipper",
                "placement_type": "floor",
                "dimensions": {"width": 0.28, "length": 0.12, "height": 0.08},
                "x": 1.0,
                "y": 1.0,
                "z": 0.0,
                "yaw": 0.0,
                "asset_canonical_front": {"axis": "+y", "confidence": 0.9},
            },
            {
                "id": "slipper_right",
                "category": "slipper",
                "placement_type": "floor",
                "dimensions": {"width": 0.28, "length": 0.12, "height": 0.08},
                "x": 2.0,
                "y": 1.0,
                "z": 0.0,
                "yaw": 0.0,
                "asset_canonical_front": {"axis": "-y", "confidence": 0.9},
            },
        ]
        group = {
            "group_id": "slipper_pair",
            "group_kind": "paired_instances",
            "cardinality": 2,
            "members": [
                {"object_id": "slipper_left", "role": "left_member"},
                {"object_id": "slipper_right", "role": "right_member"},
            ],
            "asset_contract": {
                "match_mode": "same_family",
                "fallback": "same_asset_reuse",
            },
            "layout_contract": {
                "arrangement": "side_by_side",
                "reference_frame": "room",
                "shared_orientation": True,
                "orientation_tolerance_degrees": 15.0,
                "min_gap": 0.03,
                "target_gap": 0.08,
                "max_gap": 0.20,
                "allow_member_respacing": True,
                "allow_rigid_translation": True,
            },
        }
        plan = {
            "room": {"width": 4.0, "length": 3.0, "height": 2.7},
            "objects": members,
            "relations": [],
            "instance_groups": [group],
        }
        resolution = apply_instance_group_postprocess(plan)
        violations, metrics = validate_instance_groups(plan)
        self.assertEqual(resolution["adjusted_count"], 1)
        self.assertEqual(metrics["hard_violation_count"], 0, violations)
        self.assertLess(members[0]["x"], members[1]["x"])
        self.assertAlmostEqual(metrics["results"][0]["gaps"][0], 0.08)
        self.assertAlmostEqual(
            metrics["results"][0]["orientation_errors_degrees"][0], 0.0
        )

    def test_group_asset_resolution_reuses_one_curated_asset_without_merging_instances(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "left.glb").write_bytes(b"left")
            (root / "right.glb").write_bytes(b"right")
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "assets": [
                            {
                                "asset_id": "slipper_left_asset",
                                "category": "slipper",
                                "styles": ["modern"],
                                "qa_status": "approved",
                                "glb_path": "left.glb",
                                "dimensions": {
                                    "width": 0.28,
                                    "length": 0.12,
                                    "height": 0.08,
                                },
                            },
                            {
                                "asset_id": "slipper_right_asset",
                                "category": "slipper",
                                "styles": ["modern"],
                                "qa_status": "approved",
                                "glb_path": "right.glb",
                                "dimensions": {
                                    "width": 0.28,
                                    "length": 0.12,
                                    "height": 0.08,
                                },
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            brief = build_baseline_brief(
                "A modern bedroom with exactly one pair of slippers."
            )
            report = resolve_assets(
                brief,
                root / "run",
                mode="plan",
                manifest_path=manifest,
                trellis_url="http://127.0.0.1:1",
                seed=1,
                timeout=1.0,
                steps=1,
                texture_size=64,
                decimation_target=1000,
                pipeline_type="512",
                preprocess_image=False,
                max_new_assets=4,
            )
            slippers = [
                obj for obj in brief["objects"] if obj["category"] == "slipper"
            ]
            self.assertEqual(len(slippers), 2)
            self.assertEqual(
                {obj["asset_id"] for obj in slippers},
                {"slipper_left_asset"},
            )
            self.assertEqual(
                {
                    obj["instance_group_asset_family"]
                    for obj in slippers
                },
                {"same_asset:slipper_left_asset"},
            )
            self.assertEqual(
                report["instance_group_resolution"]["group_count"], 1
            )

    def test_codex_typed_delta_overrides_policy_defaults_before_graph_build(self) -> None:
        prompt_path = (
            Path(__file__).parents[1]
            / "prompts"
            / "bedroom_typed_graph_component_strict.txt"
        )
        prompt = prompt_path.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmp, patch(
            "sage.experiments.codex_trellis_scene_v2.brief.run_codex_json",
            return_value=self._expanded_delta(),
        ):
            brief = expand_prompt(
                prompt,
                Path(tmp),
                room_type_override=None,
                mode="codex",
                model="test-model",
            )

        by_id = {obj["id"]: obj for obj in brief["objects"]}
        self.assertEqual(by_id["bedside_mug"]["support_id"], "explicit_desk")
        self.assertEqual(by_id["bedside_mug"]["placement_type"], "support")
        self.assertEqual(by_id["explicit_desk"]["preferred_wall"], "east")
        self.assertEqual(by_id["explicit_desk"]["wall_constraint_strength"], "hard")
        self.assertEqual(by_id["explicit_desk"]["facing_constraint"]["wall"], "east")
        self.assertEqual(by_id["wardrobe"]["preferred_wall"], "west")
        self.assertEqual(by_id["wardrobe"]["wall_constraint_strength"], "hard")
        self.assertEqual(by_id["wardrobe"]["facing_constraint"]["wall"], "west")
        self.assertEqual(brief["semantic_grounding"]["accepted_count"], 12)
        self.assertEqual(brief["semantic_grounding"]["rejected_count"], 0)
        self.assertEqual(brief["semantic_grounding"]["normalization_count"], 2)
        side_relations = {
            relation["source"]: relation
            for relation in brief["relations"]
            if isinstance(relation, dict)
            and relation.get("source") in {"nightstand_left", "nightstand_right"}
            and relation.get("type") in {"left_of", "right_of"}
        }
        self.assertEqual(side_relations["nightstand_left"]["parameters"]["reference_frame"], "room")
        self.assertEqual(side_relations["nightstand_right"]["parameters"]["reference_frame"], "room")
        self.assertTrue(side_relations["nightstand_left"]["parameters"]["role_locked"])

        graph = build_typed_scene_graph(brief, plan_architecture(brief))
        nodes = {node["id"]: node for node in graph["nodes"]}
        self.assertEqual(nodes["bedside_mug"]["parent_id"], "explicit_desk")
        relation_keys = {
            (edge["source"], edge["type"], edge["target"])
            for edge in graph["relations"]
        }
        self.assertIn(
            ("explicit_office_chair", "faces", "explicit_desk"), relation_keys
        )
        self.assertIn(
            ("explicit_desk", "against_wall", "east_wall"), relation_keys
        )
        self.assertIn(("wardrobe", "against_wall", "west_wall"), relation_keys)
        self.assertIn(("nightstand_left", "aligned_with", "bed"), relation_keys)
        self.assertIn(
            ("nightstand_left", "mirror_symmetric", "nightstand_right"),
            relation_keys,
        )
        self.assertNotIn(("wardrobe", "against_wall", "east_wall"), relation_keys)

        mug_spec = build_asset_generation_spec(
            by_id["bedside_mug"], brief["styles"], prompt
        )
        book_spec = build_asset_generation_spec(
            by_id["explicit_book_stack"], brief["styles"], prompt
        )
        self.assertEqual(mug_spec["appearance_terms"], ["ceramic"])
        self.assertNotIn("ceramic", book_spec["appearance_terms"])

    def test_tucked_under_relation_requires_named_target_free_space(self) -> None:
        brief = build_baseline_brief("A study with a desk and office chair.")
        desk = next(obj for obj in brief["objects"] if obj["category"] == "desk")
        chair = next(
            obj for obj in brief["objects"] if obj["category"] == "office_chair"
        )
        brief["relations"].append(
            {
                "source": chair["id"],
                "type": "tucked_under",
                "target": desk["id"],
                "strength": "hard",
                "parameters": {
                    "free_space_id": "under_desk",
                    "reference_frame": "target_local",
                    "preserve_facing": True,
                },
            }
        )
        graph = build_typed_scene_graph(brief, plan_architecture(brief))
        self.assertTrue(graph["validation"]["ok"], graph["validation"])
        relation = next(
            edge
            for edge in graph["relations"]
            if edge["type"] == "tucked_under"
        )
        self.assertEqual(relation["constraint_class"], "free_space")
        self.assertEqual(relation["strength"], "hard")
        self.assertEqual(
            relation["parameters"]["free_space_id"], "under_desk"
        )

        relation["parameters"].pop("free_space_id")
        validation = validate_typed_scene_graph(graph)
        self.assertFalse(validation["ok"])
        self.assertTrue(
            any(
                "requires parameters.free_space_id" in error
                for error in validation["errors"]
            )
        )

    def test_tucked_under_grounding_requires_capability_name_and_becomes_hard(
        self,
    ) -> None:
        brief = build_baseline_brief("A study with a desk and office chair.")
        desk = next(obj for obj in brief["objects"] if obj["category"] == "desk")
        chair = next(
            obj for obj in brief["objects"] if obj["category"] == "office_chair"
        )
        report = apply_expansion_grounding(
            brief,
            {
                "relation_updates": [
                    {
                        "source": chair["id"],
                        "type": "tucked_under",
                        "target": desk["id"],
                        "strength": "soft",
                        "parameters": {"free_space_id": "under_desk"},
                        "source_evidence": "chair tucked under desk",
                    }
                ]
            },
        )
        self.assertEqual(report["accepted_count"], 1)
        relation = next(
            edge
            for edge in brief["relations"]
            if isinstance(edge, dict) and edge.get("type") == "tucked_under"
        )
        self.assertEqual(relation["strength"], "hard")
        self.assertEqual(
            relation["parameters"]["reference_frame"], "target_local"
        )

        rejected_brief = build_baseline_brief(
            "A study with a desk and office chair."
        )
        rejected_desk = next(
            obj for obj in rejected_brief["objects"] if obj["category"] == "desk"
        )
        rejected_chair = next(
            obj
            for obj in rejected_brief["objects"]
            if obj["category"] == "office_chair"
        )
        rejected = apply_expansion_grounding(
            rejected_brief,
            {
                "relation_updates": [
                    {
                        "source": rejected_chair["id"],
                        "type": "tucked_under",
                        "target": rejected_desk["id"],
                        "strength": "hard",
                        "parameters": {},
                    }
                ]
            },
        )
        self.assertEqual(rejected["accepted_count"], 0)
        self.assertEqual(rejected["rejected_count"], 1)
        self.assertIn(
            "requires parameters.free_space_id",
            rejected["rejected"][0]["reason"],
        )

    def test_explicit_user_viewpoint_can_override_locked_role_frame(self) -> None:
        prompt = (
            "A bedroom. Put the left bedside table on the left from the bed occupant's "
            "perspective."
        )
        brief = build_baseline_brief(prompt)
        apply_expansion_grounding(
            brief,
            {
                "relation_updates": [
                    {
                        "source": "nightstand_left",
                        "type": "left_of",
                        "target": "bed",
                        "strength": "hard",
                        "parameters": {"reference_frame": "target_local"},
                        "source_evidence": "from the bed occupant's perspective",
                    }
                ]
            },
        )
        relation = next(
            item
            for item in brief["relations"]
            if isinstance(item, dict)
            and item.get("source") == "nightstand_left"
            and item.get("type") == "left_of"
        )
        self.assertEqual(relation["parameters"]["reference_frame"], "target_local")
        self.assertEqual(
            relation["parameters"]["role_source"], "user_explicit_reference_frame"
        )
        self.assertEqual(
            brief["semantic_grounding"]["normalizations"][0]["kind"],
            "explicit_reference_frame_override_accepted",
        )

    def test_constraint_scopes_allow_overlap_without_mutating_hierarchy(self) -> None:
        evidence = "bedside tables on the left and right sides of the bed"
        prompt = f"A bedroom with {evidence}."
        brief = build_baseline_brief(prompt)
        original_supports = {
            obj["id"]: obj.get("support_id") for obj in brief["objects"]
        }
        report = apply_expansion_grounding(
            brief,
            {
                "constraint_scopes": [
                    {
                        "scope_id": "bed_setup",
                        "domain": "floor",
                        "scope_kind": "layout_group",
                        "root_id": "bed",
                        "members": [
                            {"object_id": "bed", "role": "anchor"},
                            {"object_id": "nightstand_left", "role": "left_member"},
                            {"object_id": "nightstand_right", "role": "right_member"},
                        ],
                        "relation_refs": [
                            {"source": "nightstand_left", "type": "left_of", "target": "bed"},
                            {"source": "nightstand_right", "type": "right_of", "target": "bed"},
                        ],
                        "source_evidence": evidence,
                    },
                    {
                        "scope_id": "left_bed_access",
                        "domain": "functional_clearance",
                        "scope_kind": "functional_group",
                        "root_id": "bed",
                        "members": [
                            {"object_id": "bed", "role": "anchor"},
                            {"object_id": "nightstand_left", "role": "adjacent_member"},
                        ],
                        "relation_refs": [
                            {"source": "nightstand_left", "type": "left_of", "target": "bed"}
                        ],
                        "source_evidence": evidence,
                    },
                ]
            },
        )
        self.assertEqual(report["constraint_scopes"]["accepted_count"], 2)
        self.assertEqual(
            brief["constraint_scope_grounding"]["overlapping_memberships"]["bed"],
            ["bed_setup", "left_bed_access"],
        )
        self.assertFalse(brief["constraint_scope_grounding"]["auto_merge_performed"])
        self.assertEqual(
            original_supports,
            {obj["id"]: obj.get("support_id") for obj in brief["objects"]},
        )

        envelopes = evaluate_constraint_scope_envelopes(brief)
        bed_setup = next(
            item for item in envelopes["results"] if item["scope_id"] == "bed_setup"
        )
        self.assertEqual(bed_setup["status"], "not_ruled_out")
        self.assertAlmostEqual(
            bed_setup["minimum_envelope"]["width"], 2.98, places=6
        )
        graph = build_typed_scene_graph(brief, plan_architecture(brief))
        self.assertTrue(graph["validation"]["ok"], graph["validation"])
        self.assertEqual(graph["stats"]["constraint_scope_count"], 2)

        brief["room"].update({"width": 2.5, "length": 2.5})
        constrained = evaluate_constraint_scope_envelopes(brief)
        constrained_bed_setup = next(
            item
            for item in constrained["results"]
            if item["scope_id"] == "bed_setup"
        )
        self.assertEqual(constrained_bed_setup["status"], "potentially_infeasible")
        self.assertTrue(constrained_bed_setup["advisory_only"])

    def test_constraint_scope_contract_rejects_unverifiable_proposals(self) -> None:
        evidence = "bedside tables on the left and right sides of the bed"
        brief = build_baseline_brief(f"A bedroom with {evidence}.")
        report = apply_expansion_grounding(
            brief,
            {
                "constraint_scopes": [
                    {
                        "scope_id": "unknown_member",
                        "domain": "floor",
                        "root_id": "bed",
                        "members": ["bed", "invented_table"],
                        "relation_refs": [
                            {"source": "nightstand_left", "type": "left_of", "target": "bed"}
                        ],
                        "source_evidence": evidence,
                    },
                    {
                        "scope_id": "invented_evidence",
                        "domain": "floor",
                        "root_id": "bed",
                        "members": ["bed", "nightstand_left"],
                        "relation_refs": [
                            {"source": "nightstand_left", "type": "left_of", "target": "bed"}
                        ],
                        "source_evidence": "a reading cluster not present in the prompt",
                    },
                    {
                        "scope_id": "missing_relation",
                        "domain": "floor",
                        "root_id": "bed",
                        "members": ["bed", "nightstand_left"],
                        "relation_refs": [
                            {"source": "nightstand_left", "type": "faces", "target": "bed"}
                        ],
                        "source_evidence": evidence,
                    },
                ]
            },
        )
        self.assertEqual(report["constraint_scopes"]["accepted_count"], 0)
        self.assertEqual(report["constraint_scopes"]["rejected_count"], 3)
        reasons = {
            item["reason"] for item in brief["constraint_scope_grounding"]["rejected"]
        }
        self.assertTrue(any("unknown member" in reason for reason in reasons))
        self.assertTrue(any("source_evidence" in reason for reason in reasons))
        self.assertTrue(any("not grounded" in reason for reason in reasons))

    def test_target_facing_is_reapplied_after_sdk_repair(self) -> None:
        prompt_path = (
            Path(__file__).parents[1]
            / "prompts"
            / "bedroom_typed_graph_component_strict.txt"
        )
        prompt = prompt_path.read_text(encoding="utf-8")
        brief = build_baseline_brief(prompt)
        apply_expansion_grounding(brief, self._expanded_delta())
        brief["scene_graph"] = build_typed_scene_graph(
            brief, plan_architecture(brief)
        )
        plan = rules_layout(brief)
        chair = next(
            obj for obj in plan["objects"] if obj["id"] == "explicit_office_chair"
        )
        chair["yaw"] = (float(chair["yaw"]) + 180.0) % 360.0
        before = evaluate_relation_facing(plan["objects"], plan["relations"])
        self.assertFalse(before[0]["ok"])

        repaired = deterministic_repair(plan)
        after = evaluate_relation_facing(repaired["objects"], repaired["relations"])
        self.assertTrue(after[0]["ok"], after)
        validation = validate_layout(repaired)
        self.assertEqual(
            validation["metrics"]["functional_facing"]["target_facing_count"], 1
        )
        self.assertNotIn(
            "functional_facing_direction",
            {item["type"] for item in validation["violations"]},
        )

    def test_invalid_grounding_ids_and_support_cycles_are_rejected(self) -> None:
        brief = build_baseline_brief("A bedroom.")
        report = apply_expansion_grounding(
            brief,
            {
                "relation_updates": [
                    {
                        "source": "missing_cup",
                        "type": "supported_by",
                        "target": "bed",
                    },
                    {
                        "source": "nightstand_left",
                        "type": "supported_by",
                        "target": "lamp_left",
                    },
                ],
                "attribute_updates": [],
                "component_updates": [],
            },
        )
        self.assertEqual(report["accepted_count"], 0)
        self.assertEqual(report["rejected_count"], 2)
        self.assertIsNone(
            next(obj for obj in brief["objects"] if obj["id"] == "nightstand_left")[
                "support_id"
            ]
        )

    def test_missing_asset_prompts_are_isolated_and_group_duplicate_instances(self) -> None:
        prompt_path = (
            Path(__file__).parents[1] / "prompts" / "bedroom_rgbd_front_strict.txt"
        )
        source_prompt = prompt_path.read_text(encoding="utf-8")
        brief = build_baseline_brief(source_prompt)
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
            generation_plan = json.loads(
                Path(report["missing_asset_generation_plan"]).read_text(encoding="utf-8")
            )
        self.assertEqual(generation_plan["source_scene_prompt"], source_prompt)
        self.assertEqual(
            generation_plan["missing_instance_count"], len(brief["objects"])
        )
        entries = generation_plan["generation_entries"]
        self.assertTrue(all(entry["prompt_metrics"]["words"] <= 90 for entry in entries))
        self.assertTrue(
            all("scene context:" not in entry["bridge_input_prompt"].lower() for entry in entries)
        )
        for category in ("book_stack", "storage_box"):
            category_entries = [entry for entry in entries if entry["category"] == category]
            self.assertTrue(category_entries)
            for entry in category_entries:
                lowered = entry["bridge_input_prompt"].lower()
                self.assertNotIn("bedside table", lowered)
                self.assertNotIn("camera requirements", lowered)
                self.assertFalse(
                    entry["asset_generation_spec"]["source_requirements"][
                        "full_scene_prompt_forwarded"
                    ]
                )
        self.assertFalse(any(entry["category"] == "pillow" for entry in entries))
        bed_entry = next(entry for entry in entries if entry["category"] == "bed")
        self.assertEqual(
            bed_entry["asset_generation_spec"]["integrated_component_requirements"][0][
                "requested_count"
            ],
            2,
        )
        self.assertIn("2 integrated pillows", bed_entry["bridge_input_prompt"].lower())
        self.assertEqual(
            report["component_resolution"][0]["resolution_status"],
            "requested_in_composite_asset_prompt",
        )
        storage_entries = [entry for entry in entries if entry["category"] == "storage_box"]
        self.assertEqual(
            [entry["strategy"] for entry in storage_entries],
            ["generate_unique_asset", "reuse_generated_asset"],
        )

    def test_final_bridge_prompt_keeps_object_first_and_within_t5_budget(self) -> None:
        brief = build_baseline_brief(
            "A clean modern bedroom with exactly two storage boxes and minimal occlusion."
        )
        box = next(obj for obj in brief["objects"] if obj["category"] == "storage_box")
        with tempfile.TemporaryDirectory() as tmp:
            report = resolve_assets(
                {**brief, "objects": [box]},
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
                max_new_assets=1,
            )
            entry = json.loads(
                Path(report["missing_asset_generation_plan"]).read_text(encoding="utf-8")
            )["generation_entries"][0]
        runtime = Trellis2BridgeRuntime(Namespace(flux_background_mode="contrast"))
        final_prompt = runtime._compose_flux_prompt(entry["bridge_input_prompt"])
        self.assertTrue(final_prompt.startswith("Exactly one isolated object:"))
        self.assertLessEqual(len(final_prompt.split()), 150)
        self.assertNotIn("built-in lamp base", final_prompt.lower())
        self.assertNotIn("scene context:", final_prompt.lower())
        self.assertNotIn("minimal design", final_prompt.lower())

    def test_trellis_generates_one_asset_for_equivalent_instances(self) -> None:
        brief = build_baseline_brief(
            "A modern bedroom with exactly two storage boxes and no decorative clutter."
        )
        brief["objects"] = [
            obj for obj in brief["objects"] if obj["category"] == "storage_box"
        ]
        brief["asset_inventory"] = [
            {
                "category": "storage_box",
                "requested_count": 2,
                "required_count": 2,
                "instance_ids": [obj["id"] for obj in brief["objects"]],
            }
        ]

        def fake_generate(obj, output_path, **kwargs):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"glTF generated once")
            return {
                "job_id": "fake-job",
                "request": {"input_text": obj["asset_prompt"]},
                "bridge_metadata": {
                    "selected_reference_job_id": "ref-1",
                    "reference_attempts": [
                        {"reference_job_id": "ref-1", "prompt": "final isolated Flux prompt"}
                    ],
                },
            }

        with tempfile.TemporaryDirectory() as tmp, patch(
            "sage.experiments.codex_trellis_scene_v2.assets.bridge_health",
            return_value={"ok": True},
        ), patch(
            "sage.experiments.codex_trellis_scene_v2.assets.generate_trellis_asset",
            side_effect=fake_generate,
        ) as generate:
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
            self.assertEqual(generate.call_count, 1)
            self.assertEqual(report["generated_count"], 2)
            self.assertEqual(report["unique_generated_count"], 1)
            self.assertTrue(report["ready_for_assembly"])
            self.assertEqual(
                {item["generation_strategy"] for item in report["results"]},
                {"generate_unique_asset", "reuse_generated_asset"},
            )
            self.assertEqual(
                {item["final_flux_prompt"] for item in report["results"]},
                {"final isolated Flux prompt"},
            )

    def test_restroom_detection_has_complete_functional_core(self) -> None:
        brief = build_baseline_brief("一个紧凑的现代卫生间。")
        self.assertEqual(brief["room_type"], "restroom")
        ids = {obj["id"] for obj in brief["objects"]}
        self.assertTrue({"toilet", "vanity_sink", "shower", "vanity_mirror"} <= ids)

    def test_architecture_is_separate_from_furniture_budget(self) -> None:
        brief = build_baseline_brief("A bedroom.")
        architecture = brief["architecture"]
        self.assertEqual(len(architecture["doors"]), 1)
        self.assertEqual(len(architecture["windows"]), 1)
        self.assertEqual(
            architecture["floor"]["material"]["texture_type"],
            "procedural_wood_plank",
        )
        self.assertEqual(
            architecture["wall_finish"]["default"]["material_id"],
            "warm_white_plaster",
        )
        self.assertNotIn("entry_door", {obj["id"] for obj in brief["objects"]})
        self.assertEqual(len(brief["objects"]), 10)


class ArchitecturePlanningTest(unittest.TestCase):
    def test_default_room_policies_keep_entry_and_window_on_different_walls(self) -> None:
        for room_type in ("bedroom", "living_room", "kitchen", "study", "restroom"):
            with self.subTest(room_type=room_type):
                brief = build_baseline_brief("A room.", room_type)
                report = plan_architecture(brief)
                door_walls = {item["wall"] for item in report["architecture"]["doors"]}
                window_walls = {item["wall"] for item in report["architecture"]["windows"]}
                self.assertFalse(door_walls & window_walls)
                self.assertEqual(report["stage_order"][1], "architecture_planning")

    def test_bedroom_prefers_main_window_opposite_entry_door(self) -> None:
        brief = build_baseline_brief("A bedroom.")
        report = plan_architecture(brief)
        self.assertEqual(report["architecture"]["doors"][0]["wall"], "east")
        self.assertEqual(report["architecture"]["windows"][0]["wall"], "west")
        validation = validate_layout(rules_layout(brief))
        architecture = validation["metrics"]["architecture"]
        self.assertTrue(architecture["door_window_opposite_wall_preferred"])
        self.assertTrue(architecture["door_window_opposite_wall"])

    def test_explicit_nonopposite_bedroom_window_is_recorded_as_override(self) -> None:
        brief = build_baseline_brief("A bedroom.")
        plan_architecture(brief, window_wall_override="south")
        report = validate_layout(rules_layout(brief))
        architecture = report["metrics"]["architecture"]
        self.assertFalse(architecture["door_window_opposite_wall"])
        self.assertTrue(architecture["door_window_opposite_wall_overridden"])
        self.assertNotIn(
            "door_window_not_opposite",
            {item["type"] for item in report["violations"]},
        )

    def test_unrecorded_nonopposite_bedroom_window_is_a_soft_violation(self) -> None:
        brief = build_baseline_brief("A bedroom.")
        brief["architecture"]["windows"][0]["wall"] = "south"
        plan = rules_layout(brief)
        report = validate_layout(plan)
        self.assertIn(
            "door_window_not_opposite",
            {item["type"] for item in report["violations"]},
        )

    def test_prompt_selects_floor_material_before_object_layout(self) -> None:
        brief = build_baseline_brief("A warm bedroom with a terrazzo floor.")
        report = plan_architecture(brief)
        material = report["architecture"]["floor"]["material"]
        self.assertEqual(material["material_id"], "terrazzo_tile")
        self.assertEqual(material["texture_type"], "procedural_terrazzo")
        self.assertTrue(material["embed_generated_texture"])

    def test_explicit_same_wall_choice_is_recorded_as_soft_override(self) -> None:
        brief = build_baseline_brief("A bedroom.")
        plan_architecture(brief, window_wall_override="east")
        plan = rules_layout(brief)
        report = validate_layout(plan)
        architecture = report["metrics"]["architecture"]
        self.assertTrue(architecture["door_window_same_wall"])
        self.assertTrue(architecture["door_window_same_wall_overridden"])
        self.assertNotIn(
            "door_window_same_wall",
            {item["type"] for item in report["violations"]},
        )

    def test_prompt_selects_global_wall_material_before_object_layout(self) -> None:
        brief = build_baseline_brief("A bedroom with light gray walls.")
        report = plan_architecture(brief)
        wall_finish = report["architecture"]["wall_finish"]
        self.assertEqual(
            wall_finish["default"]["material_id"],
            "light_gray_matte_paint",
        )
        self.assertEqual(wall_finish["overrides"], {})
        self.assertTrue(wall_finish["default"]["embed_generated_texture"])

    def test_single_accent_wall_override_is_frozen_in_architecture(self) -> None:
        brief = build_baseline_brief("A warm bedroom.")
        report = plan_architecture(
            brief,
            wall_material_override="warm_white_plaster",
            accent_wall_override="north",
            accent_wall_material_override="muted_sage_matte_paint",
        )
        wall_finish = report["architecture"]["wall_finish"]
        self.assertEqual(
            wall_finish["default"]["material_id"],
            "warm_white_plaster",
        )
        self.assertEqual(
            wall_finish["overrides"]["north"]["material_id"],
            "muted_sage_matte_paint",
        )
        plan = rules_layout(brief)
        validation = validate_layout(plan)
        self.assertTrue(validation["ok"], validation)
        self.assertEqual(
            validation["metrics"]["architecture"]["wall_material_overrides"],
            {"north": "muted_sage_matte_paint"},
        )

    def test_accent_wall_options_must_be_paired(self) -> None:
        brief = build_baseline_brief("A bedroom.")
        with self.assertRaisesRegex(ValueError, "must be provided together"):
            plan_architecture(brief, accent_wall_override="north")

    def test_all_floor_presets_have_embeddable_texture_types(self) -> None:
        expected = {
            "warm_oak_plank",
            "light_oak_plank",
            "walnut_plank",
            "gray_wash_plank",
            "beige_ceramic_tile",
            "gray_stone_tile",
            "terrazzo_tile",
            "polished_concrete",
        }
        self.assertEqual(set(FLOOR_MATERIAL_PRESETS), expected)
        self.assertTrue(
            all(str(item["texture_type"]).startswith("procedural_") for item in FLOOR_MATERIAL_PRESETS.values())
        )

    def test_all_wall_presets_have_embeddable_texture_types(self) -> None:
        expected = {
            "warm_white_plaster",
            "cool_white_plaster",
            "soft_beige_limewash",
            "light_gray_matte_paint",
            "muted_sage_matte_paint",
            "blue_gray_matte_paint",
        }
        self.assertEqual(set(WALL_MATERIAL_PRESETS), expected)
        self.assertTrue(
            all(
                str(item["texture_type"]).startswith("procedural_")
                for item in WALL_MATERIAL_PRESETS.values()
            )
        )


class FunctionalOrientationTest(unittest.TestCase):
    def test_canonical_front_solver_targets_each_wall_inward_normal(self) -> None:
        expected = {"north": 0.0, "south": 180.0, "east": 270.0, "west": 90.0}
        for wall, yaw in expected.items():
            with self.subTest(wall=wall):
                obj = {
                    "id": "storage",
                    "preferred_wall": wall,
                    "yaw": 0.0,
                    "asset_canonical_front": {"axis": "-y", "confidence": 0.9},
                    "facing_constraint": {
                        "mode": "into_room",
                        "wall": wall,
                        "contact_face": "back",
                    },
                }
                self.assertEqual(solve_facing_yaw(obj), yaw)

    def test_external_orientation_metadata_and_local_offset_are_supported(self) -> None:
        obj = {
            "id": "external_storage",
            "preferred_wall": "east",
            "yaw": 0.0,
            "asset_orientation": {
                "canonical_front_axis": "+x",
                "confidence": 0.85,
            },
            "asset_local_yaw_offset_degrees": 90.0,
            "facing_constraint": {
                "mode": "into_room",
                "wall": "east",
                "contact_face": "back",
            },
        }
        self.assertEqual(solve_facing_yaw(obj), 90.0)

    def test_rules_layout_points_east_wardrobe_and_south_dresser_into_room(self) -> None:
        brief = build_baseline_brief("A bedroom.")
        for obj in brief["objects"]:
            if obj["id"] in {"wardrobe", "dresser"}:
                obj["asset_canonical_front"] = {"axis": "-y", "confidence": 0.9}
        plan = rules_layout(brief)
        by_id = {obj["id"]: obj for obj in plan["objects"]}
        self.assertEqual(by_id["wardrobe"]["yaw"], 270.0)
        self.assertEqual(by_id["dresser"]["yaw"], 180.0)
        self.assertTrue(evaluate_facing(by_id["wardrobe"])["ok"])
        self.assertTrue(evaluate_facing(by_id["dresser"])["ok"])

    def test_validator_rejects_high_confidence_front_facing_wall(self) -> None:
        brief = build_baseline_brief("A bedroom.")
        wardrobe = next(obj for obj in brief["objects"] if obj["id"] == "wardrobe")
        wardrobe["asset_canonical_front"] = {"axis": "-y", "confidence": 0.9}
        plan = rules_layout(brief)
        wardrobe = next(obj for obj in plan["objects"] if obj["id"] == "wardrobe")
        wardrobe["yaw"] = 90.0
        report = validate_layout(plan)
        violations = [
            item for item in report["violations"]
            if item["type"] == "functional_facing_direction"
        ]
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0]["severity"], "hard")
        self.assertEqual(violations[0]["angle_error_degrees"], 180.0)

    def test_repair_restores_functional_front_before_wall_snap(self) -> None:
        brief = build_baseline_brief("A bedroom.")
        wardrobe = next(obj for obj in brief["objects"] if obj["id"] == "wardrobe")
        wardrobe["asset_canonical_front"] = {"axis": "-y", "confidence": 0.9}
        plan = rules_layout(brief)
        wardrobe = next(obj for obj in plan["objects"] if obj["id"] == "wardrobe")
        wardrobe["yaw"] = 90.0
        repaired = deterministic_repair(plan)
        fixed = next(obj for obj in repaired["objects"] if obj["id"] == "wardrobe")
        self.assertEqual(fixed["yaw"], 270.0)
        self.assertTrue(evaluate_facing(fixed)["ok"])
        self.assertTrue(validate_layout(repaired)["ok"])


class SpatialRelationConstraintTest(unittest.TestCase):
    @staticmethod
    def _plan(
        objects: list[dict], relations: list[dict]
    ) -> dict:
        plan = rules_layout(build_baseline_brief("A bedroom."))
        plan["objects"] = deepcopy(objects)
        plan["relations"] = deepcopy(relations)
        plan["object_budget"] = {
            "hard_min": len(objects),
            "target_max": len(objects),
            "max_auto_inferred_objects": 0,
            "hard_runtime_limit": 40,
            "required_object_ids": [obj["id"] for obj in objects],
            "floor_occupancy_min": 0.0,
            "floor_occupancy_max": 1.0,
        }
        plan.pop("scene_graph", None)
        return plan

    def test_target_local_front_rotates_with_target(self) -> None:
        desk = {
            "id": "desk",
            "dimensions": {"width": 1.4, "length": 0.72, "height": 0.75},
            "x": 4.0,
            "y": 2.5,
            "z": 0.0,
            "yaw": 270.0,
            "asset_canonical_front": {"axis": "-y", "confidence": 0.9},
        }
        chair = {
            "id": "chair",
            "dimensions": {"width": 0.62, "length": 0.62, "height": 1.0},
            "x": 3.0,
            "y": 2.5,
            "z": 0.0,
            "yaw": 90.0,
        }
        relation = {
            "source": "chair",
            "type": "in_front_of",
            "target": "desk",
            "strength": "hard",
            "parameters": {
                "reference_frame": "target_local",
                "min_gap": 0.2,
                "max_gap": 0.8,
            },
        }
        status = evaluate_spatial_relations([desk, chair], [relation])[0]
        self.assertTrue(status["ok"], status)
        chair["x"], chair["y"] = 4.0, 1.3
        status = evaluate_spatial_relations([desk, chair], [relation])[0]
        self.assertFalse(status["ok"], status)

    def test_left_right_ordering_does_not_imply_center_alignment(self) -> None:
        bed = {
            "id": "bed",
            "dimensions": {"width": 1.8, "length": 2.1, "height": 1.05},
            "x": 2.6,
            "y": 3.27,
            "z": 0.0,
            "yaw": 0.0,
        }
        nightstand = {
            "id": "nightstand",
            "dimensions": {"width": 0.55, "length": 0.45, "height": 0.62},
            "x": 1.25,
            "y": 4.095,
            "z": 0.0,
            "yaw": 0.0,
        }
        relation = {
            "source": "nightstand",
            "type": "left_of",
            "target": "bed",
            "strength": "hard",
            "parameters": {
                "reference_frame": "room",
                "lateral_tolerance": 0.2,
            },
        }
        status = evaluate_spatial_relations([bed, nightstand], [relation])[0]
        self.assertTrue(status["ok"], status)
        self.assertIsNone(status["lateral_tolerance"])

        relation["parameters"]["alignment_mode"] = "center"
        status = evaluate_spatial_relations([bed, nightstand], [relation])[0]
        self.assertFalse(status["ok"], status)

    def test_locked_side_role_reports_a_swapped_neutral_entity_id(self) -> None:
        bed = {
            "id": "bed",
            "category": "bed",
            "placement_type": "floor",
            "dimensions": {"width": 1.8, "length": 2.1, "height": 1.05},
            "x": 2.6,
            "y": 2.2,
            "z": 0.0,
            "yaw": 0.0,
        }
        table = {
            "id": "table_a",
            "category": "nightstand",
            "placement_type": "floor",
            "dimensions": {"width": 0.55, "length": 0.45, "height": 0.62},
            "x": 3.9,
            "y": 2.2,
            "z": 0.0,
            "yaw": 0.0,
        }
        relation = {
            "source": "table_a",
            "type": "left_of",
            "target": "bed",
            "strength": "soft",
            "parameters": {
                "reference_frame": "target_local",
                "side_role": "left",
                "role_locked": True,
                "role_reference_frame": "room",
                "role_source": "test_policy",
            },
        }
        status = evaluate_spatial_relations([bed, table], [relation])[0]
        self.assertFalse(status["role_assignment_ok"], status)
        self.assertEqual(status["strength"], "hard")

        report = validate_layout(self._plan([bed, table], [relation]))
        role_violations = [
            item
            for item in report["violations"]
            if item["type"] == "side_role_assignment"
        ]
        self.assertEqual(len(role_violations), 1, report)
        self.assertEqual(role_violations[0]["source"], "table_a")
        self.assertEqual(
            report["metrics"]["spatial_relations"]["side_role_assignment"][
                "invalid_count"
            ],
            1,
        )

    def test_scope_failure_aggregation_groups_connected_relations_only(self) -> None:
        bed = {
            "id": "bed",
            "category": "bed",
            "placement_type": "floor",
            "dimensions": {"width": 1.8, "length": 2.1, "height": 1.05},
            "x": 2.6,
            "y": 3.27,
            "z": 0.0,
            "yaw": 0.0,
        }
        slippers = [
            {
                "id": f"slipper_{index}",
                "category": "slipper",
                "placement_type": "floor",
                "dimensions": {"width": 0.28, "length": 0.12, "height": 0.08},
                "x": x,
                "y": 1.14,
                "z": 0.0,
                "yaw": 0.0,
            }
            for index, x in ((1, 2.22), (2, 2.72))
        ]
        relations = [
            {
                "source": slipper["id"],
                "type": "in_front_of",
                "target": "bed",
                "strength": "hard",
                "parameters": {
                    "reference_frame": "target_local",
                    "min_gap": 0.05,
                    "max_gap": 0.9,
                },
            }
            for slipper in slippers
        ]
        plan = self._plan([bed, *slippers], relations)
        plan["constraint_scopes"] = [
            {
                "scope_id": "slipper_pair_at_bed_foot",
                "domain": "floor",
                "scope_kind": "layout_group",
                "root_id": "bed",
                "members": [
                    {"object_id": "bed", "role": "anchor"},
                    {"object_id": "slipper_1", "role": "left_member"},
                    {"object_id": "slipper_2", "role": "right_member"},
                ],
                "relation_refs": [
                    {
                        "id": f"relation:{slipper['id']}:in_front_of:bed",
                        "source": slipper["id"],
                        "type": "in_front_of",
                        "target": "bed",
                    }
                    for slipper in slippers[:1]
                ],
            }
        ]
        report = validate_layout(plan)
        aggregation = report["metrics"]["constraint_scope_failures"]
        self.assertEqual(
            report["metrics"]["spatial_relations"]["hard_invalid_count"], 2
        )
        self.assertEqual(aggregation["raw_relation_failure_count"], 2)
        self.assertEqual(aggregation["scope_failure_count"], 1)
        self.assertEqual(aggregation["membership_inferred_relation_count"], 1)
        self.assertEqual(aggregation["hard_scope_failure_count"], 1)
        self.assertEqual(aggregation["grouped_relation_failure_count"], 1)
        self.assertEqual(len(report["constraint_scope_failures"]), 1)
        self.assertEqual(
            report["constraint_scope_failures"][0]["failed_relation_count"], 2
        )
        self.assertEqual(report["constraint_scope_failures"][0]["severity"], "hard")
        self.assertEqual(
            report["constraint_scope_failures"][0][
                "membership_inferred_relation_ids"
            ],
            ["relation:slipper_2:in_front_of:bed"],
        )
        self.assertFalse(aggregation["changes_validation_ok"])

        objects = [
            {
                "id": object_id,
                "category": "side_table",
                "placement_type": "floor",
                "dimensions": {"width": 0.2, "length": 0.2, "height": 0.4},
                "x": x,
                "y": y,
                "z": 0.0,
                "yaw": 0.0,
            }
            for object_id, x, y in (
                ("anchor_a", 1.0, 1.0),
                ("member_a", 2.0, 1.0),
                ("anchor_b", 1.0, 3.0),
                ("member_b", 2.0, 3.0),
            )
        ]
        disconnected_relations = [
            {
                "source": member,
                "type": "left_of",
                "target": anchor,
                "strength": "hard",
                "parameters": {"reference_frame": "room"},
            }
            for member, anchor in (("member_a", "anchor_a"), ("member_b", "anchor_b"))
        ]
        disconnected_plan = self._plan(objects, disconnected_relations)
        disconnected_plan["constraint_scopes"] = [
            {
                "scope_id": "two_independent_pairs",
                "domain": "floor",
                "scope_kind": "layout_group",
                "root_id": "anchor_a",
                "members": [
                    {"object_id": obj["id"], "role": "member"} for obj in objects
                ],
                "relation_refs": [
                    {
                        "id": f"relation:{member}:left_of:{anchor}",
                        "source": member,
                        "type": "left_of",
                        "target": anchor,
                    }
                    for member, anchor in (("member_a", "anchor_a"), ("member_b", "anchor_b"))
                ],
            }
        ]
        disconnected = validate_layout(disconnected_plan)["metrics"][
            "constraint_scope_failures"
        ]
        self.assertEqual(disconnected["raw_relation_failure_count"], 2)
        self.assertEqual(disconnected["scope_failure_count"], 2)

    def test_back_face_alignment_and_pair_symmetry_use_semantic_anchors(self) -> None:
        bed = {
            "id": "bed",
            "dimensions": {"width": 1.8, "length": 2.1, "height": 1.05},
            "x": 2.6,
            "y": 3.27,
            "z": 0.0,
            "yaw": 0.0,
        }
        left = {
            "id": "left",
            "dimensions": {"width": 0.55, "length": 0.45, "height": 0.62},
            "x": 1.25,
            "y": 4.095,
            "z": 0.0,
            "yaw": 0.0,
        }
        right = {**deepcopy(left), "id": "right", "x": 3.95}
        relations = [
            {
                "source": "left",
                "type": "aligned_with",
                "target": "bed",
                "strength": "hard",
                "parameters": {
                    "reference_frame": "target_local",
                    "source_anchor": "back_face",
                    "target_anchor": "back_face",
                    "axis": "depth",
                    "alignment_tolerance": 0.02,
                },
            },
            {
                "source": "right",
                "type": "aligned_with",
                "target": "bed",
                "strength": "hard",
                "parameters": {
                    "reference_frame": "target_local",
                    "source_anchor": "back_face",
                    "target_anchor": "back_face",
                    "axis": "depth",
                    "alignment_tolerance": 0.02,
                },
            },
            {
                "source": "left",
                "type": "mirror_symmetric",
                "target": "right",
                "strength": "hard",
                "parameters": {
                    "reference_id": "bed",
                    "axis": "left_right",
                    "alignment_tolerance": 0.02,
                },
            },
        ]
        statuses = evaluate_spatial_relations([bed, left, right], relations)
        self.assertTrue(all(status["ok"] for status in statuses), statuses)

        left["y"] = 3.27
        statuses = evaluate_spatial_relations([bed, left, right], relations)
        self.assertEqual(sum(not status["ok"] for status in statuses), 2)

    def test_grid_csp_repairs_wall_aligned_symmetric_pair(self) -> None:
        bed = {
            "id": "bed",
            "category": "bed",
            "placement_type": "floor",
            "preferred_wall": "north",
            "wall_constraint_strength": "hard",
            "priority": 100,
            "dimensions": {"width": 1.8, "length": 2.1, "height": 1.05},
            "x": 2.6,
            "y": 3.27,
            "z": 0.0,
            "yaw": 0.0,
        }
        left = {
            "id": "left",
            "category": "nightstand",
            "placement_type": "floor",
            "preferred_wall": "north",
            "wall_constraint_strength": "soft",
            "priority": 80,
            "dimensions": {"width": 0.55, "length": 0.45, "height": 0.62},
            "x": 1.25,
            "y": 3.27,
            "z": 0.0,
            "yaw": 0.0,
        }
        right = {**deepcopy(left), "id": "right", "x": 3.95}
        relations = [
            {
                "source": side,
                "type": "aligned_with",
                "target": "bed",
                "strength": "hard",
                "parameters": {
                    "source_anchor": "back_face",
                    "target_anchor": "back_face",
                    "axis": "depth",
                    "alignment_tolerance": 0.02,
                },
            }
            for side in ("left", "right")
        ]
        relations.append(
            {
                "source": "left",
                "type": "mirror_symmetric",
                "target": "right",
                "strength": "hard",
                "parameters": {
                    "reference_id": "bed",
                    "axis": "left_right",
                    "alignment_tolerance": 0.02,
                },
            }
        )
        repaired = deterministic_repair(self._plan([bed, left, right], relations))
        report = validate_layout(repaired)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["metrics"]["spatial_relations"]["invalid_count"], 0)
        by_id = {obj["id"]: obj for obj in repaired["objects"]}
        self.assertAlmostEqual(by_id["left"]["y"], 4.095, places=3)
        self.assertAlmostEqual(by_id["right"]["y"], 4.095, places=3)

    def test_preferred_wall_can_be_soft_or_hard(self) -> None:
        obj = {
            "id": "cabinet",
            "category": "cabinet",
            "placement_type": "floor",
            "preferred_wall": "north",
            "wall_constraint_strength": "soft",
            "priority": 50,
            "dimensions": {"width": 0.8, "length": 0.5, "height": 1.0},
            "x": 1.0,
            "y": 2.0,
            "z": 0.0,
            "yaw": 0.0,
        }
        plan = self._plan([obj], [])
        wall_violation = next(
            item for item in validate_layout(plan)["violations"]
            if item["type"] == "wall_affinity"
        )
        self.assertEqual(wall_violation["severity"], "soft")
        plan["objects"][0]["wall_constraint_strength"] = "hard"
        wall_violation = next(
            item for item in validate_layout(plan)["violations"]
            if item["type"] == "wall_affinity"
        )
        self.assertEqual(wall_violation["severity"], "hard")

    def test_grid_csp_repairs_desk_chair_front_and_clearance(self) -> None:
        desk = {
            "id": "desk",
            "category": "desk",
            "placement_type": "floor",
            "preferred_wall": "east",
            "priority": 80,
            "dimensions": {"width": 1.4, "length": 0.72, "height": 0.75},
            "x": 4.76,
            "y": 3.0,
            "z": 0.0,
            "yaw": 270.0,
            "asset_canonical_front": {"axis": "-y", "confidence": 0.9},
            "facing_constraint": {
                "mode": "into_room",
                "wall": "east",
                "contact_face": "back",
                "tolerance_degrees": 15.0,
            },
        }
        chair = {
            "id": "chair",
            "category": "office_chair",
            "placement_type": "floor",
            "preferred_wall": None,
            "priority": 60,
            "dimensions": {"width": 0.62, "length": 0.62, "height": 1.05},
            "x": 1.2,
            "y": 3.0,
            "z": 0.0,
            "yaw": 90.0,
            "asset_canonical_front": {"axis": "-y", "confidence": 0.9},
        }
        relations = [
            {
                "source": "chair",
                "type": "in_front_of",
                "target": "desk",
                "strength": "hard",
                "parameters": {"reference_frame": "target_local", "min_gap": 0.12},
            },
            {
                "source": "chair",
                "type": "clearance_from",
                "target": "desk",
                "strength": "hard",
                "parameters": {"min_gap": 0.2, "max_gap": 0.8},
            },
        ]
        plan = self._plan([desk, chair], relations)
        before = validate_layout(plan)
        self.assertGreater(
            before["metrics"]["spatial_relations"]["hard_invalid_count"], 0
        )

        repaired = deterministic_repair(plan)
        report = validate_layout(repaired)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["metrics"]["spatial_relations"]["invalid_count"], 0)
        search = repaired["repair_history"][-1]["spatial_relation_search"]
        self.assertGreater(search["change_count"], 0)
        self.assertEqual(search["unresolved_count"], 0)

    def test_grid_csp_repairs_room_left_and_pair_separation(self) -> None:
        boxes = [
            {
                "id": "box_left",
                "category": "storage_box",
                "placement_type": "floor",
                "priority": 40,
                "dimensions": {"width": 0.46, "length": 0.34, "height": 0.28},
                "x": 3.2,
                "y": 2.5,
                "z": 0.0,
                "yaw": 0.0,
            },
            {
                "id": "box_right",
                "category": "storage_box",
                "placement_type": "floor",
                "priority": 40,
                "dimensions": {"width": 0.46, "length": 0.34, "height": 0.28},
                "x": 2.2,
                "y": 2.5,
                "z": 0.0,
                "yaw": 0.0,
            },
        ]
        relations = [
            {
                "source": "box_left",
                "type": "left_of",
                "target": "box_right",
                "strength": "hard",
                "parameters": {
                    "reference_frame": "room",
                    "min_gap": 0.05,
                    "lateral_tolerance": 0.12,
                },
            },
            {
                "source": "box_left",
                "type": "separated_from",
                "target": "box_right",
                "strength": "hard",
                "parameters": {"min_gap": 0.08},
            },
        ]
        repaired = deterministic_repair(self._plan(boxes, relations))
        report = validate_layout(repaired)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["metrics"]["spatial_relations"]["invalid_count"], 0)
        by_id = {obj["id"]: obj for obj in repaired["objects"]}
        self.assertLess(by_id["box_left"]["x"], by_id["box_right"]["x"])

    def test_unsatisfiable_wall_locked_relation_is_reported(self) -> None:
        objects = [
            {
                "id": "wall_locked",
                "category": "cabinet",
                "placement_type": "floor",
                "preferred_wall": "east",
                "priority": 50,
                "dimensions": {"width": 0.8, "length": 0.6, "height": 1.0},
                "x": 4.82,
                "y": 3.0,
                "z": 0.0,
                "yaw": 0.0,
            },
            {
                "id": "west_anchor",
                "category": "cabinet",
                "placement_type": "floor",
                "preferred_wall": "west",
                "priority": 80,
                "dimensions": {"width": 0.8, "length": 0.6, "height": 1.0},
                "x": 0.48,
                "y": 3.0,
                "z": 0.0,
                "yaw": 0.0,
            },
        ]
        relations = [
            {
                "source": "wall_locked",
                "type": "left_of",
                "target": "west_anchor",
                "strength": "hard",
                "parameters": {"reference_frame": "room", "min_gap": 0.1},
            }
        ]
        repaired = deterministic_repair(self._plan(objects, relations))
        report = validate_layout(repaired)
        self.assertFalse(report["ok"])
        self.assertEqual(report["metrics"]["spatial_relations"]["hard_invalid_count"], 1)
        search = repaired["repair_history"][-1]["spatial_relation_search"]
        self.assertEqual(search["unresolved_count"], 1)
        self.assertEqual(search["unresolved"][0]["type"], "left_of")

    def test_soft_relation_is_optimized_without_becoming_hard(self) -> None:
        objects = [
            {
                "id": "movable",
                "category": "storage_box",
                "placement_type": "floor",
                "priority": 40,
                "dimensions": {"width": 0.4, "length": 0.4, "height": 0.3},
                "x": 3.0,
                "y": 2.5,
                "z": 0.0,
                "yaw": 0.0,
            },
            {
                "id": "anchor",
                "category": "storage_box",
                "placement_type": "floor",
                "priority": 80,
                "dimensions": {"width": 0.4, "length": 0.4, "height": 0.3},
                "x": 2.0,
                "y": 2.5,
                "z": 0.0,
                "yaw": 0.0,
            },
        ]
        relation = {
            "source": "movable",
            "type": "left_of",
            "target": "anchor",
            "strength": "soft",
            "parameters": {"reference_frame": "room", "min_gap": 0.05},
        }
        plan = self._plan(objects, [relation])
        before = validate_layout(plan)
        self.assertTrue(before["ok"], before)
        self.assertEqual(before["metrics"]["spatial_relations"]["hard_invalid_count"], 0)
        self.assertEqual(before["metrics"]["spatial_relations"]["soft_invalid_count"], 1)
        violation = next(
            item
            for item in before["violations"]
            if item["type"] == "spatial_relation_constraint"
        )
        self.assertEqual(violation["relation_type"], "left_of")
        self.assertEqual(violation["severity"], "soft")

        repaired = deterministic_repair(plan)
        after = validate_layout(repaired)
        self.assertTrue(after["ok"], after)
        self.assertEqual(after["metrics"]["spatial_relations"]["invalid_count"], 0)


class LayoutSdkTest(unittest.TestCase):
    def test_rules_layout_is_valid_for_all_supported_rooms(self) -> None:
        prompts = {
            "bedroom": "A bedroom.",
            "living_room": "A living room.",
            "kitchen": "A kitchen.",
            "study": "A study.",
            "restroom": "A restroom.",
        }
        for room_type, prompt in prompts.items():
            with self.subTest(room_type=room_type):
                plan = rules_layout(build_baseline_brief(prompt, room_type))
                repaired = deterministic_repair(plan)
                report = validate_layout(repaired)
                self.assertTrue(report["ok"], report)

    def test_collision_report_and_deterministic_repair(self) -> None:
        plan = rules_layout(build_baseline_brief("A bedroom."))
        by_id = {obj["id"]: obj for obj in plan["objects"]}
        by_id["wardrobe"]["x"] = by_id["bed"]["x"]
        by_id["wardrobe"]["y"] = by_id["bed"]["y"]
        broken = validate_layout(plan)
        self.assertFalse(broken["ok"])
        self.assertIn("floor_collision", {item["type"] for item in broken["violations"]})
        repaired = deterministic_repair(plan)
        self.assertTrue(validate_layout(repaired)["ok"])

    def test_support_children_are_snapped_to_support_height(self) -> None:
        plan = rules_layout(build_baseline_brief("A bedroom."))
        lamp = next(obj for obj in plan["objects"] if obj["id"] == "lamp_left")
        lamp["x"] = 0.0
        lamp["y"] = 0.0
        lamp["z"] = 0.0
        repaired = deterministic_repair(plan)
        by_id = {obj["id"]: obj for obj in repaired["objects"]}
        self.assertAlmostEqual(
            by_id["lamp_left"]["x"],
            by_id["nightstand_left"]["x"] - 0.12,
        )
        self.assertAlmostEqual(
            by_id["lamp_left"]["z"],
            by_id["nightstand_left"]["dimensions"]["height"],
        )

    def test_hard_min_is_hard_and_target_does_not_penalize_explicit_objects(self) -> None:
        plan = rules_layout(build_baseline_brief("A bedroom."))
        plan["object_budget"]["hard_min"] = len(plan["objects"]) + 1
        below = validate_layout(plan)
        self.assertFalse(below["ok"])
        self.assertIn(
            "object_count_below_hard_min",
            {item["type"] for item in below["violations"]},
        )

        plan["object_budget"]["hard_min"] = 1
        plan["object_budget"]["target_max"] = len(plan["objects"]) - 1
        above = validate_layout(plan)
        self.assertTrue(above["ok"], above)
        self.assertEqual(above["metrics"]["compactness_status"], "balanced")
        self.assertNotIn(
            "object_count_above_soft_max", {item["type"] for item in above["violations"]}
        )

    def test_runtime_safety_limit_is_the_only_absolute_count_cap(self) -> None:
        plan = rules_layout(build_baseline_brief("A bedroom."))
        plan["object_budget"]["hard_runtime_limit"] = len(plan["objects"]) - 1
        report = validate_layout(plan)
        self.assertFalse(report["ok"])
        self.assertIn(
            "object_count_above_runtime_safety_limit",
            {item["type"] for item in report["violations"]},
        )

    def test_validator_rejects_dimensions_changed_after_asset_resolution(self) -> None:
        plan = rules_layout(build_baseline_brief("A bedroom."))
        bed = next(obj for obj in plan["objects"] if obj["id"] == "bed")
        effective = deepcopy(bed["dimensions"])
        bed["asset_source"] = "curated_library"
        bed["dimension_resolution"] = {
            "accepted": True,
            "status": "exact_match",
            "policy_mode": "fixed_physical",
            "effective_dimensions": effective,
            "scale_factors": {"width": 1.0, "length": 1.0, "height": 1.0},
        }
        bed["dimensions"]["width"] += 0.2
        report = validate_layout(plan)
        self.assertIn(
            "asset_dimensions_changed_after_resolution",
            {item["type"] for item in report["violations"]},
        )

    def test_explicit_centered_composition_rejects_shifted_bed(self) -> None:
        brief = build_baseline_brief(
            "A bedroom, strict front-facing view, eye-level camera, centered composition."
        )
        plan = rules_layout(brief)
        next(obj for obj in plan["objects"] if obj["id"] == "bed")["x"] = 1.4
        report = validate_layout(plan)
        self.assertIn(
            "composition_primary_group_off_center",
            {item["type"] for item in report["violations"]},
        )
        self.assertLess(report["metrics"]["composition"]["centeredness_score"], 0.72)

    def test_default_room_compactness_is_balanced(self) -> None:
        for room_type in ("bedroom", "living_room", "kitchen", "study", "restroom"):
            with self.subTest(room_type=room_type):
                plan = deterministic_repair(
                    rules_layout(build_baseline_brief("A room.", room_type))
                )
                report = validate_layout(plan)
                self.assertEqual(report["metrics"]["compactness_status"], "balanced")
                self.assertEqual(report["metrics"]["compactness_score"], 1.0)

    def test_missing_window_and_floor_material_are_hard_failures(self) -> None:
        plan = rules_layout(build_baseline_brief("A bedroom."))
        plan["architecture"]["windows"] = []
        plan["architecture"]["floor"]["material"] = {}
        report = validate_layout(plan)
        self.assertFalse(report["ok"])
        violation_types = {item["type"] for item in report["violations"]}
        self.assertIn("architecture_window_count", violation_types)
        self.assertIn("floor_material_missing", violation_types)

    def test_missing_wall_material_is_a_hard_failure(self) -> None:
        plan = rules_layout(build_baseline_brief("A bedroom."))
        plan["architecture"]["wall_finish"]["default"] = {}
        report = validate_layout(plan)
        self.assertFalse(report["ok"])
        self.assertIn(
            "wall_material_missing",
            {item["type"] for item in report["violations"]},
        )

    def test_missing_enclosing_wall_is_a_hard_failure(self) -> None:
        plan = rules_layout(build_baseline_brief("A bedroom."))
        plan["architecture"]["walls"].remove("west")
        report = validate_layout(plan)
        self.assertFalse(report["ok"])
        self.assertIn(
            "architecture_enclosing_walls",
            {item["type"] for item in report["violations"]},
        )

    def test_repair_keeps_tall_furniture_clear_of_window(self) -> None:
        plan = rules_layout(build_baseline_brief("A bedroom."))
        by_id = {obj["id"]: obj for obj in plan["objects"]}
        by_id["wardrobe"]["x"] = 0.31
        by_id["wardrobe"]["y"] = 2.2
        by_id["wardrobe"]["yaw"] = 90.0
        by_id["wardrobe"]["preferred_wall"] = "west"
        by_id["wardrobe"]["facing_constraint"]["wall"] = "west"
        broken = validate_layout(plan)
        self.assertIn("window_obstruction", {item["type"] for item in broken["violations"]})
        repaired = deterministic_repair(plan)
        self.assertTrue(validate_layout(repaired)["ok"])


class AssetRegistryTest(unittest.TestCase):
    def test_curated_bed_without_component_metadata_is_assumed_not_verified(self) -> None:
        prompt_path = (
            Path(__file__).parents[1] / "prompts" / "bedroom_rgbd_front_strict.txt"
        )
        brief = build_baseline_brief(prompt_path.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bed.glb").write_bytes(b"glTF")
            manifest_path = root / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "assets": [
                            {
                                "asset_id": "bed_composite_unannotated",
                                "category": "bed",
                                "styles": ["modern"],
                                "qa_status": "approved",
                                "glb_path": "bed.glb",
                                "dimensions": {
                                    "width": 1.8,
                                    "length": 2.1,
                                    "height": 1.05,
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            report = resolve_assets(
                brief,
                root / "run",
                mode="plan",
                manifest_path=manifest_path,
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
        resolution = report["component_resolution"][0]
        self.assertEqual(
            resolution["resolution_status"],
            "assumed_satisfied_by_composite_asset",
        )
        self.assertIsNone(resolution["manifest_included_count"])
        self.assertTrue(report["component_resolution_ok"])

    def test_manifest_component_shortfall_blocks_assembly_readiness(self) -> None:
        brief = build_baseline_brief("A bedroom with exactly two pillows.")
        bed = next(obj for obj in brief["objects"] if obj["category"] == "bed")
        brief["objects"] = [bed]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bed.glb").write_bytes(b"glTF")
            manifest_path = root / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "assets": [
                            {
                                "asset_id": "bed_one_pillow",
                                "category": "bed",
                                "qa_status": "approved",
                                "glb_path": "bed.glb",
                                "dimensions": {
                                    "width": 1.8,
                                    "length": 2.1,
                                    "height": 1.05,
                                },
                                "included_components": {"pillow": 1},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            report = resolve_assets(
                brief,
                root / "run",
                mode="plan",
                manifest_path=manifest_path,
                trellis_url="http://127.0.0.1:8082",
                seed=1,
                timeout=1,
                steps=1,
                texture_size=64,
                decimation_target=100,
                pipeline_type="512",
                preprocess_image=False,
                max_new_assets=0,
            )
        self.assertEqual(
            report["component_resolution"][0]["resolution_status"],
            "asset_manifest_component_shortfall",
        )
        self.assertFalse(report["component_resolution_ok"])
        self.assertFalse(report["ready_for_assembly"])

    def test_fixed_physical_rejects_large_layout_resize(self) -> None:
        resolution = resolve_dimension_adaptation(
            {"width": 1.0, "length": 1.0, "height": 1.0},
            {"width": 1.3, "length": 1.0, "height": 1.0},
            dimension_policy_for_category("office_chair"),
        )
        self.assertFalse(resolution["accepted"])
        self.assertEqual(resolution["status"], "incompatible_dimensions")

    def test_uniform_and_axis_scaling_are_bounded(self) -> None:
        uniform = resolve_dimension_adaptation(
            {"width": 1.0, "length": 1.0, "height": 1.0},
            {"width": 1.1, "length": 1.1, "height": 1.1},
            dimension_policy_for_category("potted_plant"),
        )
        self.assertTrue(uniform["accepted"])
        self.assertEqual(uniform["status"], "bounded_uniform_scale")
        anisotropic = resolve_dimension_adaptation(
            {"width": 1.0, "length": 1.0, "height": 1.0},
            {"width": 1.1, "length": 1.0, "height": 1.1},
            dimension_policy_for_category("potted_plant"),
        )
        self.assertFalse(anisotropic["accepted"])

        desk = resolve_dimension_adaptation(
            {"width": 1.4, "length": 0.72, "height": 0.75},
            {"width": 1.2, "length": 0.72, "height": 0.75},
            dimension_policy_for_category("desk"),
        )
        self.assertTrue(desk["accepted"])
        self.assertEqual(desk["status"], "bounded_axis_scale")
        self.assertAlmostEqual(desk["scale_factors"]["width"], 1.2 / 1.4)

    def test_registry_prefers_dimension_compatible_variant(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "modern.glb").write_bytes(b"glTF")
            (root / "exact.glb").write_bytes(b"glTF")
            manifest_path = root / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "assets": [
                            {
                                "asset_id": "bed_modern_wrong_size",
                                "category": "bed",
                                "styles": ["modern"],
                                "qa_status": "approved",
                                "glb_path": "modern.glb",
                                "dimensions": {"width": 1.2, "length": 1.6, "height": 0.8},
                            },
                            {
                                "asset_id": "bed_exact_size",
                                "category": "bed",
                                "styles": ["traditional"],
                                "qa_status": "approved",
                                "glb_path": "exact.glb",
                                "dimensions": {"width": 1.8, "length": 2.1, "height": 1.05},
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            match = AssetRegistry(manifest_path).find(
                "bed",
                ["modern"],
                target_dimensions={"width": 1.8, "length": 2.1, "height": 1.05},
                dimension_policy=dimension_policy_for_category("bed"),
            )
            self.assertEqual(match["asset_id"], "bed_exact_size")
            self.assertEqual(match["_dimension_resolution"]["status"], "exact_match")

    def test_single_asset_pilot_accepts_architecture_door_category(self) -> None:
        self.assertEqual(
            PILOT_ASSET_DEFINITIONS["door"]["dimensions"],
            [0.9, 0.08, 2.1],
        )

    def test_registry_prefers_approved_style_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "modern.glb").write_bytes(b"glTF")
            (root / "other.glb").write_bytes(b"glTF")
            manifest = {
                "assets": [
                    {
                        "asset_id": "bed_other",
                        "category": "bed",
                        "styles": ["traditional"],
                        "qa_status": "approved",
                        "glb_path": "other.glb",
                    },
                    {
                        "asset_id": "bed_modern",
                        "category": "bed",
                        "styles": ["modern"],
                        "qa_status": "approved",
                        "glb_path": "modern.glb",
                    },
                ]
            }
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            match = AssetRegistry(manifest_path).find("bed", ["modern"])
            self.assertIsNotNone(match)
            self.assertEqual(match["asset_id"], "bed_modern")

    def test_registry_cycles_equal_score_variants(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "one.glb").write_bytes(b"glTF")
            (root / "two.glb").write_bytes(b"glTF")
            manifest_path = root / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "assets": [
                            {
                                "asset_id": "nightstand_001",
                                "category": "nightstand",
                                "styles": ["modern"],
                                "qa_status": "approved",
                                "glb_path": "one.glb",
                            },
                            {
                                "asset_id": "nightstand_002",
                                "category": "nightstand",
                                "styles": ["modern"],
                                "qa_status": "approved",
                                "glb_path": "two.glb",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            registry = AssetRegistry(manifest_path)
            first = registry.find("nightstand", ["modern"], variant_index=0)
            second = registry.find("nightstand", ["modern"], variant_index=1)
            self.assertEqual(first["asset_id"], "nightstand_001")
            self.assertEqual(second["asset_id"], "nightstand_002")

    def test_resolve_assets_applies_curated_pose_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bed.glb").write_bytes(b"glTF")
            manifest_path = root / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "assets": [
                            {
                                "asset_id": "bed_curated",
                                "category": "bed",
                                "styles": ["modern"],
                                "qa_status": "approved",
                                "glb_path": "bed.glb",
                                "dimensions": {"width": 1.8, "length": 2.1, "height": 1.05},
                                "asset_axis_to_z": 2,
                                "asset_local_yaw_offset_degrees": 90,
                                "asset_canonical_front": {"axis": "-y", "confidence": 0.9},
                                "asset_orientation": {"canonical_front_axis": "-y", "confidence": 0.9},
                                "asset_affordance": {"allowed_wall_contact_faces": ["back"]},
                                "usage_constraints": ["floor_only"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            brief = {
                "styles": ["modern"],
                "objects": [
                    {
                        "id": "bed",
                        "category": "bed",
                        "asset_prompt": "bed",
                        "dimensions": {"width": 1.8, "length": 2.1, "height": 1.05},
                    }
                ],
            }
            resolve_assets(
                brief,
                root / "run",
                mode="plan",
                manifest_path=manifest_path,
                trellis_url="http://127.0.0.1:8082",
                seed=1,
                timeout=1,
                steps=1,
                texture_size=64,
                decimation_target=100,
                pipeline_type="512",
                preprocess_image=False,
                max_new_assets=0,
            )
            obj = brief["objects"][0]
            self.assertEqual(obj["dimensions"]["width"], 1.8)
            self.assertEqual(obj["asset_local_yaw_offset_degrees"], 90)
            self.assertEqual(obj["asset_canonical_front"]["axis"], "-y")
            self.assertEqual(obj["asset_orientation"]["canonical_front_axis"], "-y")
            self.assertEqual(obj["asset_affordance"]["allowed_wall_contact_faces"], ["back"])
            self.assertEqual(obj["usage_constraints"], ["floor_only"])
            self.assertEqual(obj["dimension_resolution"]["status"], "exact_match")
            self.assertEqual(obj["requested_dimensions"], obj["source_dimensions"])

    def test_incompatible_curated_asset_becomes_size_specific_generation_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bed.glb").write_bytes(b"glTF")
            manifest_path = root / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "assets": [
                            {
                                "asset_id": "bed_too_small",
                                "category": "bed",
                                "styles": ["modern"],
                                "qa_status": "approved",
                                "glb_path": "bed.glb",
                                "dimensions": {"width": 1.2, "length": 1.6, "height": 0.8},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            brief = {
                "styles": ["modern"],
                "objects": [
                    {
                        "id": "bed",
                        "category": "bed",
                        "asset_prompt": "bed",
                        "dimensions": {"width": 1.8, "length": 2.1, "height": 1.05},
                        "requested_dimensions": {"width": 1.8, "length": 2.1, "height": 1.05},
                        "dimension_policy": dimension_policy_for_category("bed"),
                    }
                ],
            }
            report = resolve_assets(
                brief,
                root / "run",
                mode="plan",
                manifest_path=manifest_path,
                trellis_url="http://127.0.0.1:8082",
                seed=1,
                timeout=1,
                steps=1,
                texture_size=64,
                decimation_target=100,
                pipeline_type="512",
                preprocess_image=False,
                max_new_assets=0,
            )
            self.assertEqual(report["results"][0]["status"], "planned_missing")
            self.assertEqual(
                report["results"][0]["dimension_resolution"]["status"],
                "planned_generation_for_requested_dimensions",
            )
            self.assertEqual(len(report["results"][0]["dimension_rejections"]), 1)

    def test_architecture_assets_reuse_window_and_fallback_missing_door(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "window.glb").write_bytes(b"glTF")
            manifest_path = root / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "assets": [
                            {
                                "asset_id": "window_curated",
                                "category": "window",
                                "styles": ["modern"],
                                "qa_status": "approved",
                                "glb_path": "window.glb",
                                "dimensions": {
                                    "width": 1.04,
                                    "length": 0.08,
                                    "height": 1.296,
                                },
                                "asset_axis_to_z": 2,
                                "asset_canonical_front": {
                                    "axis": "+y",
                                    "confidence": 0.9,
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            brief = build_baseline_brief("A modern bedroom.")
            report = resolve_assets(
                brief,
                root / "run",
                mode="plan",
                manifest_path=manifest_path,
                trellis_url="http://127.0.0.1:8082",
                seed=1,
                timeout=1,
                steps=1,
                texture_size=64,
                decimation_target=100,
                pipeline_type="512",
                preprocess_image=False,
                max_new_assets=0,
            )
            door = brief["architecture"]["doors"][0]
            window = brief["architecture"]["windows"][0]
            self.assertEqual(door["asset_binding"]["status"], "parametric_fallback")
            self.assertEqual(window["asset_binding"]["status"], "reused")
            self.assertEqual(window["asset_binding"]["asset_id"], "window_curated")
            self.assertEqual(window["asset_binding"]["placement_yaw_degrees"], 270.0)
            self.assertEqual(report["architecture_reused_count"], 1)
            self.assertEqual(report["architecture_fallback_count"], 1)


if __name__ == "__main__":
    unittest.main()
