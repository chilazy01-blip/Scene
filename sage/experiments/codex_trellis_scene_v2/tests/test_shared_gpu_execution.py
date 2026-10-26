from __future__ import annotations

import json
import multiprocessing
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

from ..heavy_job_broker import HeavyJobBroker
from ..shared_gpu_execution import (
    GIB, SharedGpuBroker, SharedGpuPolicy, process_identity, run_watchdog,
    gpu_budget, parse_gpu_inventory, running_stop_reasons, select_shared_gpu,
)


def gpu(index=0, free=30, pids=None):
    return {"available": True, "gpu_index": index, "uuid": f"GPU-test-{index}", "memory_total_bytes": 48 * GIB, "memory_used_bytes": int((48 - free) * GIB), "process_pids": pids or []}


def resources(available=120, reasons=None):
    reasons = reasons or []
    return {"healthy_for_heavy_stage": not reasons and available >= 96, "reasons": reasons, "metrics": {"mem_available_gib": available, "data_free_gib": 200, "tmp_free_gib": 40}}


def cgroup(current=4, maximum=32):
    return {"path": "/test-owned.scope", "memory_max": str(int(maximum * GIB)), "memory_current": str(int(current * GIB))}


class SharedGpuExecutionTests(unittest.TestCase):
    def test_single_driver_snapshot_preserves_graphics_and_compute_pids_and_real_free_memory(self):
        xml = """<nvidia_smi_log><gpu><uuid>GPU-actual</uuid><product_name>Test 48G</product_name>
        <fb_memory_usage><total>49152 MiB</total><used>10240 MiB</used><free>38400 MiB</free></fb_memory_usage>
        <processes><process_info><pid>123</pid><type>C</type><used_memory>8192 MiB</used_memory></process_info>
        <process_info><pid>456</pid><type>G</type><used_memory>2048 MiB</used_memory></process_info></processes>
        </gpu></nvidia_smi_log>"""
        row = parse_gpu_inventory(xml)[0]
        self.assertEqual(row["process_pids"], [123, 456])
        self.assertEqual(row["memory_free_bytes"] / GIB, 37.5)
        self.assertEqual(row["processes"][1]["type"], "G")

    def selection(self, **kwargs):
        defaults = dict(maximum_cgroup_memory_bytes=32 * GIB, inventory_probe=lambda: [gpu()], resource_probe=resources, cgroup_probe=cgroup, sleep=lambda _: None)
        defaults.update(kwargs)
        return select_shared_gpu(SharedGpuPolicy(), **defaults)

    def broker(self, root, **kwargs):
        defaults = dict(policy=SharedGpuPolicy(), selected_gpu=gpu(), evidence_path=root / "admissions.jsonl", inventory_probe=lambda: [gpu(pids=[424242])], resource_probe=resources, cgroup_probe=cgroup, sleep=lambda _: None, maximum_cgroup_memory_bytes=32 * GIB)
        defaults.update(kwargs)
        return SharedGpuBroker(root / "lease.json", **defaults)

    def test_three_samples_select_best_guaranteed_capacity_and_preserve_external_pids(self):
        scans = iter([[gpu(0, free=free0, pids=[555]), gpu(1, free=free1, pids=[666, 777])] for free0, free1 in [(30, 34), (30.5, 33.5), (30, 34)]])
        result = self.selection(inventory_probe=lambda: next(scans))
        self.assertTrue(result["accepted"])
        self.assertEqual(result["gpu"]["gpu_index"], 1)
        self.assertEqual(result["minimum_free_gib"], 33.5)
        self.assertEqual(result["gpu"]["process_pids"], [666, 777])
        self.assertEqual(len(result["samples"]), 3)

    def test_full_peak_plus_reserve_and_stability_are_required(self):
        for values in ([23.9, 23.9, 23.9], [30, 28, 30], [30, 23, 30]):
            with self.subTest(values=values):
                scans = iter([[gpu(free=free)] for free in values])
                result = self.selection(inventory_probe=lambda: next(scans))
                self.assertFalse(result["accepted"])
                self.assertEqual(result["status"], "no_stable_gpu_capacity")

    def test_cold_then_warm_sequential_job_credits_only_own_resident_memory(self):
        owner = os.getpid()
        cold = gpu(free=30, pids=[424242])
        warm = {**gpu(free=14, pids=[owner, 424242]), "processes": [{"pid": str(owner), "used_memory": "12288 MiB"}, {"pid": "424242", "used_memory": "16384 MiB"}]}
        current = [cold]
        with tempfile.TemporaryDirectory() as temporary:
            broker = self.broker(Path(temporary), inventory_probe=lambda: current)
            first = broker.acquire("cold")
            self.assertTrue(first["accepted"])
            self.assertEqual(first["pinned_gpu_budgets"][-1]["required_free_gib"], 24)
            self.assertTrue(broker.release("cold"))
            current[:] = [warm]
            second = broker.acquire("warm")
            self.assertTrue(second["accepted"])
            budget = second["pinned_gpu_budgets"][-1]
            self.assertEqual(budget["verified_own_resident_gib"], 12)
            self.assertEqual(budget["required_free_gib"], 12)
            self.assertEqual(second["minimum_free_gib"], 14)
            self.assertEqual(second["gpu"]["memory_used_bytes"], warm["memory_used_bytes"])
            self.assertIn(424242, second["gpu"]["process_pids"])
            self.assertTrue(broker.release("warm"))

    def test_external_memory_never_contributes_to_own_budget(self):
        row = {**gpu(free=14, pids=[424242]), "processes": [{"pid": "424242", "used_memory": "24576 MiB"}]}
        result = gpu_budget(row, SharedGpuPolicy(), owner_identity=process_identity(os.getpid()), pinned_gpu_uuid=row["uuid"])
        self.assertFalse(result["capacity_sufficient"])
        self.assertEqual(result["verified_own_resident_gib"], 0)
        self.assertEqual(result["required_free_gib"], 24)

    def test_driver_memory_must_be_exact_unambiguous_and_match_owner_identity(self):
        identity = process_identity(os.getpid())
        owner = str(identity["pid"])
        for processes, expected_identity in [([{ "pid": owner, "used_memory": "N/A"}], identity), ([{"pid": owner, "used_memory": "40960 MiB"}], identity), ([{"pid": owner, "used_memory": "12288 MiB"}] * 2, identity), ([{"pid": owner, "used_memory": "12288 MiB"}], {**identity, "start_ticks": identity["start_ticks"] + 1})]:
            row = {**gpu(free=14, pids=[int(owner)]), "processes": processes}
            with self.subTest(processes=processes, identity=expected_identity):
                result = gpu_budget(row, SharedGpuPolicy(), owner_identity=expected_identity, pinned_gpu_uuid=row["uuid"])
                self.assertFalse(result["capacity_sufficient"])
                self.assertEqual(result["verified_own_resident_gib"], 0)

    def test_owner_residency_on_another_gpu_cannot_repair_pinned_capacity(self):
        owner = os.getpid()
        first = gpu(0, free=14)
        other = {**gpu(1, free=14, pids=[owner]), "processes": [{"pid": str(owner), "used_memory": "12288 MiB"}]}
        with tempfile.TemporaryDirectory() as temporary:
            broker = self.broker(Path(temporary), inventory_probe=lambda: [first, other])
            self.assertFalse(broker.acquire("wrong-card")["accepted"])
        self.assertFalse(self.selection(inventory_probe=lambda: [other])["accepted"])

    def test_warm_budget_still_requires_four_gib_of_actual_free_memory(self):
        owner = os.getpid()
        row = {**gpu(free=3.9, pids=[owner]), "processes": [{"pid": str(owner), "used_memory": "24576 MiB"}]}
        result = gpu_budget(row, SharedGpuPolicy(), owner_identity=process_identity(owner), pinned_gpu_uuid=row["uuid"])
        self.assertEqual(result["incremental_peak_needed_gib"], 0)
        self.assertEqual(result["required_free_gib"], 4)
        self.assertFalse(result["capacity_sufficient"])

    def test_startup_memory_and_cgroup_gates_remain_before_lease(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            broker = self.broker(root, resource_probe=lambda: resources(95))
            self.assertEqual(broker.acquire("low-memory")["status"], "resource_busy")
            self.assertIsNone(broker.snapshot().get("active"))
            broker = self.broker(root, cgroup_probe=lambda: {"path": "/", "memory_max": "max", "memory_current": "0"})
            self.assertFalse(broker.acquire("unbounded")["accepted"])
            self.assertIsNone(broker.snapshot().get("active"))

    def test_policy_cannot_disable_required_safety_gates(self):
        for override in ({"minimum_start_mem_available_gib": 95}, {"gpu_reserve_gib": 3.9}, {"stable_samples": 2}, {"sample_interval_seconds": 2}, {"max_runtime_seconds": float("inf")}, {"maximum_running_cgroup_fraction": 0.99}):
            with self.subTest(override=override), self.assertRaises(ValueError):
                SharedGpuPolicy(**override)

    def test_parallel_shared_admissions_take_one_common_lease(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first, second = self.broker(root), self.broker(root)
            with ThreadPoolExecutor(2) as pool:
                results = list(pool.map(lambda pair: pair[0].acquire(pair[1]), [(first, "one"), (second, "two")]))
            self.assertEqual(sum(bool(row["accepted"]) for row in results), 1)
            self.assertEqual(first.snapshot()["active"]["admission_mode"], "explicit_shared_gpu")
            active = first.snapshot()["active"]["job_id"]
            legacy = HeavyJobBroker(root / "lease.json", resource_probe=lambda: {"healthy_for_heavy_stage": True}, gpu_probe=lambda: {"available": True, "process_pids": []})
            self.assertEqual(legacy.acquire("legacy")["status"], "queue_full")
            self.assertTrue(first.release(active))

    def test_live_lease_not_stolen_on_expired_heartbeat_but_stale_pid_identity_recovers(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            broker = self.broker(root)
            broker.acquire("first")
            state = broker.snapshot()
            state["active"]["heartbeat_at"] = time.time() - 999
            broker._write(state)
            self.assertEqual(self.broker(root).acquire("second")["status"], "queue_full")
            state["active"]["owner_identity"]["start_ticks"] += 1
            broker._write(state)
            self.assertTrue(self.broker(root).acquire("recovered")["accepted"])

    def test_pinned_device_resource_change_rejects_without_silently_switching(self):
        with tempfile.TemporaryDirectory() as temporary:
            broker = self.broker(Path(temporary), inventory_probe=lambda: [gpu(0, free=23), gpu(1, free=35)])
            result = broker.acquire("changed")
            self.assertFalse(result["accepted"])
            self.assertEqual(result["status"], "pinned_gpu_capacity_changed")
            self.assertIsNone(broker.snapshot().get("active"))

    def test_running_memory_floor_differs_from_startup_and_all_pressure_limits_work(self):
        sample = {"gpus": [gpu()], "resources": resources(80), "cgroup": cgroup()}
        options = dict(policy=SharedGpuPolicy(), selected_gpu=gpu(), maximum_cgroup_memory_bytes=32 * GIB)
        self.assertEqual(running_stop_reasons(sample, **options), ([], False))
        for field, value, expected in [("gpus", [gpu(free=3.9)], "gpu_free_below_reserve"), ("resources", resources(23.9), "host_memory_below_running_floor"), ("cgroup", cgroup(current=29.5), "cgroup_memory_near_max"), ("gpus", [], "telemetry_or_cgroup_unavailable")]:
            with self.subTest(expected=expected):
                changed = {**sample, field: value}
                self.assertIn(expected, running_stop_reasons(changed, **options)[0])
        self.assertEqual(running_stop_reasons({**sample, "error": "telemetry_deadline_exceeded"}, **options)[0], ["telemetry_deadline_exceeded"])

    def guarded_cpu_child(self, root, *, inventory_probe=None, resource_probe=None, identity_change=False, stubborn=False, max_runtime=10):
        script = "import time; time.sleep(30)"
        if stubborn:
            script = "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print('ready', flush=True); time.sleep(30)"
        child = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, text=True)
        if stubborn:
            self.assertEqual(child.stdout.readline().strip(), "ready")
        sentinel = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        self.addCleanup(self.cleanup_process, child)
        self.addCleanup(self.cleanup_process, sentinel)
        identity = process_identity(child.pid)
        if identity_change:
            identity["start_ticks"] += 1
        config = {"policy": asdict(SharedGpuPolicy(max_runtime_seconds=max_runtime)), "owner_identity": identity, "selected_gpu": gpu(), "maximum_cgroup_memory_bytes": 32 * GIB, "evidence_path": str(root / "watchdog.jsonl")}
        report_root = os.environ.get("SHARED_GPU_TEST_EVIDENCE_DIR")
        if report_root:
            report = Path(report_root) / f"{self._testMethodName}.jsonl"
            report.parent.mkdir(parents=True, exist_ok=True)
            if report.exists():
                raise ValueError("CPU validation evidence path already exists; use a new directory")
            (root / "watchdog.jsonl").symlink_to(report)
        context = multiprocessing.get_context("fork")
        stop, ready = context.Event(), context.Event()
        monitor = context.Process(target=run_watchdog, args=(config, stop, ready), kwargs={"inventory_probe": inventory_probe or (lambda: [gpu(free=3, pids=[sentinel.pid])]), "resource_probe": resource_probe or resources, "cgroup_probe": cgroup})
        monitor.start()
        self.addCleanup(self.cleanup_monitor, monitor, stop)
        return child, sentinel, monitor, stop, ready

    @staticmethod
    def cleanup_process(process):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)
        if process.stdout:
            process.stdout.close()

    @staticmethod
    def cleanup_monitor(process, stop):
        stop.set()
        process.join(timeout=2)
        if process.is_alive():
            process.terminate()
            process.join(timeout=2)

    def test_independent_watchdog_stops_only_bound_cpu_process_even_if_term_ignored(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            child, sentinel, monitor, _, ready = self.guarded_cpu_child(root, stubborn=True)
            self.assertTrue(ready.wait(2))
            self.assertEqual(child.wait(timeout=3), -9)
            monitor.join(timeout=2)
            self.assertEqual(monitor.exitcode, 0)
            self.assertIsNone(sentinel.poll())
            records = [json.loads(line) for line in (root / "watchdog.jsonl").read_text().splitlines()]
            self.assertEqual(records[-1]["reasons"], ["gpu_free_below_reserve"])
            self.assertEqual(records[-1]["owner_identity"]["pid"], child.pid)
            self.assertIn(sentinel.pid, records[-1]["sample"]["gpus"][0]["process_pids"])

    def test_pid_reuse_identity_mismatch_never_signals_either_process(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            child, sentinel, monitor, _, _ = self.guarded_cpu_child(root, identity_change=True)
            monitor.join(timeout=2)
            self.assertEqual(monitor.exitcode, 0)
            self.assertIsNone(child.poll())
            self.assertIsNone(sentinel.poll())
            self.assertEqual(json.loads((root / "watchdog.jsonl").read_text())["event"], "binding_rejected")

    def test_probe_hang_stops_bound_child_with_deadline(self):
        def hung_probe():
            time.sleep(10)
            return [gpu()]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            child, sentinel, monitor, _, _ = self.guarded_cpu_child(root, inventory_probe=hung_probe)
            self.assertEqual(child.wait(timeout=3), -15)
            monitor.join(timeout=2)
            self.assertIsNone(sentinel.poll())
            self.assertIn("telemetry_deadline_exceeded", json.loads((root / "watchdog.jsonl").read_text())["reasons"])

    def test_sustained_io_requires_three_samples(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            child, sentinel, monitor, _, _ = self.guarded_cpu_child(root, inventory_probe=lambda: [gpu()], resource_probe=lambda: resources(80, ["iowait_above_threshold"]))
            self.assertEqual(child.wait(timeout=5), -15)
            monitor.join(timeout=2)
            self.assertIsNone(sentinel.poll())
            records = [json.loads(line) for line in (root / "watchdog.jsonl").read_text().splitlines()]
            self.assertEqual([row["io_streak"] for row in records], [1, 2, 3])
            self.assertEqual(records[-1]["reasons"], ["sustained_io_pressure"])

    def test_normal_memory_loading_below_startup_gate_does_not_stop(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            child, sentinel, monitor, stop, ready = self.guarded_cpu_child(root, inventory_probe=lambda: [gpu(free=5)], resource_probe=lambda: resources(80))
            self.assertTrue(ready.wait(2))
            time.sleep(0.15)
            stop.set()
            monitor.join(timeout=2)
            self.assertEqual(monitor.exitcode, 0)
            self.assertIsNone(child.poll())
            self.assertIsNone(sentinel.poll())
            self.assertEqual(json.loads((root / "watchdog.jsonl").read_text())["reasons"], [])

    def test_runtime_is_bounded_even_without_pressure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            child, sentinel, monitor, _, _ = self.guarded_cpu_child(root, inventory_probe=lambda: [gpu()], max_runtime=0.1)
            self.assertEqual(child.wait(timeout=3), -15)
            monitor.join(timeout=2)
            self.assertIsNone(sentinel.poll())
            records = [json.loads(line) for line in (root / "watchdog.jsonl").read_text().splitlines()]
            self.assertEqual(records[-1]["reasons"], ["bounded_runtime_exhausted"])


if __name__ == "__main__":
    unittest.main()
