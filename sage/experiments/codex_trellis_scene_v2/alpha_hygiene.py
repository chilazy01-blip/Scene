from __future__ import annotations

from typing import Any

import numpy as np
from PIL import Image
from scipy.ndimage import binary_dilation, binary_erosion, distance_transform_edt


DEFAULT_REVIEW_BACKGROUND_RGB = (224, 224, 224)


def recorded_alpha_background_rgb(
    alpha_metadata: dict[str, Any] | None,
) -> list[float] | None:
    """Read private source-matte provenance from bridge alpha metadata."""

    if not isinstance(alpha_metadata, dict):
        return None
    quality = alpha_metadata.get("alpha_quality")
    if not isinstance(quality, dict):
        return None
    hygiene = quality.get("chroma_spill_hygiene")
    if not isinstance(hygiene, dict):
        return None
    background = hygiene.get("background_rgb")
    if background is None:
        estimate = hygiene.get("background_estimate")
        if isinstance(estimate, dict) and estimate.get("evaluated"):
            background = estimate.get("background_rgb")
    if not isinstance(background, (list, tuple)) or len(background) != 3:
        return None
    return [float(value) for value in background]


def _as_rgba_array(image: Image.Image | np.ndarray) -> np.ndarray:
    if isinstance(image, Image.Image):
        return np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()
    array = np.asarray(image, dtype=np.uint8)
    if array.ndim != 3 or array.shape[2] != 4:
        raise ValueError("expected an RGBA image")
    return array.copy()


def estimate_hidden_background_rgb(
    image: Image.Image | np.ndarray,
    *,
    foreground_alpha_threshold: int = 24,
    ring_radius: int = 4,
) -> dict[str, Any]:
    """Estimate a removed uniform background from RGB hidden under alpha zero.

    RMBG preserves the source RGB values under transparent pixels.  Sampling a
    narrow outside ring avoids the black transparent canvas introduced when a
    cutout is recentered.
    """

    rgba = _as_rgba_array(image)
    alpha = rgba[:, :, 3]
    foreground = alpha > int(foreground_alpha_threshold)
    if not np.any(foreground) or np.all(alpha == 255):
        return {"evaluated": False, "reason": "no_transparent_foreground_boundary"}
    outside_ring = binary_dilation(foreground, iterations=max(1, ring_radius))
    outside_ring &= ~foreground
    # Only fully transparent pixels can provide unambiguous evidence about the
    # removed source background.  Near-transparent pixels (alpha 1..8) are
    # commonly object-coloured Lanczos/RMBG antialiasing.  Sampling them makes
    # a second pass mistake warm/yellow subject edges for a chroma background.
    outside_ring &= alpha == 0
    pixels = rgba[:, :, :3][outside_ring].astype(np.float32)
    # A recentered canvas uses transparent black. It is not the generated
    # background and must not dominate the estimate.
    pixels = pixels[np.max(pixels, axis=1) > 8.0] if len(pixels) else pixels
    if len(pixels) < 16:
        return {
            "evaluated": False,
            "reason": "insufficient_hidden_background_samples",
            "sample_count": int(len(pixels)),
        }
    background = np.median(pixels, axis=0)
    distances = np.linalg.norm(pixels - background[None, :], axis=1)
    median_distance = float(np.median(distances))
    coherent_fraction = float(np.mean(distances <= max(18.0, median_distance * 3.0)))
    chroma_range = float(np.max(background) - np.min(background))
    return {
        "evaluated": True,
        "background_rgb": [round(float(value), 3) for value in background],
        "sample_count": int(len(pixels)),
        "sample_alpha_max": 0,
        "median_rgb_distance": round(median_distance, 4),
        "coherent_fraction": round(coherent_fraction, 6),
        "chroma_range": round(chroma_range, 4),
        "chromatic_background": bool(chroma_range >= 40.0 and coherent_fraction >= 0.70),
    }


