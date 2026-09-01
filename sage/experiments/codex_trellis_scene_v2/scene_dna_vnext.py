from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from PIL import Image

from .scene_dna_semantic import extract_form_features


GENERABILITY_SCHEMA = "scene_dna_2d_generability_evidence_v1"
VNEXT_SELECTION_SCHEMA = "scene_dna_vnext_candidate_selection_v1"


def _clip01(value: float) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"non-finite generability value: {value}")
    return max(0.0, min(1.0, value))


def _range_score(
    value: float,
    *,
    healthy_minimum: float,
    healthy_maximum: float,
    absolute_minimum: float,
    absolute_maximum: float,
) -> float:
    if healthy_minimum <= value <= healthy_maximum:
        return 1.0
    if value < healthy_minimum:
        denominator = max(1e-9, healthy_minimum - absolute_minimum)
        return _clip01((value - absolute_minimum) / denominator)
    denominator = max(1e-9, absolute_maximum - healthy_maximum)
    return _clip01((absolute_maximum - value) / denominator)


def _binary_erode(mask: np.ndarray) -> np.ndarray:
    padded = np.pad(mask, 1, mode="constant", constant_values=False)
    windows = [
        padded[dy : dy + mask.shape[0], dx : dx + mask.shape[1]]
        for dy in range(3)
        for dx in range(3)
    ]
    return np.logical_and.reduce(windows)


def _binary_dilate(mask: np.ndarray) -> np.ndarray:
    padded = np.pad(mask, 1, mode="constant", constant_values=False)
    windows = [
        padded[dy : dy + mask.shape[0], dx : dx + mask.shape[1]]
        for dy in range(3)
        for dx in range(3)
    ]
    return np.logical_or.reduce(windows)


def _opening_retention(mask: np.ndarray) -> float:
    if not np.any(mask):
        return 0.0
    opened = _binary_dilate(_binary_erode(mask))
    return float(np.count_nonzero(mask & opened)) / float(np.count_nonzero(mask))


