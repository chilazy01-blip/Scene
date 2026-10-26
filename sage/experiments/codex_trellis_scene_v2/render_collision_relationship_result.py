"""Render a presentation sheet for collision-aware scene results.

The sheet combines the final Blender preview with an auditable top-down view
derived from ``layout_plan_final.json``.  It intentionally distinguishes
near-contact clearance from geometric overlap so dense scenes do not imply a
collision pass merely because they look crowded.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont
from shapely.affinity import rotate, translate
from shapely.geometry import box


BACKGROUND = "#111820"
PANEL = "#19232d"
TEXT = "#edf2f5"
MUTED = "#9fb0bd"
TEAL = "#4cb9ad"
ORANGE = "#f3a44a"
BLUE = "#5ca6d8"
PURPLE = "#aa8bd8"
RED = "#ef6461"


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    return ImageFont.truetype(f"/usr/share/fonts/truetype/dejavu/{name}", size)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _object_polygon(obj: dict[str, Any]):
    dims = obj["dimensions"]
    shape = box(
        -float(dims["width"]) / 2.0,
        -float(dims["length"]) / 2.0,
        float(dims["width"]) / 2.0,
        float(dims["length"]) / 2.0,
    )
    shape = rotate(shape, float(obj.get("yaw", 0.0)), origin=(0.0, 0.0))
    return translate(shape, float(obj["x"]), float(obj["y"]))


def _relation_parts(raw: Any) -> tuple[str, str, str, dict[str, Any]] | None:
    if isinstance(raw, list) and len(raw) >= 3:
        return str(raw[0]), str(raw[1]), str(raw[2]), {}
    if isinstance(raw, dict):
        source = raw.get("source")
        kind = raw.get("type")
        target = raw.get("target")
        if source and kind and target:
            return str(source), str(kind), str(target), raw.get("parameters", {})
    return None


def _fit_image(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    target_w, target_h = size
    ratio = max(target_w / image.width, target_h / image.height)
    resized = image.resize(
        (round(image.width * ratio), round(image.height * ratio)),
        Image.Resampling.LANCZOS,
    )
    left = max(0, (resized.width - target_w) // 2)
    top = max(0, (resized.height - target_h) // 2)
    return resized.crop((left, top, left + target_w, top + target_h))


def _draw_dashed(
    draw: ImageDraw.ImageDraw,
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    fill: str,
    width: int = 2,
    dash: int = 8,
) -> None:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if length <= 0:
        return
    ux, uy = dx / length, dy / length
    cursor = 0.0
    while cursor < length:
        stop = min(cursor + dash, length)
        draw.line(
            (
                start[0] + ux * cursor,
                start[1] + uy * cursor,
                start[0] + ux * stop,
                start[1] + uy * stop,
            ),
            fill=fill,
            width=width,
        )
        cursor += dash * 1.8


def _boxes_overlap(left: tuple[float, float, float, float], right: tuple[float, float, float, float]) -> bool:
    return not (
        left[2] + 3 <= right[0]
        or right[2] + 3 <= left[0]
        or left[3] + 3 <= right[1]
        or right[3] + 3 <= left[1]
    )


def _place_label_box(
    center: tuple[float, float],
    size: tuple[float, float],
    occupied: list[tuple[float, float, float, float]],
    bounds: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    """Greedily place a compact map label without covering earlier labels."""

    width, height = size
    offsets = [(0, 0)]
    for radius in (18, 32, 48, 66, 86):
        offsets.extend(
            (dx, dy)
            for dx, dy in (
                (0, -radius), (0, radius), (-radius, 0), (radius, 0),
                (-radius, -radius), (radius, -radius), (-radius, radius), (radius, radius),
            )
        )
    for dx, dy in offsets:
        x0 = center[0] + dx - width / 2 - 4
        y0 = center[1] + dy - height / 2 - 3
        candidate = (x0, y0, x0 + width + 8, y0 + height + 6)
        if (
            candidate[0] >= bounds[0]
            and candidate[1] >= bounds[1]
            and candidate[2] <= bounds[2]
            and candidate[3] <= bounds[3]
            and not any(_boxes_overlap(candidate, prior) for prior in occupied)
        ):
            return candidate
    # Deterministic fallback keeps text inside the map even in pathological
    # density; callers can still identify the object through the leader line.
    x0 = min(max(center[0] - width / 2 - 4, bounds[0]), bounds[2] - width - 8)
    y0 = min(max(center[1] - height / 2 - 3, bounds[1]), bounds[3] - height - 6)
    return (x0, y0, x0 + width + 8, y0 + height + 6)


def render(run_dir: Path, preview_path: Path, output_path: Path) -> None:
    plan = _load(run_dir / "layout_plan_final.json")
    validation = _load(run_dir / "validation_final.json")
    graph = _load(run_dir / "scene_graph_final.json")
    generation_plan = _load(run_dir / "missing_asset_generation_plan.json")

    canvas = Image.new("RGB", (1800, 1120), BACKGROUND)
    draw = ImageDraw.Draw(canvas)
    title = _font(42, bold=True)
    subtitle = _font(21)
    heading = _font(24, bold=True)
    body = _font(18)
    small = _font(15)

    draw.text((54, 38), "Dense Living Room · Collision-aware Result", fill=TEXT, font=title)
    draw.text(
        (56, 92),
        "Final Blender render + validated footprints + relationship evidence",
        fill=MUTED,
        font=subtitle,
    )

    preview = _fit_image(Image.open(preview_path).convert("RGB"), (1070, 760))
    canvas.paste(preview, (50, 140))
    draw.rounded_rectangle((50, 140, 1120, 900), radius=8, outline="#50606d", width=2)
    draw.rectangle((50, 834, 1120, 900), fill="#111820d8")
    draw.text((76, 853), "FINAL ASSEMBLED SCENE", fill=TEXT, font=heading)
    draw.text((470, 858), "Tight clearances are intentional; overlaps are not.", fill=MUTED, font=body)

    panel = (1150, 140, 1750, 900)
    draw.rounded_rectangle(panel, radius=8, fill=PANEL, outline="#50606d", width=2)
    draw.text((1180, 166), "TOP-DOWN COLLISION MAP", fill=TEXT, font=heading)

    room = plan["room"]
    room_w, room_l = float(room["width"]), float(room["length"])
    map_box = (1190, 220, 1710, 660)
    scale = min((map_box[2] - map_box[0]) / room_w, (map_box[3] - map_box[1]) / room_l)
    origin_x = map_box[0] + ((map_box[2] - map_box[0]) - room_w * scale) / 2.0
    origin_y = map_box[1] + ((map_box[3] - map_box[1]) - room_l * scale) / 2.0

    def point(x: float, y: float) -> tuple[float, float]:
        return origin_x + x * scale, origin_y + (room_l - y) * scale

    draw.rectangle(
        (origin_x, origin_y, origin_x + room_w * scale, origin_y + room_l * scale),
        fill="#202d37",
        outline="#d7e0e6",
        width=3,
    )

    objects = {str(obj["id"]): obj for obj in plan["objects"]}
    polygons = {key: _object_polygon(value) for key, value in objects.items()}
    generated_ids = {
        str(item.get("object_id") or item.get("id"))
        for item in generation_plan.get("instances", generation_plan.get("objects", []))
        if isinstance(item, dict)
    }
    generated_ids.update(
        str(value) for value in generation_plan.get("new_asset_instances", []) if value
    )
    if not generated_ids:
        generated_ids = {
            key
            for key, obj in objects.items()
            if str(obj.get("asset_source", "")).startswith(("missing", "trellis"))
        }

    label_rows = []
    for object_id, obj in sorted(objects.items(), key=lambda item: float(item[1].get("z", 0.0))):
        polygon = polygons[object_id]
        coords = [point(float(x), float(y)) for x, y in polygon.exterior.coords]
        placement = str(obj.get("placement_type", "floor"))
        if object_id in generated_ids:
            fill = ORANGE
        elif placement in {"supported", "wall"} or obj.get("support_id"):
            fill = BLUE
        else:
            fill = TEAL
        if str(obj.get("category")) == "area_rug":
            fill = "#56636c"
        draw.polygon(coords, fill=fill, outline="#0c1116")
        center = point(float(obj["x"]), float(obj["y"]))
        label = object_id.replace("explicit_", "").replace("_", " ")
        if len(label) > 18:
            label = label[:16] + "…"
        bbox = draw.textbbox((0, 0), label, font=small)
        label_rows.append((center, label, bbox[2] - bbox[0], bbox[3] - bbox[1]))

    occupied_labels: list[tuple[float, float, float, float]] = []
    for center, label, label_width, label_height in label_rows:
        label_box = _place_label_box(
            center,
            (label_width, label_height),
            occupied_labels,
            (origin_x + 4, origin_y + 4, origin_x + room_w * scale - 4, origin_y + room_l * scale - 4),
        )
        occupied_labels.append(label_box)
        label_center = ((label_box[0] + label_box[2]) / 2, (label_box[1] + label_box[3]) / 2)
        if math.hypot(label_center[0] - center[0], label_center[1] - center[1]) > 10:
            draw.line((center, label_center), fill="#738592", width=1)
        draw.rounded_rectangle(label_box, radius=4, fill="#d9e2e7", outline="#26333d", width=1)
        draw.text((label_box[0] + 4, label_box[1] + 2), label, fill="#071016", font=small)

    clearance_rows: list[tuple[float, str, str]] = []
    support_count = 0
    relation_count = 0
    for raw in plan.get("relations", []):
        parts = _relation_parts(raw)
        if parts is None:
            continue
        source, kind, target, _ = parts
        relation_count += 1
        if source not in objects or target not in objects:
            continue
        a = point(float(objects[source]["x"]), float(objects[source]["y"]))
        b = point(float(objects[target]["x"]), float(objects[target]["y"]))
        if kind == "supported_by":
            support_count += 1
            _draw_dashed(draw, a, b, fill=BLUE, width=2, dash=5)
        elif kind == "mirror_symmetric":
            _draw_dashed(draw, a, b, fill=PURPLE, width=3, dash=9)
        elif kind == "clearance_from":
            distance = float(polygons[source].distance(polygons[target]))
            clearance_rows.append((distance, source, target))

    for index, (distance, source, target) in enumerate(sorted(clearance_rows)[:5]):
        a = point(float(objects[source]["x"]), float(objects[source]["y"]))
        b = point(float(objects[target]["x"]), float(objects[target]["y"]))
        _draw_dashed(draw, a, b, fill=ORANGE, width=3, dash=7)
        midpoint = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
        distance_label = f"{distance:.2f}m"
        distance_bbox = draw.textbbox((0, 0), distance_label, font=small)
        label_box = _place_label_box(
            midpoint,
            (distance_bbox[2] - distance_bbox[0], distance_bbox[3] - distance_bbox[1]),
            occupied_labels,
            (origin_x + 4, origin_y + 4, origin_x + room_w * scale - 4, origin_y + room_l * scale - 4),
        )
        occupied_labels.append(label_box)
        label_center = ((label_box[0] + label_box[2]) / 2, (label_box[1] + label_box[3]) / 2)
        if math.hypot(label_center[0] - midpoint[0], label_center[1] - midpoint[1]) > 10:
            draw.line((midpoint, label_center), fill=ORANGE, width=1)
        draw.rounded_rectangle(
            label_box,
            radius=7,
            fill="#10171d",
            outline=ORANGE,
        )
        draw.text((label_box[0] + 4, label_box[1] + 2), distance_label, fill=TEXT, font=small)

    draw.text((1180, 688), "LEGEND", fill=TEXT, font=heading)
    legend = [
        (ORANGE, "Newly built scene asset"),
        (TEAL, "Curated reusable asset"),
        (BLUE, "Supported / wall object"),
        (PURPLE, "Symmetry relation"),
    ]
    for index, (color, label) in enumerate(legend):
        y = 730 + index * 36
        draw.rounded_rectangle((1182, y, 1204, y + 22), radius=4, fill=color)
        draw.text((1218, y + 1), label, fill=MUTED, font=body)

    hard = int(validation.get("hard_violation_count", 0))
    soft = int(validation.get("soft_violation_count", 0))
    graph_relations = len(graph.get("relations", [])) or relation_count
    generated_types = int(
        generation_plan.get("new_asset_type_count")
        or generation_plan.get("unique_generation_count")
        or generation_plan.get("unique_asset_count")
        or len({objects[key].get("asset_generation_key") for key in generated_ids if key in objects})
    )
    metrics = [
        (str(len(objects)), "OBJECT INSTANCES"),
        (str(hard), "HARD COLLISIONS"),
        (str(graph_relations), "GRAPH RELATIONS"),
        (str(generated_types), "NEW ASSET TYPES"),
    ]
    x_positions = (55, 490, 925, 1360)
    for x, (value, label) in zip(x_positions, metrics, strict=True):
        draw.rounded_rectangle((x, 940, x + 385, 1068), radius=8, fill=PANEL, outline="#3a4b57")
        color = TEXT if label != "HARD COLLISIONS" or hard == 0 else RED
        draw.text((x + 24, 958), value, fill=color, font=_font(42, bold=True))
        draw.text((x + 24, 1016), label, fill=MUTED, font=body)

    status = "PASS" if hard == 0 else "FAIL"
    status_color = TEAL if hard == 0 else RED
    draw.rounded_rectangle((1530, 57, 1747, 108), radius=24, fill=status_color)
    draw.text((1570, 66), f"COLLISION {status}", fill="#071016", font=_font(19, bold=True))
    draw.text((1180, 872), f"{soft} soft affinity notes · {support_count} support links", fill=MUTED, font=small)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, quality=95)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--preview", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    render(args.run_dir.resolve(), args.preview.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
