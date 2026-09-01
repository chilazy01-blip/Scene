from __future__ import annotations

import math
from collections import deque
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from PIL import Image


SEMANTIC_FORM_SCHEMA = "scene_dna_semantic_form_contract_v1"
SEMANTIC_SCORE_SCHEMA = "scene_dna_semantic_score_v1"
FORM_SCORE_SCHEMA = "scene_dna_form_score_v1"


def _clip01(value: float) -> float:
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError(f"non-finite score: {numeric}")
    return max(0.0, min(1.0, numeric))


def _safe_mean(values: Iterable[float], default: float = 0.0) -> float:
    rows = [float(value) for value in values]
    return sum(rows) / len(rows) if rows else float(default)


def _sigmoid(value: float) -> float:
    value = max(-30.0, min(30.0, float(value)))
    return 1.0 / (1.0 + math.exp(-value))


def _foreground_mask(path: Path, alpha_threshold: int = 24) -> np.ndarray:
    rgba = np.asarray(Image.open(path).convert("RGBA"), dtype=np.uint8)
    return rgba[:, :, 3] > int(alpha_threshold)


def _component_areas(mask: np.ndarray, *, target: bool = True) -> list[int]:
    height, width = mask.shape
    visited = np.zeros(mask.shape, dtype=np.bool_)
    areas: list[int] = []
    for y in range(height):
        for x in range(width):
            if visited[y, x] or bool(mask[y, x]) is not target:
                continue
            queue: deque[tuple[int, int]] = deque([(y, x)])
            visited[y, x] = True
            area = 0
            while queue:
                cy, cx = queue.popleft()
                area += 1
                for ny, nx in (
                    (cy - 1, cx),
                    (cy + 1, cx),
                    (cy, cx - 1),
                    (cy, cx + 1),
                ):
                    if (
                        0 <= ny < height
                        and 0 <= nx < width
                        and not visited[ny, nx]
                        and bool(mask[ny, nx]) is target
                    ):
                        visited[ny, nx] = True
                        queue.append((ny, nx))
            areas.append(area)
    return sorted(areas, reverse=True)


def _hole_areas(crop: np.ndarray) -> list[int]:
    background = ~crop
    height, width = crop.shape
    exterior = np.zeros(crop.shape, dtype=np.bool_)
    queue: deque[tuple[int, int]] = deque()
    for x in range(width):
        if background[0, x]:
            queue.append((0, x))
        if background[height - 1, x]:
            queue.append((height - 1, x))
    for y in range(height):
        if background[y, 0]:
            queue.append((y, 0))
        if background[y, width - 1]:
            queue.append((y, width - 1))
    while queue:
        y, x = queue.popleft()
        if exterior[y, x] or not background[y, x]:
            continue
        exterior[y, x] = True
        for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            if 0 <= ny < height and 0 <= nx < width and not exterior[ny, nx]:
                queue.append((ny, nx))
    return _component_areas(background & ~exterior)


