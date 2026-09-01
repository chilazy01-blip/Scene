from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sage.experiments.codex_trellis_scene_v2.resource_health import (
    RESOURCE_HEALTH_SCHEMA,
    ResourceHealthThresholds,
    append_health_checkpoint,
    sample_resource_health,
)


class ResourceHealthTest(unittest.TestCase):
    def test_default_heavy_launch_gate_requires_96_gib_available(self) -> None:
        self.assertEqual(ResourceHealthThresholds().minimum_mem_available_gib, 96.0)

    def test_snapshot_records_normalized_load_and_storage(self) -> None:
        report = sample_resource_health(sample_seconds=0.01)
        self.assertEqual(report["schema"], RESOURCE_HEALTH_SCHEMA)
        self.assertGreater(report["metrics"]["logical_cpu_count"], 0)
        self.assertGreater(report["metrics"]["data_free_gib"], 0)
        self.assertGreaterEqual(report["metrics"]["iowait_fraction"], 0.0)

    def test_required_gate_fails_with_impossible_memory_threshold(self) -> None:
        thresholds = ResourceHealthThresholds(minimum_mem_available_gib=10**9)
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(RuntimeError):
                append_health_checkpoint(
                    Path(temporary) / "health.jsonl",
                    stage="synthetic_rejection",
                    require_healthy=True,
                    thresholds=thresholds,
                )


if __name__ == "__main__":
    unittest.main()
