"""Bound visible-background evidence for an unchanged native-alpha source.

The white composite is an audit input, never a replacement tool artifact or
TRELLIS input.  The bridge continues preparing the original RGBA pixels.
"""
from __future__ import annotations

from io import BytesIO
from copy import deepcopy
import os
from pathlib import Path
import tempfile
from typing import Any

import numpy as np
from PIL import Image

from .content_chain import content_hash, file_binding
import hashlib


SCHEMA = "scene-v2-native-alpha-source-normalization/v1"
EVIDENCE_SCHEMA = "scene-v2-image-trellis-reference-evidence/v3"
ALGORITHM = "straight-alpha-u8-white-round-half-up/v1"
POLICY = {
    "schema": SCHEMA,
    "scope": "native_alpha_source_white_audit_only",
    "algorithm": ALGORITHM,
    "white_rgb": [255, 255, 255],
    "alpha_preserved": True,
    "opacity_policy": "review-nonopaque-three-pixel-interior/v1",
    "decode_policy": "pillow-straight-u8-no-orientation-or-profile-transform/v1",
}
RECORD_NAMES = ("source_raw", "native_alpha_mask", "source_visible_white_rgb")


def record(path: Path) -> dict[str, Any]:
    return {"path": str(path.resolve()), **file_binding(path)}


def _pixel_hash(pixels: np.ndarray) -> str:
    return hashlib.sha256(pixels.tobytes()).hexdigest()


def decode_native_alpha(path: Path) -> tuple[np.ndarray, str] | None:
    with Image.open(path) as image:
        transparent = bool({"A", "a"}.intersection(image.getbands())) or "transparency" in image.info
        if not transparent:
            return None
        if image.mode not in {"RGBA", "LA", "P", "RGB", "L"}:
            raise ValueError("Unsupported native alpha representation")
        rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()
        if not np.any(rgba[:, :, 3] < 255):
            return None
        return rgba, image.mode