def extract_form_features(
    image_path: Path,
    *,
    alpha_threshold: int = 24,
) -> dict[str, Any]:
    mask = _foreground_mask(image_path, alpha_threshold)
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return {"evaluated": False, "reason": "empty_foreground"}
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    crop = mask[y0:y1, x0:x1]
    foreground_area = int(crop.sum())
    crop_area = int(crop.size)
    flipped = np.fliplr(crop)
    symmetry_union = int(np.count_nonzero(crop | flipped))
    symmetry = (
        float(np.count_nonzero(crop & flipped)) / float(symmetry_union)
        if symmetry_union
        else 0.0
    )
    holes = _hole_areas(crop)
    meaningful_holes = [area for area in holes if area >= max(12, int(crop_area * 0.002))]
    component_areas = _component_areas(crop)
    detached_ratio = 1.0 - float(component_areas[0]) / float(max(1, foreground_area))
    row_occupancy = crop.mean(axis=1)
    smoothed = np.convolve(row_occupancy, np.ones(5) / 5.0, mode="same")
    row_transitions = int(
        np.count_nonzero(np.abs(np.diff(smoothed)) >= 0.08)
    )
    column_occupancy = crop.mean(axis=0)
    narrow_axis_ratio = min(crop.shape) / float(max(crop.shape))
    end_width = max(1, int(crop.shape[1] * 0.20))

    def _mean_column_span(region: np.ndarray) -> float:
        spans: list[float] = []
        for column in range(region.shape[1]):
            occupied = np.flatnonzero(region[:, column])
            if len(occupied):
                spans.append(
                    float(occupied[-1] - occupied[0] + 1)
                    / float(max(1, crop.shape[0]))
                )
        return _safe_mean(spans, 0.0)

    maximum_end_height_ratio = max(
        _mean_column_span(crop[:, :end_width]),
        _mean_column_span(crop[:, -end_width:]),
    )
    return {
        "evaluated": True,
        "image_path": str(image_path),
        "bbox": [x0, y0, x1, y1],
        "bbox_aspect_ratio": round(float(x1 - x0) / float(max(1, y1 - y0)), 6),
        "bbox_fill_ratio": round(float(foreground_area) / float(crop_area), 6),
        "foreground_ratio": round(float(mask.mean()), 6),
        "bilateral_symmetry_iou": round(symmetry, 6),
        "internal_hole_count": len(meaningful_holes),
        "internal_hole_ratio": round(
            float(sum(meaningful_holes)) / float(max(1, crop_area)), 6
        ),
        "connected_component_count": len(component_areas),
        "detached_component_ratio": round(detached_ratio, 6),
        "horizontal_profile_transition_count": row_transitions,
        "row_occupancy_std": round(float(np.std(row_occupancy)), 6),
        "column_occupancy_std": round(float(np.std(column_occupancy)), 6),
        "narrow_axis_ratio": round(float(narrow_axis_ratio), 6),
        "maximum_end_height_ratio": round(maximum_end_height_ratio, 6),
    }


def _range_score(value: float, lower: float | None, upper: float | None) -> float:
    if lower is not None and value < lower:
        return math.exp(-4.0 * (lower - value) / max(0.05, abs(lower)))
    if upper is not None and value > upper:
        return math.exp(-4.0 * (value - upper) / max(0.05, abs(upper)))
    return 1.0


FORM_PROFILE_RULES: dict[str, dict[str, tuple[float | None, float | None]]] = {
    "compact_orthogonal": {
        "bbox_fill_ratio": (0.78, None),
        "bilateral_symmetry_iou": (0.70, None),
        "internal_hole_ratio": (None, 0.025),
        "detached_component_ratio": (None, 0.01),
    },
    "compact_layered": {
        "bbox_fill_ratio": (0.58, None),
        "bilateral_symmetry_iou": (0.60, None),
        "horizontal_profile_transition_count": (2.0, None),
        "detached_component_ratio": (None, 0.02),
    },
    "open_repeated_frame": {
        # A shelf may legitimately have an opaque back panel, so alpha fill
        # and transparent holes cannot be mandatory. Repeated horizontal
        # structure remains the profile-defining signal.
        "bbox_fill_ratio": (0.28, None),
        "bilateral_symmetry_iou": (0.55, None),
        "horizontal_profile_transition_count": (8.0, None),
        "detached_component_ratio": (None, 0.04),
    },
    "thin_compact": {
        "bbox_fill_ratio": (0.68, None),
        "bilateral_symmetry_iou": (0.65, None),
        "narrow_axis_ratio": (None, 0.72),
        "detached_component_ratio": (None, 0.015),
    },
    "skeletal_support": {
        "bbox_fill_ratio": (0.24, 0.76),
        "detached_component_ratio": (None, 0.045),
    },
    "slender_radial": {
        "bbox_aspect_ratio": (None, 0.90),
        "bilateral_symmetry_iou": (0.48, None),
        "bbox_fill_ratio": (0.20, 0.75),
        "detached_component_ratio": (None, 0.035),
    },
    "organic_branching": {
        "bbox_fill_ratio": (0.12, 0.72),
        "detached_component_ratio": (None, 0.08),
    },
    "paired_asymmetric": {
        "bbox_fill_ratio": (0.30, 0.84),
        "bilateral_symmetry_iou": (None, 0.92),
        "detached_component_ratio": (None, 0.025),
    },
    "open_back_footwear": {
        "bbox_aspect_ratio": (1.80, None),
        "maximum_end_height_ratio": (None, 0.50),
        "detached_component_ratio": (None, 0.025),
    },
}

