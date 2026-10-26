"""Controller-neutral high-level action and dual-layer episode contract.

The policy-visible stream and privileged audit stream are physically separate.
Reading privileged records requires a distinct explicit call; the default
reader can never return them by accident.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .audit_candidates import write_json_atomic


TASK_PHASES = (
    "approach",
    "align",
    "grasp",
    "lift",
    "carry",
    "stop",
    "place",
    "release",
    "retreat",
)

FORBIDDEN_POLICY_KEYS = {
    "contacts",
    "contact_forces",
    "object_world_pose",
    "privileged",
    "sim_state",
    "true_friction",
    "world_state",
}


def _finite(values: Iterable[float]) -> bool:
    return all(math.isfinite(float(value)) for value in values)


@dataclass(frozen=True)
class TaskInstruction:
    task_type: str
    target_object_semantic_id: str
    target_support_semantic_id: str
    target_region_semantic_id: str
    natural_language: str

    def validate(self) -> None:
        for name, value in asdict(self).items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"instruction field {name} must be a non-empty string")


@dataclass(frozen=True)
class HybridAction:
    phase: str
    issued_at_s: float
    valid_for_s: float
    frame_id: str
    base_pose_xyyaw: tuple[float, float, float] | None = None
    base_velocity_xyyaw: tuple[float, float, float] | None = None
    body_height_m: float | None = None
    end_effector_position_m: tuple[float, float, float] | None = None
    end_effector_quaternion_wxyz: tuple[float, float, float, float] | None = None
    gripper_target: float | None = None
    controller_metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if self.phase not in TASK_PHASES:
            raise ValueError(f"unknown task phase: {self.phase}")
        if not math.isfinite(self.issued_at_s) or self.issued_at_s < 0:
            raise ValueError("issued_at_s must be finite and non-negative")
        if not math.isfinite(self.valid_for_s) or not 0 < self.valid_for_s <= 60:
            raise ValueError("valid_for_s must be in (0, 60]")
        if self.frame_id not in {"world", "base", "pelvis", "end_effector"}:
            raise ValueError(f"unsupported frame: {self.frame_id}")
        if self.base_pose_xyyaw is not None:
            if len(self.base_pose_xyyaw) != 3 or not _finite(self.base_pose_xyyaw):
                raise ValueError("base pose must be a finite x/y/yaw triple")
            if max(abs(self.base_pose_xyyaw[0]), abs(self.base_pose_xyyaw[1])) > 5:
                raise ValueError("base pose exceeds the first-task workspace")
            if abs(self.base_pose_xyyaw[2]) > math.pi + 1e-9:
                raise ValueError("base yaw must be wrapped to [-pi, pi]")
        if self.base_velocity_xyyaw is not None:
            if len(self.base_velocity_xyyaw) != 3 or not _finite(self.base_velocity_xyyaw):
                raise ValueError("base velocity must be a finite vx/vy/wz triple")
            if any(abs(value) > limit for value, limit in zip(self.base_velocity_xyyaw, (1, 1, 2))):
                raise ValueError("base velocity exceeds the neutral safety envelope")
        if self.body_height_m is not None and not 0.45 <= self.body_height_m <= 0.90:
            raise ValueError("body height exceeds the neutral safety envelope")
        if self.end_effector_position_m is not None:
            if len(self.end_effector_position_m) != 3 or not _finite(
                self.end_effector_position_m
            ):
                raise ValueError("end-effector position must be a finite xyz triple")
        if self.end_effector_quaternion_wxyz is not None:
            quat = self.end_effector_quaternion_wxyz
            if len(quat) != 4 or not _finite(quat):
                raise ValueError("end-effector quaternion must be finite wxyz")
            if abs(math.sqrt(sum(value * value for value in quat)) - 1.0) > 1e-3:
                raise ValueError("end-effector quaternion must be normalized")
        if self.gripper_target is not None and not 0 <= self.gripper_target <= 1.2:
            raise ValueError("gripper target exceeds the neutral safety envelope")
        if all(
            value is None
            for value in (
                self.base_pose_xyyaw,
                self.base_velocity_xyyaw,
                self.body_height_m,
                self.end_effector_position_m,
                self.gripper_target,
            )
        ):
            raise ValueError("hybrid action has no continuous target")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)


def _contains_forbidden_key(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in FORBIDDEN_POLICY_KEYS:
                found.add(key)
            found.update(_contains_forbidden_key(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            found.update(_contains_forbidden_key(item))
    return found


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class DualLayerEpisodeWriter:
    """Write matched policy/privileged records and an integrity manifest."""

    def __init__(self, output_dir: Path, header: dict[str, Any]):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=False)
        self.header = dict(header)
        self.policy_records: list[dict[str, Any]] = []
        self.privileged_records: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []

    def append_decision(
        self,
        instruction: TaskInstruction,
        action: HybridAction,
        policy_observation: dict[str, Any],
        privileged_audit: dict[str, Any],
    ) -> None:
        instruction.validate()
        action_dict = action.to_dict()
        forbidden = _contains_forbidden_key(policy_observation)
        if forbidden:
            raise ValueError(f"privileged keys in policy observation: {sorted(forbidden)}")
        index = len(self.policy_records)
        common = {
            "decision_index": index,
            "sim_time_s": action.issued_at_s,
            "phase": action.phase,
        }
        self.policy_records.append(
            {
                **common,
                "instruction": asdict(instruction),
                "observation": policy_observation,
                "action": action_dict,
            }
        )
        self.privileged_records.append({**common, "audit": privileged_audit})

    def append_event(self, sim_time_s: float, event: str, details: dict[str, Any]) -> None:
        if not math.isfinite(sim_time_s) or sim_time_s < 0:
            raise ValueError("event time must be finite and non-negative")
        self.events.append({"sim_time_s": sim_time_s, "event": event, "details": details})

    @staticmethod
    def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
        text = "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows)
        path.write_text(text, encoding="utf-8")

    def finalize(self) -> dict[str, Any]:
        if len(self.policy_records) != len(self.privileged_records):
            raise RuntimeError("policy/privileged decision counts diverged")
        policy_path = self.output_dir / "policy.jsonl"
        privileged_path = self.output_dir / "privileged.jsonl"
        event_path = self.output_dir / "events.jsonl"
        self._write_jsonl(policy_path, self.policy_records)
        self._write_jsonl(privileged_path, self.privileged_records)
        self._write_jsonl(event_path, self.events)
        manifest = {
            "schema": "embodied-neutral-episode/v1",
            **self.header,
            "policy_visible_default": True,
            "privileged_requires_explicit_reader": True,
            "record_counts": {
                "policy": len(self.policy_records),
                "privileged": len(self.privileged_records),
                "events": len(self.events),
            },
            "files": {
                name: {
                    "relative_path": path.name,
                    "size_bytes": path.stat().st_size,
                    "sha256": _sha256(path),
                }
                for name, path in (
                    ("policy", policy_path),
                    ("privileged", privileged_path),
                    ("events", event_path),
                )
            },
        }
        write_json_atomic(self.output_dir / "MANIFEST.json", manifest)
        return manifest


def _read_bound_rows(contract_dir: Path, stream: str) -> list[dict[str, Any]]:
    manifest = json.loads((contract_dir / "MANIFEST.json").read_text(encoding="utf-8"))
    record = manifest["files"][stream]
    path = contract_dir / record["relative_path"]
    if _sha256(path) != record["sha256"]:
        raise RuntimeError(f"{stream} stream hash mismatch")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def read_policy_episode(contract_dir: Path) -> list[dict[str, Any]]:
    return _read_bound_rows(contract_dir, "policy")


def read_privileged_episode(contract_dir: Path, *, explicit: bool = False) -> list[dict[str, Any]]:
    if not explicit:
        raise PermissionError("privileged episode reads require explicit=True")
    return _read_bound_rows(contract_dir, "privileged")


class SourceANativeParityAdapter:
    """Expose Source A's native stance seam through the neutral action contract."""

    direct = False

    def __init__(
        self,
        writer: DualLayerEpisodeWriter,
        instruction: TaskInstruction,
        pick_stance: tuple[Iterable[float], float],
        place_stance: tuple[Iterable[float], float],
        time_provider: Any | None = None,
    ):
        self.writer = writer
        self.instruction = instruction
        self.native_pick = (tuple(float(v) for v in pick_stance[0]), float(pick_stance[1]))
        self.native_place = (tuple(float(v) for v in place_stance[0]), float(place_stance[1]))
        self.time_provider = time_provider

    @staticmethod
    def _ctx_audit(ctx: dict[str, Any]) -> dict[str, Any]:
        def plain(value: Any) -> Any:
            if isinstance(value, dict):
                return {str(key): plain(item) for key, item in value.items()}
            if isinstance(value, (list, tuple)):
                return [plain(item) for item in value]
            if hasattr(value, "tolist"):
                return plain(value.tolist())
            if hasattr(value, "item"):
                return plain(value.item())
            return value

        return plain(ctx)

    def _emit(self, phase: str, ctx: dict[str, Any], target: tuple[tuple[float, float], float]) -> None:
        xy, yaw = target
        issued_at_s = float(self.time_provider()) if self.time_provider is not None else 0.0
        action = HybridAction(
            phase=phase,
            issued_at_s=issued_at_s,
            valid_for_s=60.0,
            frame_id="world",
            base_pose_xyyaw=(xy[0], xy[1], yaw),
            controller_metadata={"adapter": "source_a_native_parity", "consumed": True},
        )
        self.writer.append_decision(
            self.instruction,
            action,
            policy_observation={
                "task_stage": phase,
                "previous_action_available": bool(self.writer.policy_records),
                "head_rgbd": "not_recorded_s2_component_smoke",
                "proprioception": "consumed_by_native_controller_not_duplicated_here",
            },
            privileged_audit={"source_a_command_context": self._ctx_audit(ctx)},
        )

    def pick_stance(self, ctx: dict[str, Any]):
        self._emit("approach", ctx, self.native_pick)
        return self.native_pick

    def place_stance(self, ctx: dict[str, Any]):
        self._emit("carry", ctx, self.native_place)
        return self.native_place
