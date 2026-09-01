from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sage.experiments.codex_trellis_scene_v2.stage_dag import STAGES, StageDAG


class StageDAGTests(unittest.TestCase):
    @staticmethod
    def _commit_prefix(dag: StageDAG, root: Path, stop: int) -> None:
        for stage in STAGES[:stop]:
            started = dag.begin(stage, inputs={"value": stage}, config={"v": 1})
            output = root / f"{stage}.json"
            output.write_text(stage)
            dag.commit(stage, started["attempt"]["attempt"], outputs={"main": output})

    def test_changed_input_invalidates_only_stage_and_downstream(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dag = StageDAG(root / "run_dag.json")
            for stage in STAGES:
                started = dag.begin(stage, inputs={"value": stage}, config={"v": 1})
                output = root / f"{stage}.json"; output.write_text(stage)
                dag.commit(stage, started["attempt"]["attempt"], outputs={"main": output})
            for stage in STAGES[:3]:
                self.assertTrue(dag.can_reuse(stage, inputs={"value": stage}, config={"v": 1}))
            changed = dag.begin("asset_plan", inputs={"value": "changed"}, config={"v": 1})
            self.assertFalse(changed["reused"])
            for stage in STAGES[:3]:
                self.assertNotIn("invalidated_by", dag.value["stages"][stage])
            for stage in STAGES[3:]:
                self.assertIn("invalidated_by", dag.value["stages"][stage])

    def test_failed_attempt_is_never_reused_or_mixed_with_next_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); dag = StageDAG(root / "run_dag.json")
            first = dag.begin("expand", inputs={"prompt": "a"}, config={})
            dag.fail("expand", 1, "interrupted")
            second = dag.begin("expand", inputs={"prompt": "a"}, config={})
            output = root / "attempt_2.json"; output.write_text("complete")
            committed = dag.commit("expand", 2, outputs={"brief": output})
            self.assertEqual(first["attempt"]["status"], "failed")
            self.assertEqual(second["attempt"]["attempt"], 2)
            self.assertEqual(set(committed["outputs"]), {"brief"})
            self.assertTrue(dag.can_reuse("expand", inputs={"prompt": "a"}, config={}))
            output.write_text("tampered")
            self.assertFalse(dag.can_reuse("expand", inputs={"prompt": "a"}, config={}))

    def test_interruption_at_every_stage_restarts_only_that_attempt(self) -> None:
        for index, stage in enumerate(STAGES):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                dag = StageDAG(root / "run_dag.json")
                self._commit_prefix(dag, root, index)
                first = dag.begin(stage, inputs={"value": stage}, config={"v": 1})
                dag.fail(stage, first["attempt"]["attempt"], "simulated interruption")
                second = dag.begin(stage, inputs={"value": stage}, config={"v": 1})
                output = root / f"{stage}_attempt_2.json"
                output.write_text("complete")
                dag.commit(stage, second["attempt"]["attempt"], outputs={"main": output})
                self.assertEqual(second["attempt"]["attempt"], 2)
                for upstream in STAGES[:index]:
                    self.assertTrue(
                        dag.can_reuse(
                            upstream,
                            inputs={"value": upstream},
                            config={"v": 1},
                        )
                    )


if __name__ == "__main__":
    unittest.main()