FORM_PROFILE_HARD_RULES: dict[
    str, dict[str, tuple[float | None, float | None]]
] = {
    # This is the defining distinction from a closed shoe, not a soft style
    # preference, so it may not be averaged away by other good silhouette cues.
    "open_back_footwear": {
        "maximum_end_height_ratio": (None, 0.50),
    },
}


def score_form_contract(
    image_path: Path,
    contract: dict[str, Any],
    *,
    alpha_threshold: int = 24,
) -> dict[str, Any]:
    features = extract_form_features(image_path, alpha_threshold=alpha_threshold)
    profile = str(contract.get("shape_profile") or "general_object")
    rules = FORM_PROFILE_RULES.get(profile, {})
    if not features.get("evaluated"):
        return {
            "schema": FORM_SCORE_SCHEMA,
            "evaluated": False,
            "profile": profile,
            "score": 0.0,
            "gate_passed": False,
            "features": features,
        }
    rule_results: dict[str, Any] = {}
    scores: list[float] = []
    for feature, (lower, upper) in rules.items():
        value = float(features.get(feature, 0.0))
        score = _range_score(value, lower, upper)
        scores.append(score)
        rule_results[feature] = {
            "value": value,
            "minimum": lower,
            "maximum": upper,
            "score": round(score, 6),
            "passes": score >= 0.55,
        }
    score = _safe_mean(scores, 0.65)
    hard_rules = FORM_PROFILE_HARD_RULES.get(profile, {})
    hard_rule_results = {
        feature: {
            "value": float(features.get(feature, 0.0)),
            "minimum": lower,
            "maximum": upper,
            "passes": bool(
                (lower is None or float(features.get(feature, 0.0)) >= lower)
                and (upper is None or float(features.get(feature, 0.0)) <= upper)
            ),
        }
        for feature, (lower, upper) in hard_rules.items()
    }
    hard_rules_passed = all(
        item["passes"] for item in hard_rule_results.values()
    )
    gate_passed = bool(
        score >= 0.48
        and all(item["score"] >= 0.22 for item in rule_results.values())
        and hard_rules_passed
    )
    return {
        "schema": FORM_SCORE_SCHEMA,
        "evaluated": True,
        "profile": profile,
        "score": round(score, 6),
        "gate_passed": gate_passed,
        "features": features,
        "rules": rule_results,
        "hard_rules": hard_rule_results,
        "hard_rules_passed": hard_rules_passed,
        "limitations": "single-view alpha morphology; cannot prove full 3D topology",
    }


def _standardized_rgb(image_path: Path) -> Image.Image:
    rgba = Image.open(image_path).convert("RGBA")
    alpha = np.asarray(rgba)[:, :, 3]
    ys, xs = np.nonzero(alpha > 24)
    if len(xs):
        x0, x1 = int(xs.min()), int(xs.max()) + 1
        y0, y1 = int(ys.min()), int(ys.max()) + 1
        pad = max(4, int(max(x1 - x0, y1 - y0) * 0.08))
        rgba = rgba.crop(
            (
                max(0, x0 - pad),
                max(0, y0 - pad),
                min(rgba.width, x1 + pad),
                min(rgba.height, y1 + pad),
            )
        )
    background = Image.new("RGBA", rgba.size, (224, 224, 224, 255))
    background.alpha_composite(rgba)
    return background.convert("RGB")


