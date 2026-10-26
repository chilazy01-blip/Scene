"""Fail-closed, non-actuating bridge for a future SONIC shadow controller.

This module deliberately has no simulator or actuator dependency.  It can
validate the Source-A/SONIC body-joint seam, inspect locally staged SONIC
resources, and compare two already post-processed joint-position targets.  It
cannot write a command into MuJoCo.  A future runner may call this module next
to Source A, but Source A remains the only controller consumed by physics.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from .audit_candidates import write_json_atomic


SONIC_BODY_JOINT_ORDER = (
    "left_hip_pitch_joint",
    "left_hip_roll_joint",
    "left_hip_yaw_joint",
    "left_knee_joint",
    "left_ankle_pitch_joint",
    "left_ankle_roll_joint",
    "right_hip_pitch_joint",
    "right_hip_roll_joint",
    "right_hip_yaw_joint",
    "right_knee_joint",
    "right_ankle_pitch_joint",
    "right_ankle_roll_joint",
    "waist_yaw_joint",
    "waist_roll_joint",
    "waist_pitch_joint",
    "left_shoulder_pitch_joint",
    "left_shoulder_roll_joint",
    "left_shoulder_yaw_joint",
    "left_elbow_joint",
    "left_wrist_roll_joint",
    "left_wrist_pitch_joint",
    "left_wrist_yaw_joint",
    "right_shoulder_pitch_joint",
    "right_shoulder_roll_joint",
    "right_shoulder_yaw_joint",
    "right_elbow_joint",
    "right_wrist_roll_joint",
    "right_wrist_pitch_joint",
    "right_wrist_yaw_joint",
)

SONIC_ACTION_DIM = len(SONIC_BODY_JOINT_ORDER)


def _finite_tuple(values: Iterable[float], expected: int, label: str) -> tuple[float, ...]:
    result = tuple(float(value) for value in values)
    if len(result) != expected:
        raise ValueError(f"{label} must contain {expected} values, got {len(result)}")
    if not all(math.isfinite(value) for value in result):
        raise ValueError(f"{label} must contain only finite values")
    return result


def _validate_joint_order(order: Sequence[str], label: str) -> tuple[str, ...]:
    result = tuple(order)
    if len(result) != SONIC_ACTION_DIM:
        raise ValueError(
            f"{label} must contain {SONIC_ACTION_DIM} joints, got {len(result)}"
        )
    if any(not isinstance(name, str) or not name for name in result):
        raise ValueError(f"{label} contains an invalid joint name")
    if len(set(result)) != len(result):
        raise ValueError(f"{label} contains duplicate joint names")
    missing = sorted(set(SONIC_BODY_JOINT_ORDER) - set(result))
    extra = sorted(set(result) - set(SONIC_BODY_JOINT_ORDER))
    if missing or extra:
        raise ValueError(f"{label} is incompatible; missing={missing}, extra={extra}")
    return result


@dataclass(frozen=True)
class BodyJointTarget:
    """One controller's post-processed 29-joint position target.

    SONIC's raw normalized action is intentionally not accepted here.  The
    official SONIC action scale and default angle must be applied first so the
    comparison with Source A is in the common unit, radians.
    """

    controller_id: str
    phase: str
    sim_time_s: float
    joint_order: tuple[str, ...]
    position_target_rad: tuple[float, ...]

    def validated(self) -> "BodyJointTarget":
        if not self.controller_id.strip():
            raise ValueError("controller_id must be non-empty")
        if not self.phase.strip():
            raise ValueError("phase must be non-empty")
        if not math.isfinite(self.sim_time_s) or self.sim_time_s < 0:
            raise ValueError("sim_time_s must be finite and non-negative")
        order = _validate_joint_order(self.joint_order, "joint_order")
        target = _finite_tuple(
            self.position_target_rad,
            SONIC_ACTION_DIM,
            "position_target_rad",
        )
        if order != self.joint_order or target != self.position_target_rad:
            return BodyJointTarget(
                controller_id=self.controller_id,
                phase=self.phase,
                sim_time_s=float(self.sim_time_s),
                joint_order=order,
                position_target_rad=target,
            )
        return self

    def ordered(self, target_order: Sequence[str]) -> tuple[float, ...]:
        checked = self.validated()
        target_order = _validate_joint_order(target_order, "target_order")
        by_name = dict(zip(checked.joint_order, checked.position_target_rad))
        return tuple(by_name[name] for name in target_order)


class SonicShadowBridge:
    """Compare SONIC candidates without exposing an actuation method."""

    mode = "shadow_only"
    actuation_enabled = False
    candidate_consumed_by_physics = False

    def __init__(self, source_a_body_joint_order: Sequence[str]):
        self.source_a_body_joint_order = _validate_joint_order(
            source_a_body_joint_order,
            "source_a_body_joint_order",
        )

    def compare(
        self,
        source_a: BodyJointTarget,
        sonic: BodyJointTarget,
        *,
        max_time_skew_s: float = 1e-6,
    ) -> dict[str, Any]:
        """Return a same-tick command comparison; never apply either target."""

        source_a = source_a.validated()
        sonic = sonic.validated()
        if source_a.phase != sonic.phase:
            raise ValueError("Source A and SONIC phases differ")
        time_skew_s = abs(source_a.sim_time_s - sonic.sim_time_s)
        if time_skew_s > max_time_skew_s:
            raise ValueError(
                f"Source A and SONIC samples are not synchronous: {time_skew_s}s"
            )
        source_target = source_a.ordered(self.source_a_body_joint_order)
        sonic_target = sonic.ordered(self.source_a_body_joint_order)
        delta = tuple(s - a for a, s in zip(source_target, sonic_target))
        abs_delta = tuple(abs(value) for value in delta)
        rms = math.sqrt(sum(value * value for value in delta) / len(delta))
        return {
            "schema": "sonic-shadow-comparison/v1",
            "mode": self.mode,
            "phase": source_a.phase,
            "sim_time_s": source_a.sim_time_s,
            "time_skew_s": time_skew_s,
            "physics_controller": source_a.controller_id,
            "shadow_controller": sonic.controller_id,
            "candidate_consumed_by_physics": False,
            "actuation_enabled": False,
            "joint_order": list(self.source_a_body_joint_order),
            "units": "rad_position_target",
            "source_a_target_rad": list(source_target),
            "sonic_target_rad": list(sonic_target),
            "sonic_minus_source_a_rad": list(delta),
            "metrics": {
                "max_abs_target_delta_rad": max(abs_delta),
                "mean_abs_target_delta_rad": sum(abs_delta) / len(abs_delta),
                "rms_target_delta_rad": rms,
            },
        }

    @staticmethod
    def unavailable_record(
        *,
        phase: str,
        sim_time_s: float,
        blockers: Sequence[str],
    ) -> dict[str, Any]:
        if not phase.strip():
            raise ValueError("phase must be non-empty")
        if not math.isfinite(sim_time_s) or sim_time_s < 0:
            raise ValueError("sim_time_s must be finite and non-negative")
        if not blockers:
            raise ValueError("an unavailable record requires at least one blocker")
        return {
            "schema": "sonic-shadow-comparison/v1",
            "mode": "shadow_only",
            "phase": phase,
            "sim_time_s": float(sim_time_s),
            "status": "candidate_unavailable",
            "blockers": [str(item) for item in blockers],
            "candidate_consumed_by_physics": False,
            "actuation_enabled": False,
        }


def _resource_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path), "state": "absent", "size_bytes": 0}
    size = path.stat().st_size
    prefix = path.read_bytes()[:256]
    if prefix.startswith(b"version https://git-lfs.github.com/spec/v1"):
        state = "git_lfs_pointer"
    elif size == 0:
        state = "empty"
    else:
        state = "ready"
    return {"path": str(path), "state": state, "size_bytes": size}


def inspect_sonic_resources(sonic_source_root: Path) -> dict[str, Any]:
    """Inspect the v1.1 deployment slice without importing or running it."""

    deploy = sonic_source_root / "gear_sonic_deploy"
    resources = {
        "encoder": _resource_state(
            deploy / "policy" / "sonic_v1_1" / "model_encoder.onnx"
        ),
        "decoder": _resource_state(
            deploy / "policy" / "sonic_v1_1" / "model_decoder.onnx"
        ),
        "observation_config": _resource_state(
            deploy / "policy" / "sonic_v1_1" / "observation_config.yaml"
        ),
        "planner": _resource_state(deploy / "policy" / "planner_sonic.onnx"),
        "deploy_entrypoint": _resource_state(deploy / "deploy.sh"),
    }
    inference_required = ("encoder", "decoder", "observation_config")
    shadow_inference_ready = all(
        resources[name]["state"] == "ready" for name in inference_required
    )
    blockers = [
        f"{name}:{resources[name]['state']}"
        for name in inference_required
        if resources[name]["state"] != "ready"
    ]
    if resources["planner"]["state"] != "ready":
        blockers.append(f"planner:{resources['planner']['state']}")
    return {
        "schema": "sonic-shadow-resource-inspection/v1",
        "selected_variant": "sonic_v1_1",
        "resources": resources,
        "shadow_inference_ready": shadow_inference_ready,
        "planner_ready": resources["planner"]["state"] == "ready",
        "blockers": blockers,
        "imports": 0,
        "model_forwards": 0,
        "physics_steps": 0,
    }


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_sonic_shadow_preflight(
    *,
    sonic_source_root: Path,
    sonic_contract_path: Path,
    source_a_contract_path: Path,
) -> dict[str, Any]:
    """Bind the frozen contracts to the dormant shadow seam."""

    sonic_contract = _load_json(sonic_contract_path)
    source_a_contract = _load_json(source_a_contract_path)
    sonic_order = tuple(
        sonic_contract["robot"]["joint_and_actuator_order"]["mjcf_actuator_order"]
    )
    source_a_order = tuple(
        source_a_contract["action"]["fields_order_units_bounds"]["order"]
    )
    _validate_joint_order(sonic_order, "sonic_contract_joint_order")
    bridge = SonicShadowBridge(source_a_order)
    resources = inspect_sonic_resources(sonic_source_root)
    order_exact_match = sonic_order == source_a_order
    return {
        "schema": "sonic-shadow-preflight/v1",
        "mode": bridge.mode,
        "selected_variant": "sonic_v1_1",
        "source_a_controller": source_a_contract["identity"],
        "sonic_controller": sonic_contract["identity"],
        "joint_mapping": {
            "ready": True,
            "count": SONIC_ACTION_DIM,
            "exact_order_match": order_exact_match,
            "source_a_order": list(source_a_order),
            "sonic_order": list(sonic_order),
        },
        "resource_inspection": resources,
        "dormant_adapter_ready": True,
        "shadow_inference_ready": resources["shadow_inference_ready"],
        "actuation_enabled": False,
        "candidate_consumed_by_physics": False,
        "source_a_execution_unchanged": True,
        "model_forwards": 0,
        "physics_steps": 0,
        "quality_boundary": (
            "This preflight proves only a non-actuating 29-joint interface and "
            "local resource status. It is not SONIC inference, physics, an A/B "
            "episode, or evidence that SONIC outperforms Source A."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sonic-source-root", type=Path, required=True)
    parser.add_argument("--sonic-contract", type=Path, required=True)
    parser.add_argument("--source-a-contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_sonic_shadow_preflight(
        sonic_source_root=args.sonic_source_root,
        sonic_contract_path=args.sonic_contract,
        source_a_contract_path=args.source_a_contract,
    )
    write_json_atomic(args.output, report)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
