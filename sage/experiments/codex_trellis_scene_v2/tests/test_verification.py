from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from sage.experiments.codex_trellis_scene_v2.content_chain import file_binding
from sage.experiments.codex_trellis_scene_v2.io_utils import write_json
from sage.experiments.codex_trellis_scene_v2.verification import (
    REQUIRED_TIERS,
    audit_artifact_pair,
    audit_output_allowlist,
    audit_test_catalog,
    build_verification_status,
)


class VerificationSystemTest(unittest.TestCase):
    def test_every_completed_problem_has_resolvable_negative_test(self) -> None:
        report = audit_test_catalog()
        self.assertTrue(report["ok"])
        self.assertEqual(
            set(report["negative_regressions"]),
            {f"P{index:03d}" for index in range(1, 14)},
        )
        self.assertEqual(len(report["chaos_cases"]), 7)

    def test_half_written_artifact_pair_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / "asset.glb"
            metadata = root / "asset.json"
            artifact.write_bytes(b"complete-glb")
            report = audit_artifact_pair(artifact, metadata)
            self.assertFalse(report["ok"])
            self.assertIn("metadata_missing", report["failures"])
            write_json(metadata, {"artifact": file_binding(artifact)})
            artifact.write_bytes(b"truncated")
            report = audit_artifact_pair(artifact, metadata)
        self.assertIn("artifact_binding_mismatch", report["failures"])

    def test_old_output_pollution_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "current.json").write_text("{}", encoding="utf-8")
            (root / "old_scene.glb").write_bytes(b"stale")
            report = audit_output_allowlist(root, ["current.json"])
        self.assertFalse(report["ok"])
        self.assertEqual(report["unexpected_files"], ["old_scene.glb"])

    def test_release_status_requires_all_hardware_evidence(self) -> None:
        with TemporaryDirectory() as directory:
            evidence = Path(directory) / "evidence.json"
            evidence.write_text("{}", encoding="utf-8")
            tiers = {
                tier: {
                    "status": "passed",
                    "test_count": 1,
                    "evidence": [
                        {"path": str(evidence), "binding": file_binding(evidence)}
                    ],
                }
                for tier in REQUIRED_TIERS
            }
            tiers["nightly_gpu"]["actual_gpu"] = True
            config = {
                "test_counts_are_machine_generated": True,
                "tiers": tiers,
            }
            accepted = build_verification_status(config)
            self.assertTrue(accepted["release_eligible"])
            manual_counts = build_verification_status({"tiers": tiers})
            self.assertIn(
                "test_counts_not_machine_generated", manual_counts["failures"]
            )
            tiers["nightly_gpu"].pop("actual_gpu")
            rejected = build_verification_status(config)
        self.assertFalse(rejected["release_eligible"])
        self.assertIn("nightly_gpu:actual_gpu_required", rejected["failures"])


if __name__ == "__main__":
    unittest.main()