class Siglip2SemanticScorer:
    """Lazy frozen SigLIP2 scorer; raw values remain auditable and uncalibrated."""

    def __init__(self, model_name_or_path: str, *, device: str = "cpu") -> None:
        self.model_name_or_path = str(model_name_or_path)
        self.device = str(device)
        self._model = None
        self._processor = None
        self._torch = None

    def _load(self) -> None:
        if self._model is not None:
            return
        import torch
        from transformers import Siglip2Model, Siglip2Processor

        self._processor = Siglip2Processor.from_pretrained(
            self.model_name_or_path, local_files_only=True
        )
        dtype = torch.float16 if self.device.startswith("cuda") else torch.float32
        self._model = Siglip2Model.from_pretrained(
            self.model_name_or_path,
            local_files_only=True,
            torch_dtype=dtype,
        ).to(self.device)
        self._model.eval()
        self._torch = torch

    def close(self) -> None:
        self._model = None
        self._processor = None
        torch_mod = self._torch
        self._torch = None
        if torch_mod is not None and torch_mod.cuda.is_available():
            torch_mod.cuda.empty_cache()

    def _logits(self, image: Image.Image, prompts: list[str]) -> list[float]:
        if not prompts:
            return []
        self._load()
        inputs = self._processor(
            text=prompts,
            images=image,
            padding="max_length",
            return_tensors="pt",
        )
        inputs = {key: value.to(self.device) for key, value in inputs.items()}
        with self._torch.inference_mode():
            outputs = self._model(**inputs)
            logits = outputs.logits_per_image[0]
        return [float(value) for value in logits.detach().float().cpu().tolist()]

    def score(self, image_path: Path, contract: dict[str, Any]) -> dict[str, Any]:
        identity = str(contract.get("identity") or "object").strip()
        required_parts = [
            str(part).strip()
            for part in contract.get("required_parts", [])
            if str(part).strip()
        ]
        core_description = identity
        if required_parts:
            core_description += " with " + ", ".join(required_parts)
        positive_queries = [
            f"a product photo of one complete {core_description}",
            *[
                f"a product photo of one {identity} with {part}"
                for part in required_parts
            ],
        ]
        negative_queries = [
            f"a product photo of one {item}"
            for item in contract.get("hard_negative_identities", [])
        ]
        forbidden_queries = [
            f"a product photo of one {identity} with {item}"
            for item in contract.get("forbidden_parts", [])
        ]
        required_absence_queries = [
            f"a product photo of one {identity} without a clearly visible {part}"
            for part in required_parts
        ]
        image = _standardized_rgb(image_path)
        # Score every text hypothesis in one model call.  Besides being much
        # faster on a frozen benchmark, this also guarantees that positive and
        # negative hypotheses see exactly the same encoded image batch.
        query_groups = (
            positive_queries,
            negative_queries,
            required_absence_queries,
            forbidden_queries,
        )
        all_queries = [query for group in query_groups for query in group]
        all_logits = self._logits(image, all_queries)
        group_logits: list[list[float]] = []
        offset = 0
        for group in query_groups:
            next_offset = offset + len(group)
            group_logits.append(all_logits[offset:next_offset])
            offset = next_offset
        (
            positive_logits,
            negative_logits,
            absence_logits,
            forbidden_logits,
        ) = group_logits
        identity_logit = positive_logits[0] if positive_logits else -30.0
        strongest_negative_logit = max(negative_logits, default=identity_logit)
        category_margin = _sigmoid(identity_logit - strongest_negative_logit)
        required_scores = [
            _sigmoid(present - absent)
            for present, absent in zip(positive_logits[1:], absence_logits)
        ]
        attribute_score = _safe_mean(required_scores, category_margin)
        forbidden_scores = [
            _sigmoid(forbidden - identity_logit)
            for forbidden in forbidden_logits
        ]
        forbidden_probability = max(forbidden_scores, default=0.0)
        minimum_required_score = min(required_scores, default=attribute_score)
        gate_config = contract.get("semantic_gate")
        gate_config = gate_config if isinstance(gate_config, dict) else {}
        minimum_category_margin = float(
            gate_config.get("minimum_category_margin", 0.42)
        )
        minimum_required_part_score = float(
            # Zero-shot part-vs-absence margins are useful for ranking but are
            # not calibrated as a universal hard gate. High-risk contracts
            # such as slippers opt in to an explicit non-zero threshold.
            gate_config.get("minimum_required_part_score", 0.0)
        )
        maximum_forbidden_probability = float(
            gate_config.get("maximum_forbidden_probability", 1.0)
        )
        score = _clip01(
            0.40 * category_margin
            + 0.45 * attribute_score
            + 0.10 * minimum_required_score
            + 0.05 * (1.0 - forbidden_probability)
        )
        return {
            "schema": SEMANTIC_SCORE_SCHEMA,
            "evaluated": True,
            "model": self.model_name_or_path,
            "identity": identity,
            "score": round(score, 6),
            "category_margin_score": round(category_margin, 6),
            "attribute_coverage_score": round(attribute_score, 6),
            "minimum_required_part_score": round(minimum_required_score, 6),
            "forbidden_probability": round(forbidden_probability, 6),
            "gate_passed": bool(
                category_margin >= minimum_category_margin
                and minimum_required_score >= minimum_required_part_score
                and forbidden_probability <= maximum_forbidden_probability
            ),
            "gate_thresholds": {
                "minimum_category_margin": minimum_category_margin,
                "minimum_required_part_score": minimum_required_part_score,
                "maximum_forbidden_probability": maximum_forbidden_probability,
            },
            "queries": {
                "positive_logits": dict(zip(positive_queries, positive_logits)),
                "negative_logits": dict(zip(negative_queries, negative_logits)),
                "required_absence_logits": dict(
                    zip(required_absence_queries, absence_logits)
                ),
                "forbidden_logits": dict(zip(forbidden_queries, forbidden_logits)),
                "required_part_margin_scores": dict(
                    zip(required_parts, required_scores)
                ),
                "forbidden_margin_scores": dict(
                    zip(contract.get("forbidden_parts", []), forbidden_scores)
                ),
            },
            "limitations": "frozen zero-shot image-text score; thresholds require blind-label calibration",
        }

    def score_text_contrast(
        self,
        image_path: Path,
        *,
        positive_prompts: list[str],
        negative_prompts: list[str],
        purpose: str,
    ) -> dict[str, Any]:
        """Score an auditable positive-vs-negative visual text contrast."""

        positives = [str(item) for item in positive_prompts if str(item).strip()]
        negatives = [str(item) for item in negative_prompts if str(item).strip()]
        if not positives or not negatives:
            return {
                "evaluated": False,
                "score": None,
                "purpose": purpose,
                "reason": "positive_and_negative_prompts_required",
            }
        image = _standardized_rgb(image_path)
        prompts = [*positives, *negatives]
        logits = self._logits(image, prompts)
        positive_logits = logits[: len(positives)]
        negative_logits = logits[len(positives) :]
        positive_logit = _safe_mean(positive_logits)
        strongest_negative = max(negative_logits)
        score = _sigmoid(positive_logit - strongest_negative)
        return {
            "schema": "scene_dna_text_contrast_score_v1",
            "evaluated": True,
            "purpose": str(purpose),
            "model": self.model_name_or_path,
            "score": round(score, 6),
            "positive_mean_logit": round(positive_logit, 6),
            "strongest_negative_logit": round(strongest_negative, 6),
            "positive_logits": dict(zip(positives, positive_logits)),
            "negative_logits": dict(zip(negatives, negative_logits)),
            "limitations": "frozen zero-shot contrast; threshold remains experimental until blind-label calibration",
        }


