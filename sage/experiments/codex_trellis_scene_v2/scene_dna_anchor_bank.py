from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .brief import ASSET_SEMANTIC_FORM_HINTS
from .io_utils import read_json, write_json


DEFAULT_TURNTABLE_ASSET_MAP = {
    "wooden_bed": "bed_warm_oak_001",
    "left_nightstand": "nightstand_warm_oak_001",
    "wooden_desk": "desk_warm_oak_001",
    "black_office_chair": "office_chair_black_mesh_001",
    "wall_shelf": "wall_shelf_warm_oak_001",
    "framed_lake_art": "wall_art_lake_001",
    "potted_plant": "potted_plant_white_001",
    "white_mug": "mug_white_001",
    "left_slipper": "slipper_blue_left_001",
    "area_rug": "area_rug_warm_procedural_001",
}


def build_anchor_manifest(
    curated_manifest_path: Path,
    turntable_manifest_path: Path,
    output_path: Path,
    *,
    object_asset_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    curated = read_json(curated_manifest_path)
    turntables = read_json(turntable_manifest_path)
    assets = {
        str(item.get("asset_id") or ""): item
        for item in curated.get("assets", [])
        if isinstance(item, dict) and item.get("asset_id")
    }
    mapping = object_asset_map or DEFAULT_TURNTABLE_ASSET_MAP
    anchors: list[dict[str, Any]] = []
    missing: list[dict[str, str]] = []
    for object_id, asset_id in mapping.items():
        asset = assets.get(asset_id)
        views = turntables.get("views", {}).get(object_id)
        if not isinstance(asset, dict) or not isinstance(views, dict):
            missing.append({"object_id": object_id, "asset_id": asset_id})
            continue
        if str(asset.get("qa_status") or "approved") != "approved":
            continue
        category = str(asset.get("category") or "")
        semantic = ASSET_SEMANTIC_FORM_HINTS.get(category, {})
        paths = [
            str(Path(str(views[axis])).resolve())
            for axis in ("+x", "-x", "+y", "-y")
            if views.get(axis) and Path(str(views[axis])).is_file()
        ]
        if not paths:
            missing.append({"object_id": object_id, "asset_id": asset_id})
            continue
        anchors.append(
            {
                "asset_id": asset_id,
                "category": category,
                "identity": str(semantic.get("identity") or category).replace(
                    "_", " "
                ),
                "shape_profile": str(
                    semantic.get("shape_profile") or "general_object"
                ),
                "styles": list(asset.get("styles", [])),
                "qa_status": "approved",
                "image_paths": paths,
                "turntable_object_id": object_id,
            }
        )
    report = {
        "schema": "scene_dna_dinov3_anchor_manifest_v1",
        "source_curated_manifest": str(curated_manifest_path.resolve()),
        "source_turntable_manifest": str(turntable_manifest_path.resolve()),
        "approved_anchor_count": len(anchors),
        "anchors": anchors,
        "missing": missing,
        "limitations": [
            "only assets with approved metadata and standardized four-view renders are included",
            "categories without approved turntables fall back to shape and semantic scoring",
        ],
    }
    write_json(output_path, report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--curated-manifest", required=True, type=Path)
    parser.add_argument("--turntable-manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = build_anchor_manifest(
        args.curated_manifest, args.turntable_manifest, args.output
    )
    print(
        json.dumps(
            {
                "approved_anchor_count": report["approved_anchor_count"],
                "missing_count": len(report["missing"]),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
