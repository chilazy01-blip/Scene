"""Compact policy/privileged state capture for bounded S3 smoke episodes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from .audit_candidates import write_json_atomic


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class StateStreamCapture:
    """Sample state without changing controller timing or simulator state."""

    def __init__(self, sample_every_steps: int, action_index: Callable[[], int]):
        if sample_every_steps <= 0:
            raise ValueError("sample_every_steps must be positive")
        self.sample_every_steps = sample_every_steps
        self.action_index = action_index
        self.policy: dict[str, list[Any]] = {
            key: []
            for key in (
                "physics_step",
                "sim_time_s",
                "joint_position",
                "joint_velocity",
                "base_quaternion_wxyz",
                "base_velocity",
                "previous_high_level_action_index",
            )
        }
        self.privileged: dict[str, list[Any]] = {
            key: []
            for key in (
                "physics_step",
                "sim_time_s",
                "qpos",
                "qvel",
                "ctrl",
                "object_position",
                "object_quaternion_wxyz",
                "contact_count",
                "max_contact_force_n",
                "min_contact_distance_m",
            )
        }
        self.model_signature: dict[str, Any] | None = None
        self.object_body_id: int | None = None

    def on_step(self, model: Any, data: Any, step: int, mujoco: Any) -> None:
        if step % self.sample_every_steps:
            return
        import numpy as np

        if self.model_signature is None:
            self.model_signature = {
                "nq": int(model.nq),
                "nv": int(model.nv),
                "nu": int(model.nu),
                "dt": float(model.opt.timestep),
                "robot_joint_count": 43,
            }
            for name in ("red_block", "red_cylinder"):
                body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, name)
                if body_id >= 0:
                    self.object_body_id = int(body_id)
                    break
            if self.object_body_id is None:
                raise RuntimeError("task object body not found")

        force_max = 0.0
        min_distance = float("inf")
        for index, contact in enumerate(data.contact):
            force = np.zeros(6)
            mujoco.mj_contactForce(model, data, index, force)
            force_max = max(force_max, float(np.linalg.norm(force[:3])))
            min_distance = min(min_distance, float(contact.dist))
        if not data.ncon:
            min_distance = 0.0

        robot_joint_count = self.model_signature["robot_joint_count"]
        self.policy["physics_step"].append(step)
        self.policy["sim_time_s"].append(float(data.time))
        self.policy["joint_position"].append(data.qpos[7 : 7 + robot_joint_count].copy())
        self.policy["joint_velocity"].append(data.qvel[6 : 6 + robot_joint_count].copy())
        self.policy["base_quaternion_wxyz"].append(data.qpos[3:7].copy())
        self.policy["base_velocity"].append(data.qvel[:6].copy())
        self.policy["previous_high_level_action_index"].append(self.action_index())

        object_id = self.object_body_id
        self.privileged["physics_step"].append(step)
        self.privileged["sim_time_s"].append(float(data.time))
        self.privileged["qpos"].append(data.qpos.copy())
        self.privileged["qvel"].append(data.qvel.copy())
        self.privileged["ctrl"].append(data.ctrl.copy())
        self.privileged["object_position"].append(data.xpos[object_id].copy())
        self.privileged["object_quaternion_wxyz"].append(data.xquat[object_id].copy())
        self.privileged["contact_count"].append(int(data.ncon))
        self.privileged["max_contact_force_n"].append(force_max)
        self.privileged["min_contact_distance_m"].append(min_distance)

    @staticmethod
    def _array_manifest(np: Any, arrays: dict[str, list[Any]]) -> dict[str, Any]:
        return {
            key: {"shape": list(np.asarray(value).shape), "dtype": str(np.asarray(value).dtype)}
            for key, value in arrays.items()
        }

    def finalize(self, output_dir: Path) -> dict[str, Any]:
        import numpy as np

        if not self.policy["sim_time_s"]:
            raise RuntimeError("state stream has no samples")
        output_dir.mkdir(parents=True, exist_ok=False)
        policy_path = output_dir / "policy_state.npz"
        privileged_path = output_dir / "privileged_state.npz"
        np.savez_compressed(policy_path, **{key: np.asarray(value) for key, value in self.policy.items()})
        np.savez_compressed(
            privileged_path,
            **{key: np.asarray(value) for key, value in self.privileged.items()},
        )
        manifest = {
            "schema": "embodied-state-stream/v1",
            "sample_every_physics_steps": self.sample_every_steps,
            "sample_count": len(self.policy["sim_time_s"]),
            "model": self.model_signature,
            "head_rgbd_status": "not_recorded_s3_bounded_smoke",
            "wrist_rgbd_status": "not_recorded_s3_bounded_smoke",
            "policy_visible_default": True,
            "privileged_requires_explicit_reader": True,
            "streams": {
                "policy": {
                    "relative_path": policy_path.name,
                    "sha256": sha256_file(policy_path),
                    "size_bytes": policy_path.stat().st_size,
                    "arrays": self._array_manifest(np, self.policy),
                },
                "privileged": {
                    "relative_path": privileged_path.name,
                    "sha256": sha256_file(privileged_path),
                    "size_bytes": privileged_path.stat().st_size,
                    "arrays": self._array_manifest(np, self.privileged),
                },
            },
        }
        write_json_atomic(output_dir / "MANIFEST.json", manifest)
        return manifest


def _load_stream(output_dir: Path, stream: str, explicit: bool) -> dict[str, Any]:
    if stream == "privileged" and not explicit:
        raise PermissionError("privileged state reads require explicit=True")
    import numpy as np

    manifest = json.loads((output_dir / "MANIFEST.json").read_text(encoding="utf-8"))
    record = manifest["streams"][stream]
    path = output_dir / record["relative_path"]
    if sha256_file(path) != record["sha256"]:
        raise RuntimeError(f"{stream} state stream hash mismatch")
    with np.load(path, allow_pickle=False) as archive:
        return {name: archive[name] for name in archive.files}


def load_policy_state(output_dir: Path) -> dict[str, Any]:
    return _load_stream(output_dir, "policy", explicit=True)


def load_privileged_state(output_dir: Path, *, explicit: bool = False) -> dict[str, Any]:
    return _load_stream(output_dir, "privileged", explicit=explicit)


class SourceAPhaseTrace:
    """Observe Source A's state/contact-driven milestones without controlling it."""

    REPORT_PHASE = {
        "closed": "grasp",
        "lifted": "lift",
        "cradled": "carry",
        "arrived": "stop",
        "pre-place": "place",
        "thumb open": "release",
        "retracted": "retreat",
    }
    SNAP_PHASE = {"V2_ready": "align"}

    def __init__(self):
        self.events: list[dict[str, Any]] = []
        self._seen: set[str] = set()
        self._original_report: Any | None = None
        self._original_snap: Any | None = None

    def _record(self, runner: Any, phase: str, source_event: str) -> None:
        if phase in self._seen:
            return
        self._seen.add(phase)
        self.events.append(
            {
                "phase": phase,
                "sim_time_s": float(runner.data.time),
                "source_event": source_event,
                "pelvis_z_m": float(runner.data.qpos[2]),
                "object_position": [float(value) for value in runner.cyl_pos()],
                "finger_contacts": int(runner.finger_contacts()),
            }
        )

    def install(self, pipeline: Any) -> None:
        trace = self
        cls = pipeline.HybridRunner
        self._original_report = cls.report
        self._original_snap = cls.snap

        def report(runner: Any, tag: str, *args: Any, **kwargs: Any):
            phase = trace.REPORT_PHASE.get(tag)
            if phase:
                trace._record(runner, phase, f"report:{tag}")
            return trace._original_report(runner, tag, *args, **kwargs)

        def snap(runner: Any, name: str, *args: Any, **kwargs: Any):
            phase = trace.SNAP_PHASE.get(name)
            if phase:
                trace._record(runner, phase, f"snap:{name}")
            return trace._original_snap(runner, name, *args, **kwargs)

        cls.report = report
        cls.snap = snap

    def restore(self, pipeline: Any) -> None:
        cls = pipeline.HybridRunner
        if self._original_report is not None:
            cls.report = self._original_report
        if self._original_snap is not None:
            cls.snap = self._original_snap

    def with_approach(self, policy_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        approach = next(row for row in policy_records if row["phase"] == "approach")
        event = {
            "phase": "approach",
            "sim_time_s": float(approach["sim_time_s"]),
            "source_event": "neutral_action:approach",
        }
        return sorted([event, *self.events], key=lambda row: row["sim_time_s"])