class DinoV3PrototypeScorer:
    """Compare a candidate with standardized renders of approved anchor assets."""

    def __init__(
        self,
        model_name_or_path: str,
        anchor_manifest: dict[str, Any],
        *,
        device: str = "cpu",
    ) -> None:
        self.model_name_or_path = str(model_name_or_path)
        self.anchor_manifest = anchor_manifest
        self.device = str(device)
        self._model = None
        self._processor = None
        self._torch = None
        self._embedding_cache: dict[str, np.ndarray] = {}

    def _load(self) -> None:
        if self._model is not None:
            return
        import torch
        from transformers import AutoImageProcessor, DINOv3ViTModel

        self._processor = AutoImageProcessor.from_pretrained(
            self.model_name_or_path, local_files_only=True
        )
        # This DINOv3 checkpoint produces non-finite CLS activations in fp16 on
        # the supported GPU stack. Casting an already-invalid activation to
        # fp32 cannot recover it, so keep the model computation itself in fp32.
        dtype = torch.float32
        self._model = DINOv3ViTModel.from_pretrained(
            self.model_name_or_path,
            local_files_only=True,
            torch_dtype=dtype,
        ).to(self.device)
        self._model.eval()
        self._torch = torch

    def close(self) -> None:
        self._model = None
        self._processor = None
        torch_mod = self._torch
        self._torch = None
        if torch_mod is not None and torch_mod.cuda.is_available():
            torch_mod.cuda.empty_cache()

    def _embedding(self, image_path: Path) -> np.ndarray:
        key = str(image_path.resolve())
        cached = self._embedding_cache.get(key)
        if cached is not None:
            return cached
        self._load()
        image = _standardized_rgb(image_path)
        inputs = self._processor(images=image, return_tensors="pt")
        pixel_values = inputs["pixel_values"].to(self.device)
        with self._torch.inference_mode():
            output = self._model(pixel_values=pixel_values)
            # DINO-family image retrieval uses the global/CLS token. Averaging all
            # tokens in fp16 was both less discriminative and produced NaNs on one
            # supported GPU stack; normalize in fp32 and reject non-finite output.
            vector = output.last_hidden_state[0, 0].float()
            vector = vector / vector.norm(p=2).clamp_min(1e-8)
        result = vector.detach().cpu().numpy().astype(np.float32)
        if not np.isfinite(result).all():
            raise ValueError(f"non-finite DINOv3 embedding for {image_path}")
        self._embedding_cache[key] = result
        return result

    def score(
        self,
        image_path: Path,
        contract: dict[str, Any],
    ) -> dict[str, Any]:
        identity = str(contract.get("identity") or "").replace("_", " ")
        profile = str(contract.get("shape_profile") or "general_object")
        anchors = [
            item
            for item in self.anchor_manifest.get("anchors", [])
            if isinstance(item, dict)
            and (
                str(item.get("identity") or "").replace("_", " ") == identity
                or str(item.get("shape_profile") or "") == profile
            )
        ]
        available_anchor_views = [
            (anchor, Path(str(raw_path)))
            for anchor in anchors
            for raw_path in anchor.get("image_paths", [])
            if Path(str(raw_path)).is_file()
        ]
        if not available_anchor_views:
            return {
                "evaluated": False,
                "score": None,
                "reason": "no_matching_approved_anchor_renders",
                "model": self.model_name_or_path,
            }
        candidate = self._embedding(image_path)
        comparisons: list[dict[str, Any]] = []
        for anchor, path in available_anchor_views:
            similarity = float(np.dot(candidate, self._embedding(path)))
            comparisons.append(
                {
                    "asset_id": str(anchor.get("asset_id") or ""),
                    "image_path": str(path),
                    "similarity": round(similarity, 6),
                    "match_basis": (
                        "identity"
                        if str(anchor.get("identity") or "").replace("_", " ")
                        == identity
                        else "shape_profile"
                    ),
                }
            )
        comparisons.sort(key=lambda item: float(item["similarity"]), reverse=True)
        top = comparisons[: min(4, len(comparisons))]
        cosine = _safe_mean([float(item["similarity"]) for item in top])
        return {
            "evaluated": True,
            "score": round(_clip01((cosine + 1.0) * 0.5), 6),
            "raw_cosine_mean_top4": round(cosine, 6),
            "model": self.model_name_or_path,
            "matched_anchor_view_count": len(comparisons),
            "top_matches": top,
            "limitations": "approved-render prototype similarity; not a category proof",
        }


