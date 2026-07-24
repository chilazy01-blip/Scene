from __future__ import annotations

from copy import deepcopy
from typing import Any


AXES = ("width", "length", "height")


DEFAULT_DIMENSION_POLICY: dict[str, Any] = {
    "mode": "fixed_physical",
    "relative_tolerance": 0.08,
    "enforce_at_assembly": True,
}


UNIFORM_SCALABLE_CATEGORIES = {
    "potted_plant",
    "wall_art",
    "mirror",
    "pillow",
}


AXIS_SCALABLE_POLICIES: dict[str, dict[str, Any]] = {
    "desk": {"width": [0.80, 1.25]},
    "dining_table": {"width": [0.80, 1.25], "length": [0.85, 1.20]},
    "coffee_table": {"width": [0.80, 1.25], "length": [0.85, 1.20]},
    "side_table": {"width": [0.85, 1.15], "length": [0.85, 1.15]},
    "dresser": {"width": [0.80, 1.25]},
    "area_rug": {"width": [0.65, 1.50], "length": [0.65, 1.50]},
    "curtain_rod": {"width": [0.60, 1.80]},
    "curtain_panel": {"width": [0.70, 1.40], "height": [0.80, 1.20]},
}


MODULAR_CATEGORIES = {
    "wardrobe",
    "bookcase",
    "cabinet",
    "counter",
    "tv_stand",
    "sink_cabinet",
}


OPENING_FIT_CATEGORIES = {"door", "window"}


def dimension_policy_for_category(category: str) -> dict[str, Any]:
    if category in OPENING_FIT_CATEGORIES:
        return {
            "mode": "opening_fit",
            "axis_scale_ranges": {
                "width": [0.50, 2.00],
                "length": [0.50, 2.00],
                "height": [0.50, 2.00],
            },
            "enforce_at_assembly": True,
        }
    if category in MODULAR_CATEGORIES:
        return {
            "mode": "modular",
            "relative_tolerance": 0.06,
            "enforce_at_assembly": True,
        }
    if category in AXIS_SCALABLE_POLICIES:
        return {
            "mode": "axis_scalable",
            "axis_scale_ranges": deepcopy(AXIS_SCALABLE_POLICIES[category]),
            "locked_axis_tolerance": 0.06,
            "enforce_at_assembly": True,
        }
    if category in UNIFORM_SCALABLE_CATEGORIES:
        return {
            "mode": "uniform_scalable",
            "uniform_scale_range": [0.85, 1.15],
            "anisotropy_tolerance": 0.06,
            "enforce_at_assembly": True,
        }
    return deepcopy(DEFAULT_DIMENSION_POLICY)


def _dimensions(value: Any) -> dict[str, float] | None:
    if not isinstance(value, dict) or not all(axis in value for axis in AXES):
        return None
    result = {axis: float(value[axis]) for axis in AXES}
    if any(result[axis] <= 0.0 for axis in AXES):
        return None
    return result


def _scale_factors(
    source: dict[str, float], target: dict[str, float]
) -> dict[str, float]:
    return {axis: target[axis] / source[axis] for axis in AXES}


def _max_relative_error(
    left: dict[str, float], right: dict[str, float]
) -> float:
    return max(abs(left[axis] - right[axis]) / max(right[axis], 1e-9) for axis in AXES)


def _result(
    *,
    accepted: bool,
    status: str,
    policy: dict[str, Any],
    requested: dict[str, float],
    source: dict[str, float] | None,
    effective: dict[str, float] | None,
    reason: str,
    requires_runtime_bounds_check: bool = False,
) -> dict[str, Any]:
    scale_factors = _scale_factors(source, effective) if source and effective else None
    return {
        "accepted": accepted,
        "status": status,
        "policy_mode": str(policy.get("mode") or "fixed_physical"),
        "requested_dimensions": requested,
        "source_dimensions": source,
        "effective_dimensions": effective,
        "scale_factors": scale_factors,
        "max_requested_error": (
            round(_max_relative_error(effective, requested), 6) if effective else None
        ),
        "requires_runtime_bounds_check": requires_runtime_bounds_check,
        "reason": reason,
    }