def _lower_platform_evidence(crop: np.ndarray) -> dict[str, Any]:
    """Detect a low, unusually wide appendage without assuming an object category."""

    height, width = crop.shape
    if height < 8 or width < 8:
        return {
            "evaluated": False,
            "score": 0.5,
            "reason": "foreground_crop_too_small",
        }
    row_widths = crop.mean(axis=1)
    lower_start = max(1, int(height * 0.78))
    middle_start = max(0, int(height * 0.25))
    middle_end = max(middle_start + 1, int(height * 0.70))
    lower_width = float(np.percentile(row_widths[lower_start:], 80.0))
    middle_nonzero = row_widths[middle_start:middle_end]
    middle_nonzero = middle_nonzero[middle_nonzero > 0.02]
    middle_width = float(np.median(middle_nonzero)) if len(middle_nonzero) else 0.0
    width_ratio = lower_width / max(0.05, middle_width)
    connector_band = row_widths[max(0, lower_start - max(2, height // 12)) : lower_start]
    connector_width = float(np.min(connector_band)) if len(connector_band) else lower_width
    narrow_connector = connector_width <= max(0.12, lower_width * 0.42)
    suspicious = bool(lower_width >= 0.62 and width_ratio >= 1.55 and narrow_connector)
    severity = _clip01(
        max(0.0, lower_width - 0.52) / 0.40
        * max(0.0, width_ratio - 1.25) / 1.50
        * (1.0 if narrow_connector else 0.25)
    )
    return {
        "evaluated": True,
        "score": round(1.0 - severity, 6),
        "suspicious": suspicious,
        "lower_width_ratio": round(lower_width, 6),
        "middle_width_ratio": round(middle_width, 6),
        "lower_to_middle_width_ratio": round(width_ratio, 6),
        "connector_width_ratio": round(connector_width, 6),
        "narrow_connector": narrow_connector,
        "evidence_basis": "category_independent_lower_silhouette_geometry",
    }


def assess_2d_generability(
    image_path: Path,
    *,
    alpha_metadata: dict[str, Any] | None = None,
    semantic_report: dict[str, Any] | None = None,
    form_report: dict[str, Any] | None = None,
    alpha_threshold: int = 24,
) -> dict[str, Any]:
    """Estimate whether an isolated 2D reference is safe to promote to 3D.

    The evidence is deliberately category independent.  It measures image and
    silhouette failure modes that make single-image reconstruction unstable;
    semantic part evidence comes from the supplied object contract, not from a
    category-specific branch in this scorer.
    """

    image_path = Path(image_path)
    rgba = np.asarray(Image.open(image_path).convert("RGBA"), dtype=np.uint8)
    alpha = rgba[:, :, 3]
    mask = alpha > int(alpha_threshold)
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return {
            "schema": GENERABILITY_SCHEMA,
            "evaluated": False,
            "hard_gate_passed": False,
            "hard_failures": ["empty_foreground"],
            "score": 0.0,
            "category_specific_branching": False,
        }

    height, width = mask.shape
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    crop = mask[y0:y1, x0:x1]
    form_features = extract_form_features(
        image_path, alpha_threshold=alpha_threshold
    )
    foreground_ratio = float(mask.mean())
    frame_clearance = min(x0, y0, width - x1, height - y1) / float(max(width, height))
    framing_score = _range_score(
        foreground_ratio,
        healthy_minimum=0.08,
        healthy_maximum=0.72,
        absolute_minimum=0.01,
        absolute_maximum=0.94,
    )
    framing_score *= _clip01(frame_clearance / 0.025)

    # RMBG commonly assigns alpha 254 rather than 255 across an otherwise
    # confident object. Counting every non-binary pixel therefore marks nearly
    # every real cutout as uncertain. Weight uncertainty by distance from the
    # nearest binary endpoint so alpha 1/254 contributes little and alpha 128
    # contributes strongly.
    partial_alpha = (alpha > 0) & (alpha < 255)
    partial_ratio = float(np.count_nonzero(partial_alpha)) / float(
        max(1, np.count_nonzero(alpha > 0))
    )
    alpha_float = alpha.astype(np.float32)
    ambiguity_weight_ratio = float(
        np.sum(np.minimum(alpha_float, 255.0 - alpha_float))
    ) / float(max(1.0, np.sum(alpha_float)))
    segmentation_score = _clip01(1.0 - ambiguity_weight_ratio / 0.18)

    detached_ratio = float(form_features.get("detached_component_ratio", 1.0))
    opening_retention = _opening_retention(crop)
    component_score = _clip01(1.0 - detached_ratio / 0.18)
    topology_stability_score = _clip01((opening_retention - 0.58) / 0.36)
    platform = _lower_platform_evidence(crop)
    structure_score = (
        0.45 * component_score
        + 0.30 * topology_stability_score
        + 0.25 * float(platform.get("score", 0.5))
    )

    semantic_report = semantic_report if isinstance(semantic_report, dict) else {}
    semantic_evaluated = bool(semantic_report.get("evaluated"))
    if semantic_evaluated:
        category_score = float(semantic_report.get("category_margin_score", 0.0))
        required_score = float(semantic_report.get("minimum_required_part_score", 0.0))
        forbidden_probability = float(semantic_report.get("forbidden_probability", 0.0))
        semantic_completeness_score = _clip01(
            0.25 * category_score
            + 0.60 * required_score
            + 0.15 * (1.0 - forbidden_probability)
        )
        semantic_part_floor = min(
            category_score, required_score, 1.0 - forbidden_probability
        )
    else:
        category_score = None
        required_score = None
        forbidden_probability = None
        semantic_completeness_score = 0.5
        semantic_part_floor = 0.5

    form_report = form_report if isinstance(form_report, dict) else {}
    form_score = (
        float(form_report.get("score", 0.5))
        if form_report.get("evaluated")
        else 0.5
    )
    alpha_metadata = alpha_metadata if isinstance(alpha_metadata, dict) else {}
    alpha_quality = alpha_metadata.get("alpha_quality")
    alpha_quality = alpha_quality if isinstance(alpha_quality, dict) else {}
    chroma = alpha_quality.get("chroma_spill_hygiene")
    chroma = chroma if isinstance(chroma, dict) else {}

    hard_failures: list[str] = []
    if alpha_quality and not bool(alpha_quality.get("ok", False)):
        hard_failures.append("alpha_quality_failed")
    if chroma and not bool(chroma.get("ok", False)):
        hard_failures.append("chroma_spill_hygiene_failed")
    if frame_clearance <= 0.002:
        hard_failures.append("foreground_touches_frame")
    if foreground_ratio < 0.01:
        hard_failures.append("foreground_too_small")
    if detached_ratio > 0.35:
        hard_failures.append("severe_detached_structure")
    maximum_forbidden_probability = 0.50
    if (
        semantic_evaluated
        and forbidden_probability is not None
        and forbidden_probability > maximum_forbidden_probability
    ):
        hard_failures.append("forbidden_part_probability_too_high")

    evidence_scores = {
        "framing": _clip01(framing_score),
        "segmentation_certainty": _clip01(segmentation_score),
        "structure_coherence": _clip01(structure_score),
        "semantic_completeness": _clip01(semantic_completeness_score),
        "contract_form": _clip01(form_score),
    }
    weighted_score = (
        0.18 * evidence_scores["framing"]
        + 0.20 * evidence_scores["segmentation_certainty"]
        + 0.30 * evidence_scores["structure_coherence"]
        + 0.22 * evidence_scores["semantic_completeness"]
        + 0.10 * evidence_scores["contract_form"]
    )
    reliability_floor = min(
        evidence_scores["framing"],
        evidence_scores["segmentation_certainty"],
        evidence_scores["structure_coherence"],
        _clip01(semantic_part_floor),
    )
    uncertainty_penalty = 0.06 if not semantic_evaluated else 0.0
    score = _clip01(
        0.65 * weighted_score + 0.35 * reliability_floor - uncertainty_penalty
    )
    return {
        "schema": GENERABILITY_SCHEMA,
        "evaluated": True,
        "image_path": str(image_path),
        "hard_gate_passed": not hard_failures,
        "hard_failures": hard_failures,
        "score": round(score, 6),
        "weighted_evidence_score": round(weighted_score, 6),
        "reliability_floor": round(reliability_floor, 6),
        "uncertainty_penalty": round(uncertainty_penalty, 6),
        "evidence_scores": {
            key: round(value, 6) for key, value in evidence_scores.items()
        },
        "evidence": {
            "foreground_ratio": round(foreground_ratio, 6),
            "frame_clearance_ratio": round(frame_clearance, 6),
            "partial_alpha_ratio": round(partial_ratio, 6),
            "alpha_ambiguity_weight_ratio": round(ambiguity_weight_ratio, 6),
            "detached_component_ratio": round(detached_ratio, 6),
            "opening_retention": round(opening_retention, 6),
            "lower_platform": platform,
            "semantic_evaluated": semantic_evaluated,
            "category_margin_score": category_score,
            "minimum_required_part_score": required_score,
            "semantic_part_floor": round(float(semantic_part_floor), 6),
            "forbidden_probability": forbidden_probability,
            "maximum_forbidden_probability": maximum_forbidden_probability,
            "alpha_quality_evaluated": bool(alpha_quality),
            "chroma_hygiene_evaluated": bool(chroma),
        },
        "category_specific_branching": False,
        "limitations": [
            "2D evidence predicts reconstruction risk but cannot prove 3D topology",
            "semantic evidence is frozen zero-shot evidence, not human ground truth",
            "thresholds are engineering safety bounds and require held-out blind validation",
        ],
    }


def select_vnext_candidate(
    candidates: Iterable[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Select by balanced generability evidence without category-specific rules."""

    rows = [candidate for candidate in candidates if isinstance(candidate, dict)]
    if not rows:
        raise ValueError("vNext selection requires at least one candidate")
    eligible = [
        candidate
        for candidate in rows
        if bool(
            (candidate.get("scene_dna_candidate_score", {}).get("generability") or {}).get(
                "hard_gate_passed"
            )
        )
    ]
    pool = eligible or rows

    def _key(candidate: dict[str, Any]) -> tuple[float, float, float, int]:
        score = candidate.get("scene_dna_candidate_score")
        score = score if isinstance(score, dict) else {}
        generability = score.get("generability")
        generability = generability if isinstance(generability, dict) else {}
        return (
            float(generability.get("reliability_floor", -1.0) or -1.0),
            float(generability.get("score", -1.0) or -1.0),
            float(score.get("score", -1.0) or -1.0),
            -int(candidate.get("attempt", 0) or 0),
        )

    selected = max(pool, key=_key)
    current = max(
        rows,
        key=lambda candidate: (
            float(
                (candidate.get("scene_dna_candidate_score") or {}).get("score", -1.0)
                or -1.0
            ),
            -int(candidate.get("attempt", 0) or 0),
        ),
    )
    ranking = sorted(rows, key=_key, reverse=True)
    return selected, {
        "schema": VNEXT_SELECTION_SCHEMA,
        "enabled": True,
        "selected_reference_job_id": selected.get("reference_job_id"),
        "current_selector_reference_job_id": current.get("reference_job_id"),
        "selection_changed": selected is not current,
        "hard_eligible_candidate_count": len(eligible),
        "all_candidates_failed_generability_gate": not eligible,
        "decision": (
            "select_balanced_generability_candidate"
            if eligible
            else "no_generability_eligible_candidate_reject_batch"
        ),
        "category_specific_branching": False,
        "selection_order": [
            "hard_generability_gate",
            "weakest_evidence_floor",
            "balanced_generability_score",
            "current_semantic_form_style_score",
            "stable_attempt_order",
        ],
        "ranking": [
            {
                "rank": index,
                "reference_job_id": candidate.get("reference_job_id"),
                "attempt": candidate.get("attempt"),
                "hard_gate_passed": bool(
                    (
                        candidate.get("scene_dna_candidate_score", {}).get(
                            "generability"
                        )
                        or {}
                    ).get("hard_gate_passed")
                ),
                "generability_score": (
                    candidate.get("scene_dna_candidate_score", {}).get("generability")
                    or {}
                ).get("score"),
                "reliability_floor": (
                    candidate.get("scene_dna_candidate_score", {}).get("generability")
                    or {}
                ).get("reliability_floor"),
                "current_score": candidate.get("scene_dna_candidate_score", {}).get(
                    "score"
                ),
            }
            for index, candidate in enumerate(ranking, start=1)
        ],
        "status": "development_only_default_off_requires_new_seed_blind_validation",
    }
