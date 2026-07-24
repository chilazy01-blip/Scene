from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from .io_utils import read_json, run_codex_image_json, write_json


INVENTORY_AUDIT_SCHEMA = "codex_trellis_reference_inventory_audit_v1"
COMPARISON_SCHEMA = "codex_trellis_reference_image_model_comparison_v1"
WALLS = {"north", "south", "east", "west", "interior", "uncertain"}


def build_inventory_audit_prompt(brief: dict[str, Any]) -> str:
    catalog = [
        {
            "id": obj["id"],
            "category": obj["category"],
            "expected_count": 1,
            "preferred_wall": obj.get("preferred_wall"),
        }
        for obj in brief.get("objects", [])
        if obj.get("placement_type") != "support"
    ]
    architecture = brief.get("architecture", {})
    expected_architecture = {
        "door_walls": [
            door.get("wall")
            for door in architecture.get("doors", [])
            if isinstance(door, dict)
        ],
        "window_walls": [
            window.get("wall")
            for window in architecture.get("windows", [])
            if isinstance(window, dict)
        ],
    }
    return f"""
Audit the attached generated room image against this exact scene contract.
Count visible instances before assigning catalog ids. Treat integrated desk drawers as part of the
desk, but count independent drawer chests, cabinets, shelves, chairs, lamps, plants, and wall art.
Do not excuse an extra object because it is aesthetically plausible.

Exact catalog:
{json.dumps(catalog, indent=2, ensure_ascii=False)}

Expected relations:
{json.dumps(brief.get("relations", []), ensure_ascii=False)}

Expected architecture:
{json.dumps(expected_architecture, ensure_ascii=False)}

Return only JSON:
{{
  "schema": "{INVENTORY_AUDIT_SCHEMA}",
  "catalog": [
    {{
      "id": "exact catalog id",
      "visible_instance_count": 0,
      "count_confidence": 0.0,
      "observed_wall": "north|south|east|west|interior|uncertain",
      "wall_confidence": 0.0,
      "evidence": "short evidence"
    }}
  ],
  "relations": [
    {{
      "source": "exact id",
      "type": "relation type",
      "target": "exact id",
      "satisfied": true,
      "confidence": 0.0,
      "evidence": "short evidence"
    }}
  ],
  "architecture": {{
    "door_walls": ["north|south|east|west"],
    "window_walls": ["north|south|east|west"],
    "confidence": 0.0
  }},
  "unexpected_objects": [
    {{
      "category": "plain category",
      "count": 1,
      "kind": "major_furniture|accessory|decor|architecture|unknown",
      "confidence": 0.0,
      "evidence": "short evidence"
    }}
  ],
  "warnings": ["ambiguity"]
}}

Rules:
- Emit every exact catalog id once, including missing or duplicated categories.
- visible_instance_count is the number of visually matching independent instances, not the expected count.
- If two instances could both be the catalog object, report count 2 rather than selecting one.
- unexpected_objects contains every visible object outside the exact catalog, grouped by category.
- major_furniture means independent chairs, cabinets, drawer chests, shelves, tables, desks, beds,
  sofas, or floor lamps. accessory means desk lamps, computers, storage bins, and other small
  movable objects. Plants, wall art, and rugs are decor.
- A small desk lamp is an accessory when the catalog contains only a floor lamp.
- Do not list books inside the expected bookcase as unexpected; stocked books are implied contents.
- Do not list drawers structurally integrated into the expected desk or cabinet as separate objects.
- Camera was requested at the south wall looking north: image-left is west and image-right is east.
- Use "uncertain" and lower confidence when perspective prevents a wall assignment.
- Do not include markdown or prose outside JSON.
""".strip()


def _relation_key(relation: Any) -> tuple[str, str, str] | None:
    if isinstance(relation, list) and len(relation) >= 3:
        return str(relation[0]), str(relation[1]), str(relation[2])
    if isinstance(relation, dict):
        source = str(relation.get("source") or "")
        relation_type = str(relation.get("type") or "")
        target = str(relation.get("target") or "")
        if source and relation_type and target:
            return source, relation_type, target
    return None


