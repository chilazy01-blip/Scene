from __future__ import annotations

import hashlib
import json
import random
from copy import deepcopy
from typing import Any


BOOK_PALETTES: dict[str, list[list[float]]] = {
    "warm_jewel": [
        [0.48, 0.12, 0.09, 1.0],
        [0.12, 0.31, 0.35, 1.0],
        [0.67, 0.42, 0.10, 1.0],
        [0.24, 0.18, 0.43, 1.0],
        [0.18, 0.38, 0.24, 1.0],
    ],
    "muted_pastel": [
        [0.63, 0.42, 0.38, 1.0],
        [0.42, 0.55, 0.56, 1.0],
        [0.66, 0.58, 0.40, 1.0],
        [0.48, 0.43, 0.58, 1.0],
        [0.45, 0.57, 0.43, 1.0],
    ],
    "natural_neutral": [
        [0.35, 0.20, 0.10, 1.0],
        [0.58, 0.43, 0.25, 1.0],
        [0.27, 0.34, 0.31, 1.0],
        [0.50, 0.30, 0.18, 1.0],
        [0.32, 0.27, 0.22, 1.0],
    ],
}


def _stable_seed(row_id: str, seed: int) -> int:
    digest = hashlib.sha256(f"{row_id}:{seed}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def compose_upright_book_row(
    *,
    row_id: str,
    container_id: str,
    slot_id: str,
    dimensions: dict[str, float],
    count: int = 5,
    palette_id: str = "warm_jewel",
    seed: int = 0,
) -> dict[str, Any]:
    """Create a static row from individually named upright book components.

    This is deliberately a rigid composition contract.  It preserves separate
    child geometry/material identity today, while avoiding unsupported claims
    about friction, tipping, or dynamically stable leaning stacks.
    """

    if count < 1:
        raise ValueError("book row count must be positive")
    if palette_id not in BOOK_PALETTES:
        raise ValueError(f"unsupported book palette: {palette_id}")
    width = float(dimensions["width"])
    length = float(dimensions["length"])
    height = float(dimensions["height"])
    if min(width, length, height) <= 0.0:
        raise ValueError("book row dimensions must be positive")
    gap = min(0.008, width * 0.018)
    usable_width = width - gap * (count - 1)
    if usable_width <= count * 0.018:
        raise ValueError("book row is too narrow for the requested count")

    rng = random.Random(_stable_seed(row_id, seed))
    weights = [0.82 + rng.random() * 0.36 for _ in range(count)]
    total_weight = sum(weights)
    book_widths = [usable_width * value / total_weight for value in weights]
    palette = BOOK_PALETTES[palette_id]
    cursor = -width / 2.0
    books: list[dict[str, Any]] = []
    for index, book_width in enumerate(book_widths):
        book_height = height * (0.78 + 0.22 * rng.random())
        book_depth = length * (0.82 + 0.18 * rng.random())
        center_x = cursor + book_width / 2.0
        books.append(
            {
                "component_id": f"{row_id}_book_{index + 1:02d}",
                "category": "single_book",
                "role": f"book_{index + 1:02d}",
                "dimensions": {
                    "width": round(book_width, 6),
                    "length": round(book_depth, 6),
                    "height": round(book_height, 6),
                },
                "local_pose": {
                    "x": round(center_x, 6),
                    "y": round((length - book_depth) / 2.0, 6),
                    "z": 0.0,
                    "yaw_degrees": 0.0,
                    "pitch_degrees": 0.0,
                    "roll_degrees": 0.0,
                },
                "cover_color": deepcopy(palette[index % len(palette)]),
                "page_color": [0.82, 0.76, 0.63, 1.0],
            }
        )
        cursor += book_width + gap

    document = {
        "schema": "scene-v2-upright-book-row/v1",
        "row_id": row_id,
        "category": "book_stack",
        "container_id": container_id,
        "slot_id": slot_id,
        "arrangement": "upright_single_depth_row",
        "count_contract": {
            "component_category": "single_book",
            "expected_count": count,
            "count_mode": "exactly",
            "maximum_depth_layers": 1,
        },
        "dimensions": {key: float(dimensions[key]) for key in ("width", "length", "height")},
        "gap_m": gap,
        "palette_id": palette_id,
        "books": books,
        "rigid_composition": True,
        "dynamic_physics_status": "deferred_until_friction_and_contact_modeling",
    }
    document["audit"] = audit_upright_book_row(document)
    if not document["audit"]["ok"]:
        raise RuntimeError(json.dumps(document["audit"], ensure_ascii=False))
    return document


def audit_upright_book_row(document: dict[str, Any]) -> dict[str, Any]:
    dimensions = document.get("dimensions") or {}
    books = [item for item in document.get("books", []) if isinstance(item, dict)]
    expected = int(
        (document.get("count_contract") or {}).get("expected_count", 0) or 0
    )
    violations: list[dict[str, Any]] = []
    if len(books) != expected:
        violations.append(
            {"type": "exact_component_count", "expected": expected, "actual": len(books)}
        )
    intervals: list[tuple[float, float, str]] = []
    y_centers: list[float] = []
    for book in books:
        component_id = str(book.get("component_id") or "")
        dims = book.get("dimensions") or {}
        pose = book.get("local_pose") or {}
        width = float(dims.get("width", 0.0) or 0.0)
        depth = float(dims.get("length", 0.0) or 0.0)
        height = float(dims.get("height", 0.0) or 0.0)
        x = float(pose.get("x", 0.0) or 0.0)
        y = float(pose.get("y", 0.0) or 0.0)
        y_centers.append(y)
        if min(width, depth, height) <= 0.0:
            violations.append({"type": "non_positive_book_dimensions", "component_id": component_id})
        if any(abs(float(pose.get(axis, 0.0) or 0.0)) > 1e-6 for axis in ("pitch_degrees", "roll_degrees")):
            violations.append({"type": "not_upright", "component_id": component_id})
        if abs(x) + width / 2.0 > float(dimensions.get("width", 0.0)) / 2.0 + 1e-6:
            violations.append({"type": "outside_row_width", "component_id": component_id})
        if abs(y) + depth / 2.0 > float(dimensions.get("length", 0.0)) / 2.0 + 1e-6:
            violations.append({"type": "outside_row_depth", "component_id": component_id})
        if height > float(dimensions.get("height", 0.0)) + 1e-6:
            violations.append({"type": "outside_row_height", "component_id": component_id})
        intervals.append((x - width / 2.0, x + width / 2.0, component_id))
    intervals.sort()
    for left, right in zip(intervals, intervals[1:]):
        if left[1] > right[0] + 1e-6:
            violations.append(
                {"type": "book_overlap", "left": left[2], "right": right[2]}
            )
    if y_centers and max(y_centers) - min(y_centers) > float(dimensions.get("length", 0.0)) * 0.25:
        violations.append({"type": "multiple_depth_layers"})
    ids = [str(item.get("component_id") or "") for item in books]
    if len(ids) != len(set(ids)) or any(not item for item in ids):
        violations.append({"type": "component_identity_not_unique"})
    return {
        "schema": "scene-v2-upright-book-row-audit/v1",
        "ok": not violations,
        "component_count": len(books),
        "upright_count": sum(
            1
            for item in books
            if abs(float((item.get("local_pose") or {}).get("pitch_degrees", 0.0) or 0.0)) <= 1e-6
            and abs(float((item.get("local_pose") or {}).get("roll_degrees", 0.0) or 0.0)) <= 1e-6
        ),
        "depth_layer_count": 1 if books and not any(v["type"] == "multiple_depth_layers" for v in violations) else 0,
        "violations": violations,
    }
