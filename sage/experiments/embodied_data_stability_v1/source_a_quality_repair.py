"""Reversible Source-A overlay for contact-aware grasp and safe placement.

The pinned Source-A tree remains byte-for-byte unchanged.  This module patches
its public runner seams only for the lifetime of one bounded repair attempt:

* each physical finger latches independently at first object contact;
* a small, bounded preload replaces the shared full-close position command;
* cage depth, contact loss, or measured slip is the only reason to tighten a
  latched finger;
* excessive hand/object penetration immediately unloads the fingers;
* touchdown stops on first table support, unloads, confirms support, then lets
  Source A's existing staged opening continue; and
* untuck/pre-place translations are preflighted against the object's actual
  collision primitives, with a reachable clear route selected before motion.

It does not change the walking policy, arm IK, MuJoCo parameters, collision
meshes, task predicates, or frozen quality gates.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence


DEFAULT_CONFIG_PATH = Path(__file__).with_name("configs") / "source_a_quality_repair_v2.json"

FINGER_GROUPS: dict[str, tuple[int, ...]] = {
    "thumb": (0, 1, 2),
    "index": (3, 4),
    "middle": (5, 6),
}


@dataclass(frozen=True)
class RepairConfig:
    schema: str
    controller_id: str
    contact_preload_rad: float
    recovery_increment_rad: float
    max_recovery_preload_rad: float
    support_preload_rad: float
    penetration_guard_m: float
    contact_loss_confirm_steps: int
    slip_recovery_threshold_m: float
    slip_recovery_cooldown_steps: int
    cage_depth_target_m: float
    cage_recovery_interval_steps: int
    support_confirm_seconds: float
    support_confirm_consecutive_steps: int
    support_max_vertical_speed_mps: float
    min_path_clearance_m: float
    path_samples_per_segment: int
    max_endpoint_raise_m: float
    endpoint_raise_step_m: float
    lateral_search_step_m: float
    lateral_search_steps: int
    max_ik_residual_m: float
    max_restance_attempts: int
    restance_step_m: float

    def validate(self) -> None:
        if self.schema != "source-a-quality-repair-config/v1":
            raise ValueError(f"unsupported repair config schema: {self.schema}")
        if not self.controller_id.strip():
            raise ValueError("controller_id must be non-empty")
        positive = (
            "contact_preload_rad",
            "recovery_increment_rad",
            "max_recovery_preload_rad",
            "penetration_guard_m",
            "support_confirm_seconds",
            "support_max_vertical_speed_mps",
            "min_path_clearance_m",
            "path_samples_per_segment",
            "endpoint_raise_step_m",
            "max_ik_residual_m",
            "restance_step_m",
            "cage_depth_target_m",
        )
        for name in positive:
            if float(getattr(self, name)) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.support_preload_rad < 0:
            raise ValueError("support_preload_rad must be non-negative")
        if self.contact_preload_rad > self.max_recovery_preload_rad:
            raise ValueError("contact preload cannot exceed recovery preload bound")
        if self.support_preload_rad > self.contact_preload_rad:
            raise ValueError("support preload must not exceed contact preload")
        if self.max_endpoint_raise_m < 0 or self.lateral_search_steps < 0:
            raise ValueError("path search bounds must be non-negative")
        if self.contact_loss_confirm_steps <= 0 or self.support_confirm_consecutive_steps <= 0:
            raise ValueError("confirmation step counts must be positive")
        if self.cage_recovery_interval_steps <= 0:
            raise ValueError("cage_recovery_interval_steps must be positive")


def load_repair_config(path: Path = DEFAULT_CONFIG_PATH) -> RepairConfig:
    raw = json.loads(path.read_text(encoding="utf-8"))
    # The already-executed v1 artifact remains loadable and byte-stable.  Its
    # absent cage gate is represented by an unreachable target, so replaying
    # that config retains the original first-contact-only behavior.
    raw.setdefault("cage_depth_target_m", float("inf"))
    raw.setdefault("cage_recovery_interval_steps", 10)
    config = RepairConfig(**raw)
    config.validate()
    return config


def _toward_closed_limit(q: float, direction: float, preload: float, raw: float) -> float:
    target = q + direction * preload
    return min(target, raw) if direction > 0 else max(target, raw)


def _is_more_open(target: float, current: float, direction: float) -> bool:
    return direction * (target - current) < -1e-9


class FingerLatchController:
    """Pure state machine for the seven finger position actuators."""

    def __init__(self, closed_values: Sequence[float], config: RepairConfig):
        if len(closed_values) != 7:
            raise ValueError("Source A repair expects exactly seven right-hand actuators")
        self.closed_values = tuple(float(value) for value in closed_values)
        if any(abs(value) < 1e-12 for value in self.closed_values):
            raise ValueError("finger closed values must be non-zero")
        self.directions = tuple(math.copysign(1.0, value) for value in self.closed_values)
        self.config = config
        self.active = False
        self.support_unloading = False
        self.support_confirmed = False
        self.opening_groups: set[str] = set()
        self.targets: list[float | None] = [None] * 7
        self.group_state = {name: "inactive" for name in FINGER_GROUPS}
        self.loss_steps = {name: 0 for name in FINGER_GROUPS}
        self.last_raw: list[float] = [0.0] * 7
        self.slip_reference_m: float | None = None
        self.slip_cooldown = 0
        self.cage_steps = 0
        self.events: list[dict[str, Any]] = []
        self.max_observed_penetration_m = 0.0

    def _event(self, event: str, sim_time_s: float, **details: Any) -> None:
        self.events.append({"event": event, "sim_time_s": float(sim_time_s), **details})

    def begin_grasp(self, sim_time_s: float) -> None:
        self.active = True
        self.support_unloading = False
        self.support_confirmed = False
        self.opening_groups.clear()
        self.targets = [None] * 7
        self.group_state = {name: "seeking_contact" for name in FINGER_GROUPS}
        self.loss_steps = {name: 0 for name in FINGER_GROUPS}
        self.slip_reference_m = None
        self.slip_cooldown = 0
        self.cage_steps = 0
        self._event("grasp_started", sim_time_s)

    def finish_grasp(self, sim_time_s: float, slip_m: float) -> None:
        self.slip_reference_m = float(slip_m)
        self._event(
            "grasp_ramp_finished",
            sim_time_s,
            slip_reference_m=float(slip_m),
            group_state=dict(self.group_state),
        )

    def commands(self, raw: Sequence[float], q: Sequence[float]) -> list[float]:
        if len(raw) != 7 or len(q) != 7:
            raise ValueError("finger command and position vectors must have length seven")
        self.last_raw = [float(value) for value in raw]
        if not self.active:
            return self.last_raw.copy()
        out = self.last_raw.copy()
        for group, indices in FINGER_GROUPS.items():
            if group in self.opening_groups:
                continue
            for index in indices:
                if self.targets[index] is not None:
                    out[index] = float(self.targets[index])
        return out

    def _latch_group(
        self,
        group: str,
        q: Sequence[float],
        preload: float,
        sim_time_s: float,
        event: str,
    ) -> None:
        targets: list[float] = []
        for index in FINGER_GROUPS[group]:
            target = _toward_closed_limit(
                float(q[index]),
                self.directions[index],
                preload,
                self.last_raw[index],
            )
            self.targets[index] = target
            targets.append(target)
        self.group_state[group] = "latched"
        self.loss_steps[group] = 0
        self._event(event, sim_time_s, group=group, targets_rad=targets, preload_rad=preload)

    def _recover_group(self, group: str, q: Sequence[float], sim_time_s: float, why: str) -> None:
        changed = False
        targets: list[float] = []
        for index in FINGER_GROUPS[group]:
            previous = self.targets[index]
            if previous is None:
                continue
            direction = self.directions[index]
            proposed = float(previous) + direction * self.config.recovery_increment_rad
            q_bound = float(q[index]) + direction * self.config.max_recovery_preload_rad
            if direction > 0:
                proposed = min(proposed, q_bound, self.last_raw[index])
            else:
                proposed = max(proposed, q_bound, self.last_raw[index])
            changed = changed or abs(proposed - float(previous)) > 1e-12
            self.targets[index] = proposed
            targets.append(proposed)
        if changed:
            self._event(
                "finger_recovery_increment",
                sim_time_s,
                group=group,
                reason=why,
                targets_rad=targets,
            )

    def observe(
        self,
        *,
        q: Sequence[float],
        contacts: dict[str, float],
        max_penetration_m: float,
        slip_m: float,
        sim_time_s: float,
    ) -> None:
        if not self.active:
            return
        self.max_observed_penetration_m = max(
            self.max_observed_penetration_m, float(max_penetration_m)
        )

        if max_penetration_m >= self.config.penetration_guard_m:
            for group in FINGER_GROUPS:
                if group not in self.opening_groups:
                    self._latch_group(
                        group,
                        q,
                        self.config.support_preload_rad,
                        sim_time_s,
                        "penetration_guard_unload",
                    )
            return

        for group in FINGER_GROUPS:
            if group in self.opening_groups:
                continue
            in_contact = group in contacts
            if self.group_state[group] == "seeking_contact" and in_contact:
                self._latch_group(
                    group,
                    q,
                    self.config.contact_preload_rad,
                    sim_time_s,
                    "first_contact_latched",
                )
                continue
            if self.group_state[group] != "latched" or self.support_unloading:
                continue
            self.loss_steps[group] = 0 if in_contact else self.loss_steps[group] + 1
            if self.loss_steps[group] >= self.config.contact_loss_confirm_steps:
                self._recover_group(group, q, sim_time_s, "contact_loss")
                self.loss_steps[group] = 0

        # First contact is not yet a stable cage.  Once thumb and one opposing
        # finger are both touching, advance only those contacted fingers in
        # small bounded increments until the cylinder reaches the established
        # 3--4.5 cm in-palm window.  This replaces v1's mistaken assumption
        # that any first contact was already enough to lift.
        opposing = [
            group
            for group in ("index", "middle")
            if self.group_state[group] == "latched"
        ]
        if (
            not self.support_unloading
            and self.group_state["thumb"] == "latched"
            and opposing
            and float(slip_m) > self.config.cage_depth_target_m
        ):
            self.cage_steps += 1
            if self.cage_steps >= self.config.cage_recovery_interval_steps:
                self._recover_group("thumb", q, sim_time_s, "cage_depth")
                for group in opposing:
                    self._recover_group(group, q, sim_time_s, "cage_depth")
                self.cage_steps = 0
        else:
            self.cage_steps = 0

        if self.slip_cooldown > 0:
            self.slip_cooldown -= 1
        if (
            not self.support_unloading
            and self.slip_reference_m is not None
            and self.slip_cooldown == 0
            and abs(float(slip_m) - self.slip_reference_m)
            >= self.config.slip_recovery_threshold_m
        ):
            for group in FINGER_GROUPS:
                if self.group_state[group] == "latched" and group not in self.opening_groups:
                    self._recover_group(group, q, sim_time_s, "slip")
            self.slip_reference_m = float(slip_m)
            self.slip_cooldown = self.config.slip_recovery_cooldown_steps

    def begin_support_unload(self, q: Sequence[float], sim_time_s: float) -> None:
        self.support_unloading = True
        self.support_confirmed = False
        for group in FINGER_GROUPS:
            if group not in self.opening_groups:
                self._latch_group(
                    group,
                    q,
                    self.config.support_preload_rad,
                    sim_time_s,
                    "support_preload",
                )
        self._event("support_unload_started", sim_time_s)

    def confirm_support(self, sim_time_s: float) -> None:
        self.support_confirmed = True
        self._event("support_confirmed", sim_time_s)

    def begin_open(
        self,
        groups: Iterable[str],
        sim_time_s: float,
        *,
        require_support: bool,
    ) -> None:
        groups = tuple(groups)
        if require_support and not self.support_confirmed:
            raise RuntimeError("finger opening requested before stable table support")
        for group in groups:
            self.opening_groups.add(group)
            for index in FINGER_GROUPS[group]:
                self.targets[index] = None
            self.group_state[group] = "opening"
        self._event("staged_open_started", sim_time_s, groups=list(groups))

    def reset_after_open(self, sim_time_s: float) -> None:
        self._event("hand_fully_open", sim_time_s)
        self.active = False
        self.support_unloading = False
        self.targets = [None] * 7
        self.group_state = {name: "inactive" for name in FINGER_GROUPS}

    def report(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "support_unloading": self.support_unloading,
            "support_confirmed": self.support_confirmed,
            "group_state": dict(self.group_state),
            "max_observed_hand_object_penetration_m": self.max_observed_penetration_m,
            "events": list(self.events),
        }


def sample_polyline(points: Sequence[Sequence[float]], samples_per_segment: int) -> list[tuple[float, float, float]]:
    """Deterministically sample a polyline, including both endpoints once."""

    if len(points) < 2:
        raise ValueError("a path needs at least two points")
    if samples_per_segment < 2:
        raise ValueError("samples_per_segment must be at least two")
    out: list[tuple[float, float, float]] = []
    for segment, (start, end) in enumerate(zip(points, points[1:])):
        if len(start) != 3 or len(end) != 3:
            raise ValueError("path points must be xyz triples")
        for index in range(samples_per_segment):
            if segment and index == 0:
                continue
            frac = index / (samples_per_segment - 1)
            out.append(tuple(float(a) + (float(b) - float(a)) * frac for a, b in zip(start, end)))
    return out


def select_safe_translation_route(
    *,
    start: Sequence[float],
    requested: Sequence[float],
    candidates: Iterable[Sequence[float]],
    clearance: Callable[[Sequence[Sequence[float]]], float | None],
    reachable: Callable[[Sequence[float]], tuple[bool, float]],
    min_clearance_m: float,
    safe_height: Callable[[Sequence[float]], float],
) -> dict[str, Any] | None:
    """Choose the least-perturbing clear route; pure and unit-testable."""

    start = tuple(float(value) for value in start)
    requested = tuple(float(value) for value in requested)
    best: tuple[float, dict[str, Any]] | None = None
    for endpoint_value in candidates:
        endpoint = tuple(float(value) for value in endpoint_value)
        ok, residual = reachable(endpoint)
        if not ok:
            continue
        direct = [start, endpoint]
        direct_clear = clearance(direct)
        routes = [("direct", direct, direct_clear)]
        high = (endpoint[0], endpoint[1], max(start[2], endpoint[2], safe_height(endpoint)))
        if high != endpoint:
            routed = [start, high, endpoint]
            routes.append(("high_then_descend", routed, clearance(routed)))
        for kind, points, minimum in routes:
            if minimum is not None and minimum < min_clearance_m:
                continue
            delta = math.dist(endpoint, requested)
            extra = sum(math.dist(a, b) for a, b in zip(points, points[1:])) - math.dist(start, endpoint)
            score = delta + 0.25 * extra + 2.0 * float(residual)
            record = {
                "kind": kind,
                "points": [list(point) for point in points],
                "endpoint_delta_m": delta,
                "extra_path_m": extra,
                "ik_residual_m": float(residual),
                "predicted_min_clearance_m": minimum,
            }
            if best is None or score < best[0]:
                best = (score, record)
    return None if best is None else best[1]


class SourceAQualityRepairRuntime:
    """Install/uninstall the repair overlay around exactly one Source-A run."""

    def __init__(self, config: RepairConfig):
        config.validate()
        self.config = config
        self.pipeline: Any | None = None
        self.sim: Any | None = None
        self.runner: Any | None = None
        self.fingers: FingerLatchController | None = None
        self.geometry: dict[str, Any] | None = None
        self.route_plans: list[dict[str, Any]] = []
        self.support_report: dict[str, Any] | None = None
        self.restance_events: list[dict[str, Any]] = []
        self._originals: dict[str, Any] = {}
        self._installed = False

    @staticmethod
    def _finger_group(body_name: str) -> str | None:
        for group in FINGER_GROUPS:
            if f"right_hand_{group}" in body_name:
                return group
        return None

    def _finger_q(self, runner: Any) -> list[float]:
        return [float(runner.data.qpos[index]) for index in runner._fq]

    def _hand_contacts(self, runner: Any) -> tuple[dict[str, float], float]:
        contacts: dict[str, float] = {}
        max_penetration = 0.0
        mujoco = self.sim.mujoco
        for index in range(runner.data.ncon):
            contact = runner.data.contact[index]
            body_a = mujoco.mj_id2name(
                runner.model,
                mujoco.mjtObj.mjOBJ_BODY,
                int(runner.model.geom_bodyid[contact.geom1]),
            ) or ""
            body_b = mujoco.mj_id2name(
                runner.model,
                mujoco.mjtObj.mjOBJ_BODY,
                int(runner.model.geom_bodyid[contact.geom2]),
            ) or ""
            if "red_block" not in (body_a, body_b):
                continue
            hand_body = body_b if body_a == "red_block" else body_a
            if "right_hand" not in hand_body:
                continue
            group = self._finger_group(hand_body)
            penetration = max(0.0, -float(contact.dist))
            max_penetration = max(max_penetration, penetration)
            if group is not None:
                contacts[group] = min(contacts.get(group, 0.0), float(contact.dist))
        return contacts, max_penetration

    def _apply_finger_commands(self, runner: Any) -> None:
        if self.fingers is None:
            return
        raw = [float(runner.data.ctrl[actuator]) for actuator, _ in runner.ctrl.right_finger_actuators]
        commands = self.fingers.commands(raw, self._finger_q(runner))
        for command, (actuator, _closed) in zip(commands, runner.ctrl.right_finger_actuators):
            runner.data.ctrl[actuator] = command

    def _observe_fingers(self, runner: Any) -> None:
        if self.fingers is None or not self.fingers.active:
            return
        contacts, penetration = self._hand_contacts(runner)
        self.fingers.observe(
            q=self._finger_q(runner),
            contacts=contacts,
            max_penetration_m=penetration,
            slip_m=float(runner.slip()),
            sim_time_s=float(runner.data.time),
        )

    def _object_vertical_speed(self, runner: Any) -> float:
        mujoco = self.sim.mujoco
        joint = mujoco.mj_name2id(
            runner.model, mujoco.mjtObj.mjOBJ_JOINT, "red_block_joint"
        )
        address = int(runner.model.jnt_dofadr[joint])
        return float(runner.data.qvel[address + 2])

    @staticmethod
    def _support_radius(geom_type: int, size: Sequence[float], row: Sequence[float], mujoco: Any) -> float | None:
        import numpy as np

        axis = np.asarray(row, float)
        size = np.asarray(size, float)
        if geom_type in (mujoco.mjtGeom.mjGEOM_CYLINDER, mujoco.mjtGeom.mjGEOM_CAPSULE):
            radius = float(size[1] * abs(axis[2]) + size[0] * np.hypot(axis[0], axis[1]))
            if geom_type == mujoco.mjtGeom.mjGEOM_CAPSULE:
                radius += float(size[0] * abs(axis[2]))
            return radius
        if geom_type == mujoco.mjtGeom.mjGEOM_BOX:
            return float(np.abs(axis) @ size[:3])
        if geom_type == mujoco.mjtGeom.mjGEOM_SPHERE:
            return float(size[0])
        return None

    def _collision_primitives(self, runner: Any) -> list[dict[str, Any]]:
        primitives = []
        mujoco = self.sim.mujoco
        for geom in range(runner.model.ngeom):
            if int(runner.model.geom_bodyid[geom]) != runner.cyl_bid:
                continue
            rotation = runner.data.geom_xmat[geom].reshape(3, 3)
            radii = [
                self._support_radius(
                    int(runner.model.geom_type[geom]),
                    runner.model.geom_size[geom],
                    rotation[axis],
                    mujoco,
                )
                for axis in range(3)
            ]
            if any(value is None for value in radii):
                continue
            primitives.append(
                {
                    "geom_id": geom,
                    "position": runner.data.geom_xpos[geom].copy(),
                    "radii": tuple(float(value) for value in radii),
                }
            )
        if not primitives:
            raise RuntimeError("task object has no supported collision primitives")
        return primitives

    def _path_clearance(self, runner: Any, points: Sequence[Sequence[float]]) -> float | None:
        if self.geometry is None:
            raise RuntimeError("placement geometry is unavailable")
        import numpy as np

        samples = sample_polyline(points, self.config.path_samples_per_segment)
        palm_start = runner.data.site_xpos[runner.ik.site_id].copy()
        table_center = np.asarray(self.geometry["blue_center"], float)
        table_half = np.asarray(self.geometry["blue_half"], float)
        table_top = float(self.geometry["blue_top_z"])
        primitives = self._collision_primitives(runner)
        minimum: float | None = None
        for point in samples:
            delta = np.asarray(point, float) - palm_start
            for primitive in primitives:
                position = primitive["position"] + delta
                radius_x, radius_y, radius_z = primitive["radii"]
                overlap = (
                    abs(float(position[0] - table_center[0])) <= float(table_half[0]) + radius_x
                    and abs(float(position[1] - table_center[1])) <= float(table_half[1]) + radius_y
                )
                if not overlap:
                    continue
                value = float(position[2]) - radius_z - table_top
                minimum = value if minimum is None else min(minimum, value)
        return minimum

    def _candidate_endpoints(self, requested: Sequence[float], tag: str) -> list[tuple[float, float, float]]:
        import numpy as np

        requested = np.asarray(requested, float)
        raises = list(
            np.arange(
                0.0,
                self.config.max_endpoint_raise_m + self.config.endpoint_raise_step_m * 0.5,
                self.config.endpoint_raise_step_m,
            )
        )
        offsets = [np.zeros(2)]
        if tag == "untuck" and self.geometry is not None:
            center = np.asarray(self.geometry["blue_center"], float)[:2]
            away = requested[:2] - center
            norm = float(np.linalg.norm(away))
            away = np.array([1.0, 0.0]) if norm < 1e-9 else away / norm
            side = np.array([-away[1], away[0]])
            for index in range(1, self.config.lateral_search_steps + 1):
                distance = index * self.config.lateral_search_step_m
                offsets.extend((away * distance, side * distance, -side * distance))
        candidates = []
        for offset in offsets:
            for raise_m in raises:
                candidates.append(
                    (
                        float(requested[0] + offset[0]),
                        float(requested[1] + offset[1]),
                        float(requested[2] + raise_m),
                    )
                )
        return candidates

    def _plan_translation(self, runner: Any, requested: Sequence[float], target_R: Any, tag: str) -> dict[str, Any] | None:
        import numpy as np

        start = runner.data.site_xpos[runner.ik.site_id].copy()
        primitives = self._collision_primitives(runner)
        table_top = float(self.geometry["blue_top_z"])
        lowest_relative = min(
            float(item["position"][2] - item["radii"][2] - start[2])
            for item in primitives
        )

        def reachable(endpoint: Sequence[float]) -> tuple[bool, float]:
            solver = getattr(runner.ik, "solve_ms", runner.ik.solve)
            try:
                if solver is runner.ik.solve:
                    _q, residual, _rotation = solver(runner.data, np.asarray(endpoint), target_R)
                else:
                    _q, residual, _rotation = solver(
                        runner.data,
                        np.asarray(endpoint),
                        target_R,
                        tol=self.config.max_ik_residual_m,
                    )
            except TypeError:
                _q, residual, _rotation = solver(runner.data, np.asarray(endpoint), target_R)
            return float(residual) <= self.config.max_ik_residual_m, float(residual)

        plan = select_safe_translation_route(
            start=start,
            requested=requested,
            candidates=self._candidate_endpoints(requested, tag),
            clearance=lambda points: self._path_clearance(runner, points),
            reachable=reachable,
            min_clearance_m=self.config.min_path_clearance_m,
            safe_height=lambda _endpoint: table_top - lowest_relative + self.config.min_path_clearance_m,
        )
        if plan is not None:
            plan = {"move_tag": tag, "requested_endpoint": list(map(float, requested)), **plan}
        return plan

    def _ensure_place_route(self, runner: Any, geo: dict[str, Any], target_R: Any) -> None:
        import numpy as np

        self.geometry = geo
        requested = self.sim.pelvis_to_world(runner.data, list(self.pipeline.UNTUCK_OFFSET))
        if self._plan_translation(runner, requested, target_R, "untuck") is not None:
            return
        for attempt in range(self.config.max_restance_attempts):
            center = np.asarray(geo["blue_center"], float)[:2]
            base = runner.data.qpos[:2].copy()
            away = base - center
            norm = float(np.linalg.norm(away))
            away = np.array([1.0, 0.0]) if norm < 1e-9 else away / norm
            target = base + away * self.config.restance_step_m
            yaw = float(self.sim.base_yaw(runner.data))
            before = [float(value) for value in base]
            self.pipeline.walk_to_pose_around(
                runner, target, yaw, geo, tag="quality_repair_restance"
            )
            event = {
                "attempt": attempt + 1,
                "from_xy": before,
                "requested_xy": [float(value) for value in target],
                "actual_xy": [float(value) for value in runner.data.qpos[:2]],
            }
            self.restance_events.append(event)
            requested = self.sim.pelvis_to_world(runner.data, list(self.pipeline.UNTUCK_OFFSET))
            if self._plan_translation(runner, requested, target_R, "untuck") is not None:
                event["route_recovered"] = True
                return
            event["route_recovered"] = False
        raise self.pipeline.EpisodeAborted("quality_repair_no_clear_place_route")

    def install(self, pipeline: Any, sim: Any) -> None:
        if self._installed:
            raise RuntimeError("quality repair overlay is already installed")
        self.pipeline, self.sim = pipeline, sim
        runtime = self
        self._originals = {
            "hybrid_init": pipeline.HybridRunner.__init__,
            "step_once": sim.Runner.step_once,
            "set_grip": sim.Runner.set_grip,
            "touchdown": sim.Runner.touchdown,
            "goto": sim.Runner.goto,
            "squeeze": pipeline.squeeze,
            "place_object": pipeline.place_object,
        }

        def hybrid_init(runner: Any, *args: Any, **kwargs: Any) -> None:
            runtime._originals["hybrid_init"](runner, *args, **kwargs)
            closed = [float(value) for _actuator, value in runner.ctrl.right_finger_actuators]
            runtime.runner = runner
            runtime.fingers = FingerLatchController(closed, runtime.config)
            runner.quality_repair = runtime

        def step_once(runner: Any) -> None:
            current_step = sim.mujoco.mj_step

            def controlled_step(model: Any, data: Any, *args: Any, **kwargs: Any) -> None:
                runtime._apply_finger_commands(runner)
                current_step(model, data, *args, **kwargs)

            sim.mujoco.mj_step = controlled_step
            try:
                runtime._originals["step_once"](runner)
            finally:
                sim.mujoco.mj_step = current_step
            runtime._observe_fingers(runner)

        def set_grip(
            runner: Any,
            alpha_target: float,
            seconds: float = 0.8,
            thumb: bool = True,
            fingers: bool = True,
        ) -> None:
            controller = runtime.fingers
            groups = []
            if controller is not None and controller.active:
                if thumb and alpha_target < runner.grip_alpha - 1e-9:
                    groups.append("thumb")
                if fingers and alpha_target < runner.grip_alpha_f - 1e-9:
                    groups.extend(("index", "middle"))
                if groups:
                    try:
                        controller.begin_open(
                            groups,
                            float(runner.data.time),
                            require_support=controller.support_unloading,
                        )
                    except RuntimeError as exc:
                        raise pipeline.EpisodeAborted("quality_repair_support_not_confirmed") from exc
            runtime._originals["set_grip"](
                runner,
                alpha_target,
                seconds=seconds,
                thumb=thumb,
                fingers=fingers,
            )
            if controller is not None and thumb and fingers and alpha_target <= 1e-9:
                controller.reset_after_open(float(runner.data.time))

        def squeeze(runner: Any, target: float, seconds: float, *args: Any, **kwargs: Any):
            controller = runtime.fingers
            if controller is None:
                return runtime._originals["squeeze"](runner, target, seconds, *args, **kwargs)
            controller.begin_grasp(float(runner.data.time))
            result = runtime._originals["squeeze"](runner, target, seconds, *args, **kwargs)
            controller.finish_grasp(float(runner.data.time), float(runner.slip()))
            return result

        def touchdown(
            runner: Any,
            R_hold: Any,
            max_drop: float = 0.06,
            seat: float = 0.5,
            rate: float = 0.003,
            seat_grip: float | None = None,
            table: str = "table_white",
        ) -> bool:
            del seat, seat_grip
            touched = runtime._originals["touchdown"](
                runner,
                R_hold,
                max_drop=max_drop,
                seat=0.0,
                rate=rate,
                seat_grip=None,
                table=table,
            )
            controller = runtime.fingers
            if not touched or controller is None:
                runtime.support_report = {
                    "touched": bool(touched),
                    "confirmed": False,
                    "reason": "table_contact_not_detected" if not touched else "controller_missing",
                }
                return bool(touched)
            controller.begin_support_unload(runtime._finger_q(runner), float(runner.data.time))
            max_steps = max(int(runtime.config.support_confirm_seconds / runner.model.opt.timestep), 1)
            stable = 0
            observed = 0
            max_abs_vz = 0.0
            for _ in range(max_steps):
                runner.step_once()
                observed += 1
                contact = runner.pair_contact("red_block", table)
                vz = abs(runtime._object_vertical_speed(runner))
                max_abs_vz = max(max_abs_vz, vz)
                if contact and vz <= runtime.config.support_max_vertical_speed_mps:
                    stable += 1
                else:
                    stable = 0
                if stable >= runtime.config.support_confirm_consecutive_steps:
                    controller.confirm_support(float(runner.data.time))
                    break
            runtime.support_report = {
                "touched": True,
                "confirmed": controller.support_confirmed,
                "physics_steps": observed,
                "consecutive_stable_steps": stable,
                "max_abs_object_vertical_speed_mps": max_abs_vz,
                "continued_downward_press_seconds": 0.0,
                "support_preload_rad": runtime.config.support_preload_rad,
            }
            if not controller.support_confirmed:
                raise pipeline.EpisodeAborted("quality_repair_support_not_confirmed")
            return True

        def goto(runner: Any, target_p: Any, target_R: Any, *args: Any, **kwargs: Any):
            tag = getattr(runner, "move_tag", "")
            if tag not in {"untuck", "place_pre"} or runtime.geometry is None:
                return runtime._originals["goto"](runner, target_p, target_R, *args, **kwargs)
            plan = runtime._plan_translation(runner, target_p, target_R, tag)
            if plan is None:
                raise pipeline.EpisodeAborted(f"quality_repair_no_clear_{tag}_route")
            runtime.route_plans.append(plan)
            points = plan["points"][1:]
            result = 0.0
            for index, point in enumerate(points):
                call_kwargs = dict(kwargs)
                if index < len(points) - 1:
                    call_kwargs["rounds"] = 1
                    call_kwargs["settle"] = 0.0
                result = runtime._originals["goto"](
                    runner, point, target_R, *args, **call_kwargs
                )
            return result

        def place_object(runner: Any, geo: dict[str, Any], R_c: Any, T: dict[str, Any], phase: Any = None):
            runtime.geometry = geo
            runtime._ensure_place_route(runner, geo, R_c)
            return runtime._originals["place_object"](runner, geo, R_c, T, phase=phase)

        pipeline.HybridRunner.__init__ = hybrid_init
        sim.Runner.step_once = step_once
        sim.Runner.set_grip = set_grip
        sim.Runner.touchdown = touchdown
        sim.Runner.goto = goto
        pipeline.squeeze = squeeze
        pipeline.place_object = place_object
        self._installed = True

    def uninstall(self) -> None:
        if not self._installed:
            return
        self.pipeline.HybridRunner.__init__ = self._originals["hybrid_init"]
        self.sim.Runner.step_once = self._originals["step_once"]
        self.sim.Runner.set_grip = self._originals["set_grip"]
        self.sim.Runner.touchdown = self._originals["touchdown"]
        self.sim.Runner.goto = self._originals["goto"]
        self.pipeline.squeeze = self._originals["squeeze"]
        self.pipeline.place_object = self._originals["place_object"]
        self._installed = False

    def report(self) -> dict[str, Any]:
        return {
            "schema": "source-a-quality-repair-runtime/v1",
            "controller_id": self.config.controller_id,
            "pinned_source_modified": False,
            "body_controller_modified": False,
            "arm_ik_modified": False,
            "physics_parameters_modified": False,
            "finger_controller": None if self.fingers is None else self.fingers.report(),
            "support_release": self.support_report,
            "route_plans": self.route_plans,
            "restance_events": self.restance_events,
            "config": asdict(self.config),
        }