def edge_chroma_spill_report(
    image: Image.Image | np.ndarray,
    background_rgb: tuple[float, float, float] | list[float] | None,
    *,
    foreground_alpha_threshold: int = 24,
    edge_radius: int = 2,
) -> dict[str, Any]:
    rgba = _as_rgba_array(image)
    if background_rgb is None:
        return {"evaluated": False, "reason": "background_color_unavailable"}
    background = np.asarray(background_rgb, dtype=np.float32)
    background_chroma = background - float(np.mean(background))
    background_chroma_norm = float(np.linalg.norm(background_chroma))
    if background_chroma_norm < 28.0:
        return {
            "evaluated": True,
            "chromatic_background": False,
            "background_rgb": [round(float(value), 3) for value in background],
            "edge_spill_fraction": 0.0,
            "visible_spill_fraction": 0.0,
            "spill_pixel_count": 0,
        }
    alpha = rgba[:, :, 3].astype(np.float32) / 255.0
    foreground = rgba[:, :, 3] > int(foreground_alpha_threshold)
    eroded = binary_erosion(foreground, iterations=max(1, edge_radius))
    edge = foreground & ~eroded
    rgb = rgba[:, :, :3].astype(np.float32)
    chroma = rgb - np.mean(rgb, axis=2, keepdims=True)
    chroma_norm = np.linalg.norm(chroma, axis=2)
    alignment = np.sum(chroma * background_chroma[None, None, :], axis=2)
    alignment /= np.maximum(chroma_norm * background_chroma_norm, 1e-6)
    spill = edge & (chroma_norm >= 28.0) & (alignment >= 0.80)
    edge_count = int(np.count_nonzero(edge))
    spill_count = int(np.count_nonzero(spill))
    visible_edge_weight = float(np.sum(alpha[edge]))
    visible_spill_weight = float(np.sum(alpha[spill]))
    return {
        "evaluated": True,
        "chromatic_background": True,
        "background_rgb": [round(float(value), 3) for value in background],
        "edge_pixel_count": edge_count,
        "spill_pixel_count": spill_count,
        "edge_spill_fraction": round(spill_count / max(1, edge_count), 6),
        "visible_spill_fraction": round(
            visible_spill_weight / max(1e-6, visible_edge_weight), 6
        ),
    }


def audit_sanitized_alpha_edges(
    image: Image.Image | np.ndarray,
    background_rgb: tuple[float, float, float] | list[float] | None,
    *,
    foreground_alpha_threshold: int = 24,
    maximum_visible_spill_fraction: float = 0.12,
) -> dict[str, Any]:
    """Audit an already-sanitized cutout against its recorded source matte.

    Unlike :func:`clean_chromatic_alpha_edges`, this function never changes the
    image and never tries to infer a background from antialiased subject pixels.
    It is therefore safe to repeat after resizing and immediately before a
    blind-review image is composited.
    """

    rgba = _as_rgba_array(image)
    alpha = rgba[:, :, 3]
    hidden_rgb_nonzero = int(
        np.count_nonzero((alpha == 0) & np.any(rgba[:, :, :3] != 0, axis=2))
    )
    spill = edge_chroma_spill_report(
        rgba,
        background_rgb,
        foreground_alpha_threshold=foreground_alpha_threshold,
    )
    residual = float(spill.get("visible_spill_fraction", 0.0) or 0.0)
    reasons: list[str] = []
    if hidden_rgb_nonzero:
        reasons.append("nonzero_hidden_rgb_after_sanitization")
    if spill.get("chromatic_background") and residual > float(
        maximum_visible_spill_fraction
    ):
        reasons.append("residual_chromatic_edge_spill")
    return {
        "schema": "scene_dna_sanitized_alpha_chroma_audit_v1",
        "ok": not reasons,
        "background_rgb": (
            [round(float(value), 3) for value in background_rgb]
            if background_rgb is not None
            else None
        ),
        "spill": spill,
        "hidden_rgb_nonzero_pixel_count": hidden_rgb_nonzero,
        "maximum_visible_spill_fraction": float(maximum_visible_spill_fraction),
        "reasons": reasons,
    }