def summarize_inventory_audit(
    raw: Any,
    brief: dict[str, Any],
    *,
    minimum_confidence: float = 0.6,
) -> dict[str, Any]:
    expected_objects = {
        str(obj["id"]): obj
        for obj in brief.get("objects", [])
        if obj.get("placement_type") != "support"
    }
    observed_catalog = {
        str(item.get("id")): item
        for item in raw.get("catalog", [])
        if isinstance(raw, dict)
        and isinstance(item, dict)
        and str(item.get("id") or "") in expected_objects
    }
    object_results: list[dict[str, Any]] = []
    exact_count_count = 0
    missing_instance_count = 0
    duplicate_instance_count = 0
    wall_expected_count = 0
    wall_correct_count = 0
    for object_id, spec in expected_objects.items():
        observed = observed_catalog.get(object_id, {})
        try:
            visible_count = max(0, int(observed.get("visible_instance_count", 0)))
        except (TypeError, ValueError):
            visible_count = 0
        try:
            count_confidence = float(observed.get("count_confidence", 0.0))
        except (TypeError, ValueError):
            count_confidence = 0.0
        count_usable = count_confidence >= float(minimum_confidence)
        count_correct = visible_count == 1 and count_usable
        exact_count_count += int(count_correct)
        if count_usable:
            missing_instance_count += max(0, 1 - visible_count)
            duplicate_instance_count += max(0, visible_count - 1)
        preferred_wall = str(spec.get("preferred_wall") or "")
        observed_wall = str(observed.get("observed_wall") or "uncertain")
        if observed_wall not in WALLS:
            observed_wall = "uncertain"
        try:
            wall_confidence = float(observed.get("wall_confidence", 0.0))
        except (TypeError, ValueError):
            wall_confidence = 0.0
        wall_correct: bool | None = None
        if preferred_wall:
            wall_expected_count += 1
            wall_correct = bool(
                count_correct
                and wall_confidence >= float(minimum_confidence)
                and observed_wall == preferred_wall
            )
            wall_correct_count += int(wall_correct)
        object_results.append(
            {
                "id": object_id,
                "category": str(spec.get("category") or ""),
                "expected_count": 1,
                "visible_instance_count": visible_count,
                "count_confidence": round(count_confidence, 6),
                "count_correct": count_correct,
                "preferred_wall": preferred_wall or None,
                "observed_wall": observed_wall,
                "wall_confidence": round(wall_confidence, 6),
                "wall_correct": wall_correct,
                "evidence": str(observed.get("evidence") or ""),
            }
        )

    unexpected: list[dict[str, Any]] = []
    unexpected_counts = {
        "major_furniture": 0,
        "accessory": 0,
        "decor": 0,
        "architecture": 0,
        "unknown": 0,
    }
    raw_unexpected = raw.get("unexpected_objects", []) if isinstance(raw, dict) else []
    for item in raw_unexpected if isinstance(raw_unexpected, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            confidence = float(item.get("confidence", 0.0))
            count = max(0, int(item.get("count", 0)))
        except (TypeError, ValueError):
            continue
        if confidence < float(minimum_confidence) or count == 0:
            continue
        kind = str(item.get("kind") or "unknown")
        if kind not in unexpected_counts:
            kind = "unknown"
        unexpected_counts[kind] += count
        unexpected.append(
            {
                "category": str(item.get("category") or ""),
                "count": count,
                "kind": kind,
                "confidence": round(confidence, 6),
                "evidence": str(item.get("evidence") or ""),
            }
        )

    expected_relations = {
        key for relation in brief.get("relations", []) if (key := _relation_key(relation))
    }
    raw_relations = raw.get("relations", []) if isinstance(raw, dict) else []
    observed_relations = {
        key: item
        for item in raw_relations if isinstance(raw_relations, list)
        if isinstance(item, dict) and (key := _relation_key(item))
    }
    relation_results: list[dict[str, Any]] = []
    relation_correct_count = 0
    for key in sorted(expected_relations):
        observed = observed_relations.get(key, {})
        try:
            confidence = float(observed.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        satisfied = bool(
            observed.get("satisfied") is True
            and confidence >= float(minimum_confidence)
        )
        relation_correct_count += int(satisfied)
        relation_results.append(
            {
                "source": key[0],
                "type": key[1],
                "target": key[2],
                "satisfied": satisfied,
                "confidence": round(confidence, 6),
                "evidence": str(observed.get("evidence") or ""),
            }
        )

    architecture = brief.get("architecture", {})
    expected_door_walls = sorted(
        str(item.get("wall"))
        for item in architecture.get("doors", [])
        if isinstance(item, dict) and item.get("wall")
    )
    expected_window_walls = sorted(
        str(item.get("wall"))
        for item in architecture.get("windows", [])
        if isinstance(item, dict) and item.get("wall")
    )
    raw_architecture = (
        raw.get("architecture", {}) if isinstance(raw, dict) else {}
    )
    observed_door_walls = sorted(
        str(wall)
        for wall in raw_architecture.get("door_walls", [])
        if str(wall) in WALLS
    )
    observed_window_walls = sorted(
        str(wall)
        for wall in raw_architecture.get("window_walls", [])
        if str(wall) in WALLS
    )
    architecture_correct = (
        observed_door_walls == expected_door_walls
        and observed_window_walls == expected_window_walls
    )
    expected_count = len(expected_objects)
    exact_count_rate = exact_count_count / max(expected_count, 1)
    wall_match_rate = wall_correct_count / max(wall_expected_count, 1)
    relation_match_rate = relation_correct_count / max(len(expected_relations), 1)
    strict_inventory_pass = bool(
        exact_count_count == expected_count
        and unexpected_counts["major_furniture"] == 0
    )
    strict_all_object_pass = bool(
        strict_inventory_pass
        and unexpected_counts["accessory"] == 0
        and unexpected_counts["decor"] == 0
        and unexpected_counts["unknown"] == 0
    )
    return {
        "schema": INVENTORY_AUDIT_SCHEMA,
        "minimum_confidence": float(minimum_confidence),
        "objects": object_results,
        "metrics": {
            "expected_object_count": expected_count,
            "exact_count_object_count": exact_count_count,
            "exact_count_rate": round(exact_count_rate, 6),
            "missing_instance_count": missing_instance_count,
            "duplicate_instance_count": duplicate_instance_count,
            "unexpected_object_counts": unexpected_counts,
            "strict_inventory_pass": strict_inventory_pass,
            "strict_all_object_pass": strict_all_object_pass,
            "wall_expected_count": wall_expected_count,
            "wall_correct_count": wall_correct_count,
            "wall_match_rate": round(wall_match_rate, 6),
            "expected_relation_count": len(expected_relations),
            "relation_correct_count": relation_correct_count,
            "relation_match_rate": round(relation_match_rate, 6),
            "architecture_correct": architecture_correct,
        },
        "relations": relation_results,
        "architecture": {
            "expected_door_walls": expected_door_walls,
            "observed_door_walls": observed_door_walls,
            "expected_window_walls": expected_window_walls,
            "observed_window_walls": observed_window_walls,
            "correct": architecture_correct,
        },
        "unexpected_objects": unexpected,
        "warnings": list(raw.get("warnings", []))
        if isinstance(raw, dict) and isinstance(raw.get("warnings"), list)
        else [],
    }


def _copy_if_needed(source: Path, destination: Path) -> None:
    source = source.expanduser().resolve()
    destination = destination.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source != destination:
        shutil.copy2(source, destination)


def run_comparison(args: Any) -> dict[str, Any]:
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    brief = read_json(Path(args.brief).expanduser().resolve())
    sources = {
        "flux1_schnell": Path(args.flux_image).expanduser().resolve(),
        "codex_builtin_imagegen": Path(args.codex_image).expanduser().resolve(),
    }
    summaries: dict[str, Any] = {}
    for name, source_image in sources.items():
        model_dir = output_dir / name
        image_path = model_dir / "reference_image.png"
        _copy_if_needed(source_image, image_path)
        raw = run_codex_image_json(
            build_inventory_audit_prompt(brief),
            image_path,
            model_dir,
            stage="inventory_audit",
            model=str(args.audit_model),
        )
        write_json(model_dir / "inventory_audit_raw.json", raw)
        summary = summarize_inventory_audit(
            raw,
            brief,
            minimum_confidence=float(args.minimum_confidence),
        )
        write_json(model_dir / "inventory_audit_summary.json", summary)
        summaries[name] = summary

    flux = summaries["flux1_schnell"]["metrics"]
    codex = summaries["codex_builtin_imagegen"]["metrics"]
    comparison = {
        "schema": COMPARISON_SCHEMA,
        "audit_model": str(args.audit_model),
        "minimum_confidence": float(args.minimum_confidence),
        "generator_identity": {
            "flux1_schnell": {
                "model": "FLUX.1-schnell",
                "configuration": "local 768x768, 4 steps, guidance_scale=0",
            },
            "codex_builtin_imagegen": {
                "model": None,
                "configuration": "Codex built-in image generation",
                "note": "The built-in tool did not expose a backend model id; this result is not labeled as a verified API gpt-image-2 call.",
            },
        },
        "results": summaries,
        "metric_delta_codex_minus_flux": {
            "exact_count_rate": round(
                float(codex["exact_count_rate"])
                - float(flux["exact_count_rate"]),
                6,
            ),
            "unexpected_major_furniture_count": (
                int(codex["unexpected_object_counts"]["major_furniture"])
                - int(flux["unexpected_object_counts"]["major_furniture"])
            ),
            "unexpected_accessory_count": (
                int(codex["unexpected_object_counts"]["accessory"])
                - int(flux["unexpected_object_counts"]["accessory"])
            ),
            "unexpected_decor_count": (
                int(codex["unexpected_object_counts"]["decor"])
                - int(flux["unexpected_object_counts"]["decor"])
            ),
            "wall_match_rate": round(
                float(codex["wall_match_rate"])
                - float(flux["wall_match_rate"]),
                6,
            ),
            "relation_match_rate": round(
                float(codex["relation_match_rate"])
                - float(flux["relation_match_rate"]),
                6,
            ),
        },
        "limitations": [
            "Both images are audited by the same vision model, so evaluator bias is shared rather than eliminated.",
            "The vision audit is model-generated and may vary across repeated runs; raw evidence is retained for inspection.",
            "This is one prompt and one sample per generator; it is a smoke comparison, not a statistical model ranking.",
            "The Codex built-in image generation tool did not expose its backend model id.",
            "Final scene quality still requires equal-asset 3D assembly and render-based evaluation.",
        ],
    }
    write_json(output_dir / "reference_image_model_comparison.json", comparison)
    return comparison


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare two generated scene references with one inventory auditor."
    )
    parser.add_argument("--brief", required=True, type=Path)
    parser.add_argument("--flux-image", required=True, type=Path)
    parser.add_argument("--codex-image", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--audit-model", default="gpt-5.6-sol")
    parser.add_argument("--minimum-confidence", type=float, default=0.6)
    return parser


def main(argv: list[str] | None = None) -> int:
    report = run_comparison(build_parser().parse_args(argv))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
