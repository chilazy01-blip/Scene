from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sage.experiments.codex_trellis_scene_v2.content_chain import (
    content_hash,
    build_generation_contract,
    make_artifact_certificate,
    verify_artifact_certificate,
)
from sage.experiments.codex_trellis_scene_v2.pilot_asset import validate_pilot_report


class ContentChainTests(unittest.TestCase):
    def _contract(self, reference: Path, **overrides):
        values = dict(
            category="chair",
            prompt="one chair",
            target_dimensions_m={"width": 0.5, "length": 0.5, "height": 0.9},
            seed=7,
            model_fingerprint="trellis-model-a",
            rmbg_fingerprint="rmbg-a",
            pipeline_type="512",
            steps=12,
            texture_size=1024,
            decimation_target=200000,
            preprocess_image=True,
            code_version="commit-a",
            reference_image=reference,
        )
        values.update(overrides)
        return build_generation_contract(**values)

    def test_reference_seed_model_and_parameters_change_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            reference = Path(temporary) / "reference.png"
            reference.write_bytes(b"reference-a")
            baseline = self._contract(reference)["content_key"]
            for override in (
                {"seed": 8},
                {"model_fingerprint": "trellis-model-b"},
                {"steps": 13},
                {"texture_size": 512},
                {"decimation_target": 100000},
            ):
                self.assertNotEqual(baseline, self._contract(reference, **override)["content_key"])
            reference.write_bytes(b"reference-b")
            self.assertNotEqual(baseline, self._contract(reference)["content_key"])

    def test_artifact_or_evidence_replacement_invalidates_certificate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "asset.glb"
            evidence = root / "view.png"
            artifact.write_bytes(b"asset-a")
            evidence.write_bytes(b"view-a")
            upstream = {"generation_key": "abc"}
            rules = {"renderer": "blender-4.3.2", "qa_rules": "v2"}
            certificate = make_artifact_certificate(
                artifact, upstream=upstream, rules=rules, evidence={"front": evidence}
            )
            self.assertTrue(
                verify_artifact_certificate(
                    certificate,
                    artifact,
                    upstream=upstream,
                    rules=rules,
                    evidence={"front": evidence},
                )[0]
            )
            evidence.write_bytes(b"view-b")
            self.assertFalse(
                verify_artifact_certificate(
                    certificate,
                    artifact,
                    upstream=upstream,
                    rules=rules,
                    evidence={"front": evidence},
                )[0]
            )

    def test_pilot_resume_rejects_replaced_inputs_and_changed_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reference = root / "reference.png"
            artifact = root / "asset.glb"
            reference.write_bytes(b"reference-a")
            artifact.write_bytes(b"asset-a")
            contract = self._contract(reference)
            generation = {"job_id": "job-a", "request": {"seed": 7}}
            rules = {"kind": "trellis_single_asset_pilot", "inspection_version": 1}
            report = {
                "ok": True,
                "asset_glb": str(artifact),
                "reference_image": str(reference),
                "generation": generation,
                "generation_contract": contract,
                "content_certificate": make_artifact_certificate(
                    artifact,
                    upstream={
                        "generation_contract": contract,
                        "generation_metadata_hash": content_hash(generation),
                    },
                    rules=rules,
                    evidence={"reference_image": reference},
                ),
            }
            self.assertTrue(validate_pilot_report(report, contract)[0])
            artifact.write_bytes(b"asset-replaced")
            self.assertFalse(validate_pilot_report(report, contract)[0])
            artifact.write_bytes(b"asset-a")
            reference.write_bytes(b"reference-replaced")
            self.assertFalse(validate_pilot_report(report, contract)[0])
            reference.write_bytes(b"reference-a")
            for changed in (
                self._contract(reference, seed=8),
                self._contract(reference, model_fingerprint="model-b"),
                self._contract(reference, steps=13),
            ):
                self.assertFalse(validate_pilot_report(report, changed)[0])


if __name__ == "__main__":
    unittest.main()