def clean_chromatic_alpha_edges(
    image: Image.Image | np.ndarray,
    *,
    foreground_alpha_threshold: int = 24,
    maximum_visible_spill_fraction: float = 0.12,
    maximum_alpha_weight_removed_fraction: float = 0.12,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Remove chroma-key RGB from transparent and antialiased edge pixels.

    The operation is deliberately limited to a coherent, strongly chromatic
    removed background. Fully transparent RGB is always zeroed so viewers that
    mishandle alpha cannot reveal the old background.
    """

    original = _as_rgba_array(image)
    rgba = original.copy()
    estimate = estimate_hidden_background_rgb(
        rgba, foreground_alpha_threshold=foreground_alpha_threshold
    )
    background = estimate.get("background_rgb") if estimate.get("evaluated") else None
    before = edge_chroma_spill_report(
        rgba,
        background,
        foreground_alpha_threshold=foreground_alpha_threshold,
    )
    alpha = rgba[:, :, 3].astype(np.float32)
    hidden_rgb_nonzero = int(
        np.count_nonzero((alpha == 0) & np.any(rgba[:, :, :3] != 0, axis=2))
    )
    rgba[:, :, :3][alpha == 0] = 0
    cleanup_applied = False
    alpha_weight_removed = 0.0
    if bool(estimate.get("chromatic_background")) and background is not None:
        bg = np.asarray(background, dtype=np.float32)
        rgb = original[:, :, :3].astype(np.float32)
        foreground = alpha > 0
        confident = alpha >= 245
        boundary = foreground & ~binary_erosion(
            alpha > foreground_alpha_threshold, iterations=3
        )
        distance_from_background = np.linalg.norm(rgb - bg[None, None, :], axis=2)
        background_mad = float(estimate.get("median_rgb_distance", 0.0))
        separation = max(50.0, min(90.0, 35.0 + background_mad * 3.0))
        similarity_alpha = np.clip(distance_from_background / separation, 0.0, 1.0)
        refined_alpha = alpha.copy()
        refined_alpha[boundary] = np.minimum(
            refined_alpha[boundary], refined_alpha[boundary] * similarity_alpha[boundary]
        )
        alpha_weight_removed = float(np.sum(alpha - refined_alpha)) / max(
            1.0, float(np.sum(alpha))
        )
        alpha = refined_alpha
        rgba[:, :, 3] = np.rint(alpha).astype(np.uint8)

        core = confident & (distance_from_background >= separation)
        edge_pixels = (alpha > 0) & (alpha < 245)
        if np.any(core) and np.any(edge_pixels):
            nearest = distance_transform_edt(~core, return_distances=False, return_indices=True)
            nearest_rgb = original[nearest[0], nearest[1], :3]
            rgba[:, :, :3][edge_pixels] = nearest_rgb[edge_pixels]
        rgba[:, :, :3][alpha == 0] = 0
        cleanup_applied = True

    after = edge_chroma_spill_report(
        rgba,
        background,
        foreground_alpha_threshold=foreground_alpha_threshold,
    )
    residual = float(after.get("visible_spill_fraction", 0.0) or 0.0)
    reasons: list[str] = []
    if after.get("chromatic_background") and residual > float(
        maximum_visible_spill_fraction
    ):
        reasons.append("residual_chromatic_edge_spill")
    if alpha_weight_removed > float(maximum_alpha_weight_removed_fraction):
        reasons.append("chroma_cleanup_removed_too_much_foreground")
    ok = not reasons
    return rgba, {
        "schema": "scene_dna_alpha_chroma_hygiene_v1",
        "ok": ok,
        "background_estimate": estimate,
        "before": before,
        "after": after,
        "cleanup_applied": cleanup_applied,
        "hidden_rgb_zeroed_pixel_count": hidden_rgb_nonzero,
        "alpha_weight_removed_fraction": round(alpha_weight_removed, 6),
        "maximum_visible_spill_fraction": float(maximum_visible_spill_fraction),
        "maximum_alpha_weight_removed_fraction": float(
            maximum_alpha_weight_removed_fraction
        ),
        "reasons": reasons,
    }


def composite_on_review_background(
    image: Image.Image | np.ndarray,
    *,
    background_rgb: tuple[int, int, int] = DEFAULT_REVIEW_BACKGROUND_RGB,
) -> Image.Image:
    rgba = Image.fromarray(_as_rgba_array(image), mode="RGBA")
    background = Image.new("RGBA", rgba.size, (*background_rgb, 255))
    return Image.alpha_composite(background, rgba).convert("RGB")