def visible_white_rgb(rgba: np.ndarray) -> np.ndarray:
    alpha = rgba[:, :, 3:4].astype(np.uint32)
    return ((rgba[:, :, :3].astype(np.uint32) * alpha
             + 255 * (255 - alpha) + 127) // 255).astype(np.uint8)


def opacity_audit(alpha: np.ndarray) -> dict[str, Any]:
    interior = alpha > 24
    for _ in range(3):
        padded = np.pad(interior, 1, constant_values=False)
        height, width = alpha.shape
        interior = np.logical_and.reduce([
            padded[y:y + height, x:x + width]
            for y in range(3) for x in range(3)
        ])
    count = int(interior.sum())
    nonopaque = int(np.count_nonzero(interior & (alpha < 255)))
    return {
        "policy": POLICY["opacity_policy"],
        "alpha_min": int(alpha.min()), "alpha_max": int(alpha.max()),
        "alpha_zero_count": int(np.count_nonzero(alpha == 0)),
        "alpha_255_count": int(np.count_nonzero(alpha == 255)),
        "interior_pixel_count": count,
        "nonopaque_interior_pixel_count": nonopaque,
        "review_required": count == 0 or nonopaque > 0,
    }


def opacity_review_ok(metadata: dict[str, Any]) -> bool:
    if not metadata["opacity_audit"]["review_required"]:
        return True
    review = metadata.get("opacity_review")
    return (isinstance(review, dict)
            and review.get("decision") == "accept"
            and review.get("source_raw_sha256") == metadata["records"]["source_raw"]["sha256"]
            and review.get("alpha_pixel_sha256") == metadata["alpha_pixel_sha256"]
            and all(isinstance(review.get(key), str) and review[key].strip()
                    for key in ("reviewer", "reason")))


def normalization_content_key(metadata: dict[str, Any]) -> str:
    content = {key: value for key, value in metadata.items() if key != "content_key"}
    content["records"] = {
        name: {key: value for key, value in bound.items() if key != "path"}
        for name, bound in metadata["records"].items()
    }
    return content_hash(content)


def write_immutable(path: Path, body: bytes) -> None:
    """Commit only new content; an existing different artifact is a conflict."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".native-alpha-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(name, path)
        except FileExistsError:
            if path.is_symlink() or path.read_bytes() != body:
                raise ValueError(f"Immutable native alpha evidence conflict: {path}")
    finally:
        Path(name).unlink(missing_ok=True)


def prepare_native_alpha_evidence(
    source_path: Path, output_dir: Path, job_id: str,
    *, review: dict[str, Any] | None = None,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]] | None:
    decoded = decode_native_alpha(source_path)
    if decoded is None:
        return None
    rgba, mode = decoded
    visible = visible_white_rgb(rgba)
    alpha = rgba[:, :, 3]
    source_record = record(source_path)
    # Raw hash prevents normalization under the same name from overwriting
    # another image. Immutable writes also catch differing review/encoding.
    directory = output_dir / "native_alpha" / job_id / source_record["sha256"]
    records = {"source_raw": source_record}
    for key, pixels, image_mode in (
        ("native_alpha_mask", alpha, "L"),
        ("source_visible_white_rgb", visible, "RGB"),
    ):
        stream = BytesIO()
        Image.fromarray(pixels, mode=image_mode).save(stream, format="PNG", optimize=False, compress_level=6)
        path = directory / f"{key}.png"
        write_immutable(path, stream.getvalue())
        records[key] = record(path)
    metadata = {
        **deepcopy(POLICY), "records": records, "raw_mode": mode,
        "raw_size": [rgba.shape[1], rgba.shape[0]],
        "alpha_pixel_sha256": _pixel_hash(alpha),
        "visible_rgb_pixel_sha256": _pixel_hash(visible),
        "opacity_audit": opacity_audit(alpha),
        "opacity_review": review,
    }
    metadata["content_key"] = normalization_content_key(metadata)
    # No call to Image.save or any write targets the raw source.
    if record(source_path) != source_record:
        raise ValueError("Raw native alpha source changed while normalizing")
    return rgba, visible, metadata


def validate_native_alpha_normalization(
    metadata: Any, files: dict[str, Any], *, require_review: bool = True,
) -> list[str]:
    """Recompute the visible composite; rebinding arbitrary hashes cannot pass."""
    failures: list[str] = []
    if not isinstance(metadata, dict):
        return ["native_alpha_normalization_metadata"]
    try:
        if any(metadata.get(key) != value for key, value in POLICY.items()):
            failures.append("native_alpha_normalization_policy")
        records = metadata["records"]
        if set(records) != set(RECORD_NAMES):
            failures.append("native_alpha_normalization_records")
        for name in RECORD_NAMES:
            if records[name] != files.get(name) or record(Path(records[name]["path"])) != records[name]:
                failures.append(f"native_alpha_normalization_binding:{name}")
        if files.get("source_rgb") != records["source_raw"]:
            failures.append("native_alpha_raw_alias")
        decoded = decode_native_alpha(Path(records["source_raw"]["path"]))
        if decoded is None:
            return failures + ["native_alpha_missing_from_raw"]
        rgba, mode = decoded
        alpha, visible = rgba[:, :, 3], visible_white_rgb(rgba)
        if metadata.get("raw_mode") != mode or metadata.get("raw_size") != [rgba.shape[1], rgba.shape[0]]:
            failures.append("native_alpha_raw_decode")
        for name, expected, expected_mode, hash_key in (
            ("native_alpha_mask", alpha, "L", "alpha_pixel_sha256"),
            ("source_visible_white_rgb", visible, "RGB", "visible_rgb_pixel_sha256"),
        ):
            with Image.open(records[name]["path"]) as image:
                if image.mode != expected_mode or not np.array_equal(np.asarray(image), expected):
                    failures.append(f"native_alpha_recompute:{name}")
            if metadata.get(hash_key) != _pixel_hash(expected):
                failures.append(f"native_alpha_pixel_hash:{name}")
        if metadata.get("opacity_audit") != opacity_audit(alpha):
            failures.append("native_alpha_opacity_audit")
        if require_review and not opacity_review_ok(metadata):
            failures.append("native_alpha_opacity_review_required")
        if metadata.get("content_key") != normalization_content_key(metadata):
            failures.append("native_alpha_normalization_content_key")
    except (OSError, ValueError, TypeError, KeyError, IndexError):
        failures.append("native_alpha_normalization_invalid")
    return list(dict.fromkeys(failures))
