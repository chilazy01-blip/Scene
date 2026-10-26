"""Pinned local helpers for a portable v0 runtime.
Source: embodied_task_interface/contracts.py
Source SHA256: 85887626f622354a178d501c9aa29e05f4f6d5a1a3dfb0eb5157198b8bd3a977
"""
from pathlib import Path
import hashlib
import json


def binding(path):
    path = Path(path)
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    return dict(path=str(path.absolute()), bytes=path.stat().st_size, sha256=sha.hexdigest())


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def outcome(config, metrics, *, stopped, reason, engineering):
    """The v2 success inequalities, with separate lifecycle/error labels.

    engineering=None means that the full restoration checks are not available.
    A policy failure is evidence about that policy, not proof of infeasibility.
    """
    if engineering is False:
        return dict(status="infrastructure_error", success=False, terminated=False,
                    truncated=True, reason=reason)
    if not stopped or engineering is None:
        return dict(status="unvalidated", success=None, terminated=False,
                    truncated=bool(stopped), reason=reason)
    a, v = config["acceptance"], metrics
    success = (v["goal_xy_error_m"] < a["goal_xy_tolerance_m"]
               and v["stable_seconds"] + 1e-8 >= a["stable_seconds"]
               and not v["forbidden_contact_steps"]
               and v["max_robot_scene_penetration_m"] < a["max_robot_scene_penetration_m"])
    if config["task"] == "pick_place":
        success = (success and v["max_lift_m"] >= a["min_lift_m"]
                   and v["bilateral_seconds"] > a["min_bilateral_seconds"]
                   and v["target_floor_contact_steps"] == 0)
    status = "success" if success else ("timeout" if reason == "time_limit" else "task_failure")
    return dict(status=status, success=bool(success), terminated=status != "timeout",
                truncated=status == "timeout", reason=reason)
