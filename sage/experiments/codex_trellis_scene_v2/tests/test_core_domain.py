from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sage.experiments.codex_trellis_scene_v2.cli import build_parser
from sage.experiments.codex_trellis_scene_v2.core_domain import CORE_STAGE_OWNERSHIP, SceneRequest
from sage.experiments.codex_trellis_scene_v2.legacy_adapter import adapt_legacy_args
from sage.experiments.codex_trellis_scene_v2.project_facts import build_project_facts, parser_defaults


ROOT = Path(__file__).resolve().parents[4]


class CoreDomainTest(unittest.TestCase):
    def test_text_front_ends_share_the_same_core_request_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            a = adapt_legacy_args("flow2_text", ["--prompt", "a study", "--output-dir", temp, "--plan-only"])
            b = adapt_legacy_args("selfmade_text", ["--prompt", "a study", "--output-dir", temp, "--plan-only"])
            self.assertIsInstance(a.scene_request, SceneRequest)
            self.assertEqual(a.scene_request.prompt, b.scene_request.prompt)
            self.assertEqual(a.scene_request.source, "text")
            self.assertEqual(tuple(CORE_STAGE_OWNERSHIP["v2_core"]), tuple(b.scene_request.as_document()["core_stage_ownership"]["v2_core"]))

    def test_image_binding_is_content_addressed_soft_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            image = Path(temp) / "reference.png"
            image.write_bytes(b"first")
            args = adapt_legacy_args("flow2_image", ["--flux-image", str(image), "--prompt", "a room with one sofa", "--output-dir", temp, "--plan-only"])
            first = args.scene_request.as_document()
            image.write_bytes(b"second")
            second = SceneRequest.create(prompt="a room with one sofa", output_dir=temp, source="image_reference", reference_image=image).as_document()
            self.assertEqual(first["prompt"], second["prompt"])
            self.assertNotEqual(first["content_hash"], second["content_hash"])

    def test_unknown_legacy_algorithm_switch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(SystemExit):
            adapt_legacy_args("flow2_text", ["--prompt", "room", "--output-dir", temp, "--new-layout-algorithm"])

    def test_all_historical_entry_points_default_to_adapter(self) -> None:
        for relative in (
            "sage/scripts/run_tree_sage_text_scene.py",
            "sage/scripts/run_selfmade_trellis_scene.py",
            "sage/scripts/run_tree_sage_scene.py",
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn('if "--legacy-engine" not in sys.argv:', source)
            self.assertIn("run_legacy_cli_adapter", source)

    def test_project_facts_are_derived_from_live_parser_and_lock(self) -> None:
        facts = build_project_facts(None)
        self.assertEqual(facts["cli_defaults"], parser_defaults())
        self.assertEqual(facts["stage_order"][0], "expand")
        self.assertEqual(facts["document_schemas"]["SceneRequest"], "scene-v2-request/v1")
        self.assertEqual(len(facts["runtime_lock"]["binding"]["sha256"]), 64)
        parser = build_parser()
        self.assertEqual(facts["cli_defaults"]["asset_mode"], parser.get_default("asset_mode"))

    def test_canonical_docs_do_not_copy_dynamic_counts_or_defaults(self) -> None:
        for relative in ("README.md", "docs/ARCHITECTURE.md", "docs/RUNBOOK.md", "docs/RESEARCH_STATUS.md"):
            text = (ROOT / relative).read_text(encoding="utf-8")
            self.assertNotRegex(text, r"\b\d+/\d+\b")
        self.assertIn("project_facts", (ROOT / "README.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
