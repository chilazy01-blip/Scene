from __future__ import annotations

import unittest
from pathlib import Path

from ..trellis_fresh_cgroup_supervisor import build_systemd_run_command


class TrellisFreshCgroupSupervisorTest(unittest.TestCase):
    def test_each_child_keeps_resource_gate_and_unique_log(self) -> None:
        command = build_systemd_run_command(
            unit_name="trellis-pair-7",
            log_path=Path("/tmp/trellis-pair-7.log"),
            memory_high="12G",
            memory_max="16G",
            bridge_command=["/usr/bin/python3", "bridge.py"],
        )
        self.assertIn("--unit=trellis-pair-7", command)
        self.assertIn("--property=MemoryHigh=12G", command)
        self.assertIn("--property=MemoryMax=16G", command)
        self.assertIn("--property=ManagedOOMPreference=omit", command)
        self.assertIn(
            "--property=StandardOutput=append:/tmp/trellis-pair-7.log",
            command,
        )
        self.assertEqual(command[-2:], ["/usr/bin/python3", "bridge.py"])


if __name__ == "__main__":
    unittest.main()
