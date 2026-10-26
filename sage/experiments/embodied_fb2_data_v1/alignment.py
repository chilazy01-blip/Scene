"""Align actual native sensor samples and future position-command chunks.

No successful sample is manufactured here. Admission requires a completed
physical task and its independent audit before any public arrays are returned.
"""
from pathlib import Path
import hashlib
import json

import numpy as np


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def accepted_chunks(trial, mapping, stride=2):
    trial = Path(trial)
    read = lambda name: json.loads((trial / name).read_text())
    result, audit = read("RESULT.json"), read("INDEPENDENT_AUDIT_R1.json")
    if not result["passed"] or result["mode"] != "full":
        raise ValueError("complete_physical_task_required")
    if not audit["passed"] or not audit["full_task_passed"]:
        raise ValueError("independent_full_task_acceptance_required")
    if result["initial_state_restorations"] != 1 or result["mid_episode_state_writes"]:
        raise ValueError("continuous_actual_episode_required")
    if sha(trial / "TRACE.npz") != audit["input_sha256"]:
        raise ValueError("physical_trace_hash_mismatch")
    assert stride == 2
    trace = np.load(trial / "TRACE.npz")
    public = read("PUBLIC_OBSERVATIONS.json")
    commands = trace["joint_commands"]
    count = len(commands)
    assert count == result["actions"] == result["dynamic_forwards"] == len(public)
    assert commands.shape == (count, 43) and count <= 2600
    assert len(trace["before"]) == count * 4 == result["physics_steps"]
    assert np.array_equal(trace["command_index"], np.repeat(np.arange(count), 4))
    assert np.array_equal(trace["before"][1:], trace["after"][:-1])
    command_times = trace["before"][::4, 0]
    assert np.allclose(np.diff(command_times), .02, rtol=0, atol=1e-11)
    for i, row in enumerate(public):
        sensor = trace["before"][max(0, 4*i - 1)]
        assert row["command_index"] == i
        assert row["command_time"] == command_times[i]
        assert row["sensor_time"] == sensor[0]
        q = sensor[1 + mapping].astype(np.float32).astype(np.float64)
        dq = sensor[58 + mapping - 1].astype(np.float32).astype(np.float64)
        assert np.array_equal(row["q"], q) and np.array_equal(row["dq"], dq)
        assert np.array_equal(row["previous_action"], np.zeros(43) if i == 0 else commands[i-1])
    starts = np.arange(0, count, stride)
    indices = starts[:, None] + np.arange(stride)[None, :]
    valid = indices < count
    bounded = np.minimum(indices, count-1)
    fields = {
        "timestamp": np.asarray([public[i]["sensor_time"] for i in starts], np.float64),
        "command_timestamp": command_times[starts],
        "joint_position": np.asarray([public[i]["q"] for i in starts], np.float64),
        "joint_velocity": np.asarray([public[i]["dq"] for i in starts], np.float64),
        "previous_command": np.asarray([public[i]["previous_action"] for i in starts], np.float64),
        "action_chunk": commands[bounded],
        "action_timestamps": command_times[bounded],
        "action_valid": valid,
        "done": np.arange(len(starts)) == len(starts)-1,
    }
    assert int(valid.sum()) == count
    assert np.array_equal(fields["action_chunk"][valid], commands)
    sensor_indices = np.maximum(0, 4*starts - 1)
    sensor_states = trace["before"][sensor_indices].copy()
    assert np.array_equal(sensor_states[:, 0], fields["timestamp"])
    binding = {name: sha(trial/name) for name in (
        "TRACE.npz", "RESULT.json", "INDEPENDENT_AUDIT_R1.json",
        "MODEL.mjb", "PUBLIC_OBSERVATIONS.json")}
    return fields, sensor_states, binding
