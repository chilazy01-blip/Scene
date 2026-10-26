"""Ledger regression tests: retries cannot duplicate charge or consume QA headroom."""
import tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from . import protocol
from .common import safe_save,read_bound_json

class AccountingTest(unittest.TestCase):
    def test_duplicate_reservation_and_pending_replay_headroom(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);entries=[]
            for i in range(9):
                trial=root/str(i);full=trial/'full';cost=trial/'cost'
                full.mkdir(parents=True);cost.mkdir()
                safe_save(cost/'REPORT.json',dict(physics_steps=10000))
                safe_save(full/'REPORT.json',dict(task_passed=i==8))
                entries.append(dict(output=str(cost),maximum_steps=12840,episode_output=str(full),success_replay_headroom=12840))
            safe_save(root/'COST.json',dict(reservations=entries))
            auth=dict(deadline_epoch_utc=time.time()+100,prefix_physics_steps=0)
            with patch.object(protocol,'ROOT',root),patch.object(protocol,'authorize',return_value=auth):
                with self.assertRaisesRegex(RuntimeError,'budget insufficient'):
                    protocol.reserve(root,root/'new/full',12840)
                self.assertEqual(len(read_bound_json(root/'COST.json')['reservations']),9)
                protocol.reserve(root,root/'8/continuous_replay',10000)
                with self.assertRaises(AssertionError):
                    protocol.reserve(root,root/'8/continuous_replay',10000)
                self.assertEqual(len(read_bound_json(root/'COST.json')['reservations']),10)

if __name__=='__main__':unittest.main()