def combine_semantic_form_style_scores(
    *,
    pixel_style_score: float,
    form_report: dict[str, Any] | None,
    semantic_report: dict[str, Any] | None,
    anchor_similarity_score: float | None = None,
) -> dict[str, Any]:
    facets: list[tuple[str, float, float]] = [
        ("pixel_style", float(pixel_style_score), 0.15),
    ]
    if isinstance(form_report, dict) and form_report.get("evaluated"):
        facets.append(("form", float(form_report.get("score", 0.0)), 0.30))
    if isinstance(semantic_report, dict) and semantic_report.get("evaluated"):
        facets.append(("semantic", float(semantic_report.get("score", 0.0)), 0.35))
    if anchor_similarity_score is not None:
        facets.append(("anchor_similarity", float(anchor_similarity_score), 0.20))
    denominator = sum(weight for _, _, weight in facets)
    score = sum(value * weight for _, value, weight in facets) / max(denominator, 1e-9)
    return {
        "score": round(_clip01(score), 6),
        "facets": {
            name: {"score": round(value, 6), "nominal_weight": weight}
            for name, value, weight in facets
        },
        "renormalized_weight_sum": round(denominator, 6),
        "semantic_embedding_evaluated": bool(
            isinstance(semantic_report, dict) and semantic_report.get("evaluated")
        ),
        "form_contract_evaluated": bool(
            isinstance(form_report, dict) and form_report.get("evaluated")
        ),
        "anchor_embedding_evaluated": anchor_similarity_score is not None,
    }


