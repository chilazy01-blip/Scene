"""Pure-Python dimension checks shared by orchestration and Blender."""

from __future__ import annotations

import math
from typing import Any


def runtime_mesh_fit_audit(
    axis_scale_factors: Any,
    dimension_policy: dict[str, Any] | None,
    dimension_resolution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Check imported proportions, separately from declared axis adaptation.

    Known physical source dimensions must describe the imported shape up to a
    uniform unit conversion. Deliberate axis adaptation is already resolved
    upstream and is divided out before checking that source calibration.
    Missing policies are unassessed, never successful certificates.
    """
    policy = dimension_policy if isinstance(dimension_policy, dict) else {}
    resolution = dimension_resolution if isinstance(dimension_resolution, dict) else {}
    contract = policy.get("runtime_mesh_fit")
    contract = contract if isinstance(contract, dict) else {}
    try:
        scales = [float(value) for value in axis_scale_factors]
    except (TypeError, ValueError, OverflowError):
        scales = []
    valid = len(scales) == 3 and all(math.isfinite(v) and v > 0 for v in scales)
    anisotropy = max(scales) / min(scales) if valid else None
    mode = str(policy.get("mode") or "")
    maximum = contract.get("maximum_axis_scale_anisotropy")
    source = "explicit_runtime_contract" if maximum is not None else "dimension_policy"
    adaptation = resolution.get("scale_factors")
    calibrated = list(scales)
    if isinstance(adaptation, dict):
        try:
            factors = [float(adaptation[axis]) for axis in ("width", "length", "height")]
            valid = valid and all(math.isfinite(v) and v > 0 for v in factors)
            if valid:
                calibrated = [v / factor for v, factor in zip(scales, factors)]
        except (KeyError, TypeError, ValueError, OverflowError):
            valid = False
    if maximum is None and mode:
        tolerance = float(policy.get("anisotropy_tolerance", policy.get("relative_tolerance", 0.08)))
        # Axis-adaptable sources with known dimensions still need a correct
        # calibration. For uncalibrated sources only their declared ranges
        # can authorize anisotropy; absent ranges mean preserve proportions.
        maximum = 1.0 + tolerance
        if mode in {"axis_scalable", "opening_fit"} and not isinstance(adaptation, dict):
            ranges = policy.get("axis_scale_ranges", {})
            locked = float(policy.get("locked_axis_tolerance", 0.06))
            lows, highs = [], []
            for axis in ("width", "length", "height"):
                low, high = ranges.get(axis, [1.0 - locked, 1.0 + locked])
                lows.append(float(low)); highs.append(float(high))
            maximum = max(highs) / min(lows)
    checked_anisotropy = max(calibrated) / min(calibrated) if valid else None
    report = {
        "evaluated": maximum is not None,
        "passes": None,
        "axis_scale_factors": scales if valid else None,
        "axis_scale_anisotropy": round(anisotropy, 6) if anisotropy is not None else None,
        "source_calibration_anisotropy": round(checked_anisotropy, 6) if checked_anisotropy is not None else None,
        "maximum_axis_scale_anisotropy": None,
        "policy_source": source,
        "reason": "runtime proportion policy is missing; not evaluated",
    }
    if policy.get("mesh_normalization") == "declared_axis_adaptation":
        if mode not in {"axis_scalable", "opening_fit"}:
            raise ValueError("Axis adaptation requires an axis-scalable or opening-fit policy")
        effective = resolution.get("effective_dimensions")
        declared = resolution.get("accepted") is True and isinstance(effective, dict)
        declared = declared and str(resolution.get("policy_mode")) == mode
        if declared:
            try:
                declared = all(math.isfinite(float(effective[axis])) and float(effective[axis]) > 0
                               for axis in ("width", "length", "height"))
            except (KeyError, TypeError, ValueError, OverflowError):
                declared = False
        physical_source = resolution.get("source_dimensions")
        if declared and isinstance(physical_source, dict):
            try:
                ranges = policy.get("axis_scale_ranges", {})
                locked = float(policy.get("locked_axis_tolerance", 0.06))
                for axis in ("width", "length", "height"):
                    source_value, target_value = float(physical_source[axis]), float(effective[axis])
                    low, high = ranges.get(axis, [1.0-locked, 1.0+locked])
                    ratio = target_value / source_value
                    declared = declared and math.isfinite(ratio) and source_value > 0 and float(low)-1e-6 <= ratio <= float(high)+1e-6
            except (KeyError, TypeError, ValueError, ZeroDivisionError, OverflowError):
                declared = False
        report.update(
            evaluated=True, passes=bool(valid and declared),
            proportion_preservation_required=False,
            reason="explicit axis-adaptable source; target adaptation resolved upstream and actual dimensions checked after placement",
        )
        if source == "explicit_runtime_contract":
            maximum = float(maximum)
            if not math.isfinite(maximum) or maximum < 1:
                raise ValueError("Runtime anisotropy limit must be finite and at least one")
            report["maximum_axis_scale_anisotropy"] = maximum
            report["passes"] = bool(report["passes"] and checked_anisotropy <= maximum + 1e-6)
            report["reason"] += "; explicit source-calibration limit also enforced"
        return report
    if maximum is None:
        return report
    maximum = float(maximum)
    if not math.isfinite(maximum) or maximum < 1:
        raise ValueError("Runtime anisotropy limit must be finite and at least one")
    passes = bool(valid and checked_anisotropy <= maximum + 1e-6)
    report.update(
        passes=passes,
        maximum_axis_scale_anisotropy=maximum,
        reason="imported proportions satisfy the declared policy" if passes else "imported proportions violate the declared policy or contain invalid scales",
        violation=str(contract.get("violation") or "reject_and_reselect"),
    )
    return report
