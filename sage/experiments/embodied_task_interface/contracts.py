"""Serializable contracts; simulator truth lives outside policy observations."""
from dataclasses import asdict, dataclass
from pathlib import Path
import hashlib
import json
import math

from . import SCHEMA


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


def audit_json(value):
    """Nonfinite failure evidence remains in NPZ; JSON uses explicit nulls."""
    if isinstance(value, dict):
        return {key: audit_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [audit_json(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


class Contract:
    def to_dict(self):
        return dict(schema=SCHEMA, kind=type(self).__name__, **asdict(self))


@dataclass(frozen=True)
class SceneManifest(Contract):
    source_episode: str
    bindings: dict
    source_package: dict
    coordinate_frame: str
    units: dict
    layout_id: str
    physics_semantics_sha256: str
    material_provenance: dict
    verification_scope: str


@dataclass(frozen=True)
class TaskSpec(Contract):
    task: str
    robot: str
    config: dict
    criterion_version: str
    evaluator_binding: dict
    physics_dt_s: float
    control_dt_s: float
    native_state_record_dt_s: float
    effective_step_limit: int
    goal_relation: str
    source_split: str
    usage_split: str = "development_compatibility"


@dataclass(frozen=True)
class ObservationSpec(Contract):
    profile: str
    fields: dict
    qpos_indices: list
    qvel_indices: list
    goal_information_allowed: bool
    privileged_state: bool
    cameras: list
    timestamp_semantics: str


@dataclass(frozen=True)
class ActionSpec(Contract):
    mode: str
    actuator_names: list
    shape: list
    control_interval_s: float
    physics_steps_per_action: int
    ctrl_limited: list
    ctrl_range: list
    actuator_semantics: dict
    units: str
    invalid_action_policy: str = "reject before physics; never clip silently"


@dataclass(frozen=True)
class EpisodeRecord(Contract):
    source_type: str
    scene_identity: str
    task_identity: str
    observation_identity: str
    action_identity: str
    policy: str
    seed: int
    random_state: dict
    steps: int
    observations: int
    outcome: dict
    data: dict
    reward: str = "not defined; no reward shaping or inferred labels"


@dataclass(frozen=True)
class AuditRecord(Contract):
    files: dict
    code: dict
    simulator: str
    metrics: dict
    restoration: dict
    resource_evidence: str | None
    exceptions: list
    contact_semantics: str = "native v2 1 kHz contacts: solver time t-dt, integration state time t"


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
