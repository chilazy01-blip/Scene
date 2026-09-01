from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from sage.experiments.codex_trellis_scene_v2.heavy_job_broker import HeavyJobBroker


def healthy():
    return {"healthy_for_heavy_stage": True, "reasons": []}


def idle_gpu():
    return {"available": True, "process_pids": []}


class HeavyJobBrokerTests(unittest.TestCase):
    def broker(self, root: Path, **kwargs):
        return HeavyJobBroker(root / "broker.json", resource_probe=healthy, gpu_probe=idle_gpu, require_nvml=True, **kwargs)

    def test_two_concurrent_requests_do_not_get_two_leases(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            broker = self.broker(Path(temporary))
            self.assertTrue(broker.acquire("first")["accepted"])
            second = broker.acquire("second")
            self.assertFalse(second["accepted"])
            self.assertEqual(second["status"], "queue_full")

    def test_external_gpu_process_rejects_admission(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            broker = HeavyJobBroker(Path(temporary) / "broker.json", resource_probe=healthy, gpu_probe=lambda: {"available": True, "process_pids": [424242]}, require_nvml=True)
            report = broker.acquire("job")
            self.assertFalse(report["accepted"])
            self.assertEqual(report["status"], "external_gpu_busy")

    def test_expired_or_dead_worker_lease_is_recovered(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = self.broker(root, lease_ttl_seconds=1.01, owner_pid=99999999)
            self.assertTrue(first.acquire("orphan")["accepted"])
            state = first.snapshot(); state["active"]["heartbeat_at"] = time.time() - 5; first._write(state)
            second = self.broker(root)
            self.assertTrue(second.acquire("replacement")["accepted"])
            self.assertEqual(second.snapshot()["active"]["job_id"], "replacement")


if __name__ == "__main__":
    unittest.main()