def selection_uncertainty(
    ranked_scores: list[float],
    *,
    margin_threshold: float = 0.03,
    scorer_conflict: bool = False,
) -> dict[str, Any]:
    margin = (
        float(ranked_scores[0]) - float(ranked_scores[1])
        if len(ranked_scores) >= 2
        else 1.0
    )
    uncertain = bool(len(ranked_scores) >= 2 and (margin < margin_threshold or scorer_conflict))
    return {
        "uncertain": uncertain,
        "top1_top2_margin": round(margin, 6),
        "margin_threshold": float(margin_threshold),
        "scorer_conflict": bool(scorer_conflict),
        "recommended_promotion_count": 2 if uncertain else 1,
    }


def form_improvement_guard(
    proposed_score: dict[str, Any],
    legacy_control_score: dict[str, Any],
    *,
    minimum_form_improvement: float = 0.08,
) -> dict[str, Any]:
    """Decide whether an experimental selector may replace its legacy control.

    This is a conservative development policy calibrated on the frozen 20260823
    three-reviewer data.  It is category independent and intentionally opt-in;
    a held-out benchmark is required before it can support an efficacy claim.
    """

    proposed_form = (
        proposed_score.get("form") if isinstance(proposed_score.get("form"), dict) else {}
    )
    control_form = (
        legacy_control_score.get("form")
        if isinstance(legacy_control_score.get("form"), dict)
        else {}
    )
    evaluated = bool(proposed_form.get("evaluated") and control_form.get("evaluated"))
    proposed_value = proposed_form.get("score")
    control_value = control_form.get("score")
    delta = (
        float(proposed_value) - float(control_value)
        if evaluated
        and isinstance(proposed_value, (int, float))
        and isinstance(control_value, (int, float))
        else None
    )
    accepted = bool(delta is not None and delta >= float(minimum_form_improvement))
    return {
        "schema": "scene_dna_form_improvement_guard_v1",
        "enabled": True,
        "accepted_proposed_selection": accepted,
        "decision": "keep_proposed" if accepted else "fallback_to_legacy_control",
        "minimum_form_improvement": float(minimum_form_improvement),
        "proposed_form_score": proposed_value,
        "legacy_control_form_score": control_value,
        "form_score_delta": round(delta, 6) if delta is not None else None,
        "form_scores_evaluated": evaluated,
        "category_specific_branching": False,
        "calibration_status": "development_only_requires_heldout_validation",
        "calibration_source": "scene_dna_20260823_v3_three_reviewer_frozen_results",
    }