def resolve_dimension_adaptation(
    source_dimensions: Any,
    requested_dimensions: Any,
    policy: dict[str, Any],
) -> dict[str, Any]:
    requested = _dimensions(requested_dimensions)
    if requested is None:
        raise ValueError("requested dimensions must contain positive width, length, and height")
    source = _dimensions(source_dimensions)
    mode = str(policy.get("mode") or "fixed_physical")
    if source is None:
        return _result(
            accepted=True,
            status="source_dimensions_unverified",
            policy=policy,
            requested=requested,
            source=None,
            effective=requested,
            reason="manifest source dimensions are missing; verify imported bounds at assembly",
            requires_runtime_bounds_check=True,
        )

    requested_scale = _scale_factors(source, requested)
    if _max_relative_error(source, requested) <= 1e-6:
        return _result(
            accepted=True,
            status="exact_match",
            policy=policy,
            requested=requested,
            source=source,
            effective=source,
            reason="requested and canonical source dimensions match",
        )

    if mode in {"fixed_physical", "modular"}:
        tolerance = float(policy.get("relative_tolerance", 0.06))
        error = _max_relative_error(source, requested)
        if error <= tolerance:
            return _result(
                accepted=True,
                status="source_dimensions_preserved",
                policy=policy,
                requested=requested,
                source=source,
                effective=source,
                reason=f"{mode} preserves canonical dimensions within {tolerance:.3f} tolerance",
            )
        return _result(
            accepted=False,
            status="incompatible_dimensions",
            policy=policy,
            requested=requested,
            source=source,
            effective=None,
            reason=f"{mode} mismatch {error:.3f} exceeds {tolerance:.3f} tolerance",
        )

    if mode == "uniform_scalable":
        minimum, maximum = [float(item) for item in policy.get("uniform_scale_range", [0.85, 1.15])]
        scales = list(requested_scale.values())
        uniform_scale = sum(scales) / len(scales)
        anisotropy = max(scales) - min(scales)
        tolerance = float(policy.get("anisotropy_tolerance", 0.06))
        if minimum <= uniform_scale <= maximum and anisotropy <= tolerance:
            effective = {axis: source[axis] * uniform_scale for axis in AXES}
            return _result(
                accepted=True,
                status="bounded_uniform_scale",
                policy=policy,
                requested=requested,
                source=source,
                effective=effective,
                reason=f"uniform scale {uniform_scale:.3f} within [{minimum:.3f}, {maximum:.3f}]",
            )
        return _result(
            accepted=False,
            status="incompatible_dimensions",
            policy=policy,
            requested=requested,
            source=source,
            effective=None,
            reason=(
                f"uniform scale {uniform_scale:.3f} or anisotropy {anisotropy:.3f} exceeds policy"
            ),
        )

    if mode in {"axis_scalable", "opening_fit"}:
        ranges = policy.get("axis_scale_ranges")
        ranges = ranges if isinstance(ranges, dict) else {}
        locked_tolerance = float(policy.get("locked_axis_tolerance", 0.06))
        effective = dict(source)
        for axis in AXES:
            scale = requested_scale[axis]
            raw_range = ranges.get(axis)
            if isinstance(raw_range, list) and len(raw_range) == 2:
                minimum, maximum = float(raw_range[0]), float(raw_range[1])
                if not minimum <= scale <= maximum:
                    return _result(
                        accepted=False,
                        status="incompatible_dimensions",
                        policy=policy,
                        requested=requested,
                        source=source,
                        effective=None,
                        reason=f"{axis} scale {scale:.3f} outside [{minimum:.3f}, {maximum:.3f}]",
                    )
                effective[axis] = requested[axis]
            elif abs(scale - 1.0) > locked_tolerance:
                return _result(
                    accepted=False,
                    status="incompatible_dimensions",
                    policy=policy,
                    requested=requested,
                    source=source,
                    effective=None,
                    reason=f"locked {axis} scale {scale:.3f} exceeds tolerance {locked_tolerance:.3f}",
                )
        return _result(
            accepted=True,
            status="opening_fit" if mode == "opening_fit" else "bounded_axis_scale",
            policy=policy,
            requested=requested,
            source=source,
            effective=effective,
            reason=f"requested dimensions satisfy {mode} ranges",
        )

    raise ValueError(f"Unsupported dimension policy mode: {mode}")


def dimension_preference_key(resolution: dict[str, Any]) -> tuple[int, float]:
    rank = {
        "exact_match": 0,
        "source_dimensions_preserved": 1,
        "bounded_uniform_scale": 2,
        "bounded_axis_scale": 2,
        "opening_fit": 2,
        "source_dimensions_unverified": 3,
    }.get(str(resolution.get("status")), 9)
    return rank, float(resolution.get("max_requested_error") or 0.0)
