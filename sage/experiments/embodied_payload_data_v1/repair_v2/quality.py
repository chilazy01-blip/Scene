"""Fail-closed, phase-aware quality predicates with explicit evidence boundaries.

Force and touchdown limits must be supplied by a validated model contract. This
module deliberately does not invent calibrated limits from old query forces.
"""
from dataclasses import dataclass
import math

from . import QUALITY_VERSION


def finite(*values):
    return all(isinstance(v, (int, float)) and math.isfinite(v) for v in values)


@dataclass(frozen=True)
class QualityContract:
    version: str = QUALITY_VERSION
    dt: float = 0.005
    support_duration: float = 1.0
    bottom_margin: float = 0.005
    com_margin: float = 0.01
    load_relative_tolerance: float = 0.10
    force_balance_relative_tolerance: float = 0.10
    contact_force_epsilon: float = 1e-4
    penetration_contact_epsilon: float = 1e-6
    transient_window: float = 0.04
    loaded_foot_force: float = 5.0
    transient_speed_limit: float | None = None
    transient_impulse_limit: float | None = None
    placement_force_limit: float | None = None
    placement_impulse_limit: float | None = None
    placement_speed_limit: float | None = None
    force_calibration_id: str | None = None

    def __post_init__(self):
        for name, value in vars(self).items():
            if name in ("version", "force_calibration_id") or value is None:
                continue
            if not finite(value) or value <= 0:
                raise ValueError("invalid_quality_parameter:" + name)
        if self.version != QUALITY_VERSION:
            raise ValueError("unknown_quality_version")


def result(checks, **measurements):
    return dict(passed=bool(checks) and all(checks.values()), checks=checks,
                quality_version=QUALITY_VERSION, **measurements)


def phase_contacts(contacts, phase, roles, board, source_supports=()):
    """Evaluate actual contact pairs, not a caller-provided 'allowed' flag."""
    if phase not in {"pick", "carry", "settle", "place", "release", "withdraw", "hold"}:
        return result({"known_phase": False}, violations=["unknown_phase"])
    violations = []
    for c in contacts:
        names = c.get("geoms", [])
        force, distance = c.get("normal_force"), c.get("distance")
        if len(names) != 2 or any(n not in roles for n in names) or not finite(force, distance):
            violations.append("invalid_contact_evidence")
            continue
        if force <= 1e-4 and distance >= -1e-6:
            continue
        pair = {roles[n] for n in names}
        robot = bool(pair & {"robot", "hand", "foot"})
        allowed = pair in ({"foot", "floor"}, {"hand", "object"}) or not robot
        if "object" in pair and pair != {"object"}:
            other = next(n for n in names if roles[n] != "object")
            if roles[other] == "hand":
                allowed = phase not in {"withdraw", "hold"}
            else:
                allowed = ((phase == "pick" and other in source_supports)
                           or (phase in {"place", "release", "withdraw", "hold"} and other == board))
        if not allowed:
            violations.append({"geoms": names, "phase": phase})
    return result({"phase_contacts": not violations}, violations=violations)


def support_sample(s, contract):
    """Require full footprint and COM, independent support, and force balance.

    board_vertical_load is the world vertical force on the object, not a sum of
    unsigned contact normals. A query force is never silently an impulse.
    """
    keys = ("bottom_margin", "com_margin", "board_vertical_load", "weight",
            "force_residual", "other_support_load", "hand_contacts",
            "object_linear", "object_angular")
    if any(k not in s for k in keys) or not finite(*(s[k] for k in keys)) or s["weight"] <= 0:
        return result({"complete_finite_evidence": False})
    weight = s["weight"]
    checks = dict(
        bottom_inside=s["bottom_margin"] >= contract.bottom_margin,
        com_inside=s["com_margin"] >= contract.com_margin,
        board_carries_weight=abs(s["board_vertical_load"] - weight) <= weight * contract.load_relative_tolerance,
        balanced=0 <= s["force_residual"] <= weight * contract.force_balance_relative_tolerance,
        no_other_support=0 <= s["other_support_load"] <= contract.contact_force_epsilon,
        no_hands=s["hand_contacts"] == 0,
        stationary=0 <= s["object_linear"] <= .02 and 0 <= s["object_angular"] <= .1,
    )
    return result(checks)


def support_window(samples, contract):
    count = math.ceil(contract.support_duration / contract.dt - 1e-9)
    if len(samples) < count:
        return result({"complete_window": False}, samples=len(samples))
    window = samples[-count:]
    times = [s.get("time") for s in window]
    contiguous = (finite(*times) and all(abs(b-a-contract.dt) < 1e-8 for a, b in zip(times, times[1:])))
    return result(dict(complete_window=True, contiguous=contiguous,
                       independent_supported=all(support_sample(s, contract)["passed"] for s in window)),
                  samples=count, duration=count * contract.dt)


def contact_dynamics(samples, contract):
    calibrated = bool(contract.force_calibration_id) and all(v is not None for v in (
        contract.placement_force_limit, contract.placement_impulse_limit, contract.placement_speed_limit))
    valid = bool(samples) and all(
        s.get("force_semantics") == "integrated_step_world_force"
        and finite(s.get("force_norm"), s.get("approach_speed"), s.get("dt"))
        and s["dt"] > 0 and s["force_norm"] >= 0 and s["approach_speed"] >= 0
        for s in samples)
    if not (valid and calibrated):
        return result(dict(calibrated=calibrated, integrated_force_evidence=valid))
    impulse = sum(s["force_norm"] * s["dt"] for s in samples)
    return result(dict(calibrated=True, integrated_force_evidence=True,
                       peak_force=max(s["force_norm"] for s in samples) <= contract.placement_force_limit,
                       impulse=impulse <= contract.placement_impulse_limit,
                       approach=max(s["approach_speed"] for s in samples) <= contract.placement_speed_limit),
                  impulse_Ns=impulse)


def foot_transients(rows, contract):
    """Retain both edges and short contact episodes; never call speed integral slip."""
    events = []
    valid = bool(rows) and all(finite(r.get("time"), *r.get("foot_load", {}).values(),
                                    *r.get("foot_slip", {}).values())
                               and all(s in r.get("foot_load", {}) and s in r.get("foot_slip", {})
                                       for s in ("left", "right")) for r in rows)
    if not valid:
        return result({"complete_finite_evidence": False}, events=[])
    contiguous = all(abs(b["time"]-a["time"]-contract.dt) < 1e-8 for a,b in zip(rows, rows[1:]))
    for side in ("left", "right"):
        start = None
        for i in range(len(rows)+1):
            loaded = i < len(rows) and rows[i]["foot_load"][side] >= contract.loaded_foot_force
            if loaded and start is None:
                start = i
            if not loaded and start is not None:
                end = i-1
                for kind, indices in (
                    ("landing", [j for j in range(start, i) if (j-start)*contract.dt < contract.transient_window-1e-9]),
                    ("leaving", [j for j in range(start, i) if (end-j)*contract.dt < contract.transient_window-1e-9]),
                ):
                    segment = [rows[j] for j in indices]
                    integrated = all(r.get("force_semantics") == "integrated_step_world_force" for r in segment)
                    events.append(dict(side=side, kind=kind, start_index=indices[0], end_index=indices[-1],
                        peak_contact_speed=max(r["foot_slip"][side] for r in segment),
                        contact_speed_integral_m=sum(r["foot_slip"][side]*contract.dt for r in segment),
                        impulse_Ns=sum(r["foot_load"][side]*contract.dt for r in segment) if integrated else None))
                start = None
    calibrated = bool(contract.force_calibration_id) and contract.transient_speed_limit is not None and contract.transient_impulse_limit is not None
    evidence = bool(events) and all(e["impulse_Ns"] is not None for e in events)
    passed = calibrated and evidence and all(e["peak_contact_speed"] <= contract.transient_speed_limit and e["impulse_Ns"] <= contract.transient_impulse_limit for e in events)
    return result(dict(contiguous=contiguous, calibrated=calibrated, integrated_force_evidence=evidence,
                       transient_limits=passed), events=events)


def continuous_transport(rows, swings, initial_z, roles, dt=.005):
    """Qualify steps and displacement in the same uninterrupted hand-carried run."""
    segments, start = [], None
    def active(r):
        pos = r.get("object_position", [])
        if len(pos) != 3 or not finite(*pos, r.get("hand_contacts"), r.get("time")):
            return False
        if pos[2] <= initial_z+.05 or r["hand_contacts"] <= 0:
            return False
        for c in r.get("contacts", []):
            if any(n not in roles for n in c.get("geoms", [])) or not finite(c.get("normal_force"), c.get("distance")):
                return False
            pair = {roles[n] for n in c["geoms"]}
            if "object" in pair and pair not in ({"object", "hand"}, {"object"}) and (c["normal_force"] > 1e-4 or c["distance"] < -1e-6):
                return False
        return True
    for i in range(len(rows)+1):
        good = i < len(rows) and active(rows[i])
        gap = i > 0 and i < len(rows) and abs(rows[i]["time"]-rows[i-1]["time"]-dt) > 1e-8
        if start is not None and (not good or gap):
            chunk = rows[start:i]
            events = sorted((e for e in swings if e["start"] >= chunk[0]["time"]-1e-9 and e["end"] <= chunk[-1]["time"]+1e-9
                             and e.get("opposite_min_load", 0) >= 5 and e.get("duration", 0) >= .08), key=lambda e:e["start"])
            best = n = 0
            prev = None
            for e in events:
                n = n+1 if prev is not None and e["side"] != prev else 1
                best = max(n,best); prev = e["side"]
            distance = max(math.dist(chunk[0]["object_position"][:2], r["object_position"][:2]) for r in chunk)
            segments.append(dict(start=chunk[0]["time"], end=chunk[-1]["time"], distance=distance, alternating_events=best))
            start = None
        if good and start is None:
            start = i
    return result({"continuous_carried_steps": any(s["distance"] >= .2 and s["alternating_events"] >= 4 for s in segments)}, segments=segments)
