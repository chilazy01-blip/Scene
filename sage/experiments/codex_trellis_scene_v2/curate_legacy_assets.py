#!/usr/bin/env python3
"""Promote reviewed TreeSAGE assets into the V2 curated asset library."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import trimesh

from .io_utils import write_json


ASSETS: list[dict[str, Any]] = [
    {
        "source_id": "wooden_bed", "asset_id": "bed_warm_oak_001", "category": "bed",
        "dimensions": [1.8, 2.1, 1.05], "styles": ["modern", "warm", "wood"],
        "target_faces": 220000, "canonical_front_axis": "-y", "quality_tier": "prototype_approved",
    },
    {
        "source_id": "left_nightstand", "asset_id": "nightstand_warm_oak_001", "category": "nightstand",
        "dimensions": [0.55, 0.45, 0.62], "styles": ["modern", "warm", "wood"],
        "target_faces": 80000, "canonical_front_axis": "-y", "quality_tier": "prototype_approved",
    },
    {
        "source_id": "right_nightstand", "asset_id": "nightstand_warm_oak_002", "category": "nightstand",
        "dimensions": [0.55, 0.45, 0.62], "styles": ["modern", "warm", "wood"],
        "target_faces": 80000, "canonical_front_axis": "-y", "quality_tier": "prototype_approved",
    },
    {
        "source_id": "wooden_desk", "asset_id": "desk_warm_oak_001", "category": "desk",
        "dimensions": [1.4, 0.72, 0.75], "styles": ["modern", "warm", "wood", "minimal"],
        "target_faces": 60000, "canonical_front_axis": "-y", "quality_tier": "corrected_metadata",
        "corrections": ["replaced undersized 0.527 m square scene dimensions with desk dimensions"],
    },
    {
        "source_id": "black_office_chair", "asset_id": "office_chair_black_mesh_001", "category": "office_chair",
        "dimensions": [0.62, 0.62, 1.05], "styles": ["modern", "office", "black"],
        "target_faces": 180000, "canonical_front_axis": "-y", "quality_tier": "prototype_approved",
    },
    {
        "source_id": "wardrobe", "asset_id": "wardrobe_warm_oak_001", "category": "wardrobe",
        "dimensions": [1.6, 0.62, 2.1], "styles": ["modern", "warm", "wood"],
        "target_faces": 90000, "canonical_front_axis": "-y", "quality_tier": "prototype_approved",
    },
    {
        "source_id": "wall_shelf", "asset_id": "wall_shelf_warm_oak_001", "category": "wall_shelf",
        "dimensions": [1.1, 0.24, 0.07], "styles": ["modern", "warm", "wood", "minimal"],
        "target_faces": 5000, "quality_tier": "corrected_geometry",
        "usage_constraints": ["wall_mounted"], "corrections": ["aggressive decimation for simple plank geometry"],
    },
    {
        "source_id": "framed_lake_art", "asset_id": "wall_art_lake_001", "category": "wall_art",
        "dimensions": [0.78, 0.045, 0.58], "styles": ["modern", "warm", "landscape"],
        "target_faces": 12000, "canonical_front_axis": "+y", "quality_tier": "corrected_usage",
        "usage_constraints": ["wall_mounted", "front_only", "back_against_wall"],
        "corrections": ["front-only constraint hides inconsistent reverse texture"],
    },
    {
        "source_id": "left_window", "asset_id": "window_white_single_001", "category": "window",
        "dimensions": [1.04, 0.08, 1.296], "styles": ["modern", "white"],
        "target_faces": 40000, "canonical_front_axis": "+y", "quality_tier": "corrected_usage",
        "usage_constraints": ["wall_mounted", "front_only", "embedded_in_wall"],
    },
    {
        "source_id": "curtain_rod", "asset_id": "curtain_rod_brass_001", "category": "curtain_rod",
        "dimensions": [1.45, 0.06, 0.06], "styles": ["modern", "warm", "brass"],
        "target_faces": 15000, "quality_tier": "prototype_approved", "usage_constraints": ["wall_mounted"],
    },
    {
        "source_id": "blue_curtain_panel", "asset_id": "curtain_panel_blue_001", "category": "curtain_panel",
        "dimensions": [0.55, 0.06, 1.9], "styles": ["modern", "blue", "fabric"],
        "target_faces": 100000, "quality_tier": "prototype_approved", "usage_constraints": ["wall_mounted"],
    },
    {
        "source_id": "bedside_table_lamp", "asset_id": "table_lamp_cream_001", "category": "table_lamp",
        "dimensions": [0.28, 0.28, 0.48], "styles": ["modern", "warm", "cream"],
        "target_faces": 80000, "quality_tier": "prototype_approved", "usage_constraints": ["support_surface"],
    },
    {
        "source_id": "alarm_clock", "asset_id": "alarm_clock_black_001", "category": "alarm_clock",
        "dimensions": [0.17, 0.13, 0.2], "styles": ["classic", "black"],
        "target_faces": 60000, "canonical_front_axis": "+y", "quality_tier": "corrected_usage",
        "usage_constraints": ["support_surface", "front_only"],
        "corrections": ["front-only constraint hides incomplete reverse face"],
    },
    {
        "source_id": "potted_plant", "asset_id": "potted_plant_white_001", "category": "potted_plant",
        "dimensions": [0.24, 0.24, 0.36], "styles": ["modern", "green", "white"],
        "target_faces": 180000, "quality_tier": "prototype_approved", "usage_constraints": ["support_surface"],
    },
    {
        "source_id": "white_mug", "asset_id": "mug_white_001", "category": "mug",
        "dimensions": [0.12, 0.09, 0.11], "styles": ["modern", "white", "minimal"],
        "target_faces": 40000, "quality_tier": "prototype_approved", "usage_constraints": ["support_surface"],
    },
    {
        "source_id": "left_slipper", "asset_id": "slipper_blue_left_001", "category": "slipper",
        "dimensions": [0.28, 0.12, 0.08], "styles": ["modern", "blue", "fabric"],
        "target_faces": 50000, "canonical_front_axis": "+y", "quality_tier": "corrected_metadata",
        "corrections": ["replaced erroneous 2.8 m scene dimensions with real slipper dimensions"],
    },
    {
        "source_id": "right_slipper", "asset_id": "slipper_blue_right_001", "category": "slipper",
        "dimensions": [0.28, 0.12, 0.08], "styles": ["modern", "blue", "fabric"],
        "target_faces": 50000, "canonical_front_axis": "-y", "quality_tier": "corrected_metadata",
        "corrections": ["replaced erroneous 2.8 m scene dimensions and registered independent front axis"],
    },
]


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--source-dir", required=True, type=Path)
    result.add_argument("--output-dir", required=True, type=Path)
    result.add_argument("--blender", type=Path, default=Path("/data/wsj/tools/blender/blender"))
    result.add_argument("--force", action="store_true")
    return result


def inspect_glb(path: Path) -> dict[str, Any]:
    loaded = trimesh.load(path, force="scene")
    return {
        "bytes": path.stat().st_size,
        "geometry_count": len(loaded.geometry),
        "faces": sum(len(geom.faces) for geom in loaded.geometry.values()),
        "raw_extents": [round(float(value), 6) for value in loaded.extents],
    }


def create_procedural_rug(path: Path) -> dict[str, Any]:
    mesh = trimesh.creation.box(extents=[2.4, 1.7, 0.02])
    mesh.apply_translation([0.0, 0.0, 0.01])
    mesh.visual.material = trimesh.visual.material.PBRMaterial(
        name="WarmWovenRug",
        baseColorFactor=[185, 174, 158, 255],
        metallicFactor=0.0,
        roughnessFactor=0.92,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(path)
    return inspect_glb(path)


def main() -> None:
    args = parser().parse_args()
    source_dir = args.source_dir.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    raw_dir = output_dir / "raw"
    optimized_dir = output_dir / "optimized"
    quarantine_dir = output_dir / "quarantine"
    reports_dir = output_dir / "reports"
    for directory in (raw_dir, optimized_dir, quarantine_dir, reports_dir):
        directory.mkdir(parents=True, exist_ok=True)

    expected_outputs = [optimized_dir / f"{item['asset_id']}.glb" for item in ASSETS]
    expected_outputs.append(optimized_dir / "area_rug_warm_procedural_001.glb")
    if not args.force and any(path.exists() for path in expected_outputs):
        raise FileExistsError(f"Curated output already exists under {output_dir}; pass --force to rebuild")

    optimization_assets: list[dict[str, Any]] = []
    source_reports: dict[str, Any] = {}
    for item in ASSETS:
        source = source_dir / f"{item['source_id']}.glb"
        if not source.is_file():
            raise FileNotFoundError(source)
        raw = raw_dir / f"{item['asset_id']}.glb"
        shutil.copy2(source, raw)
        source_reports[item["asset_id"]] = inspect_glb(raw)
        optimization_assets.append(
            {
                "asset_id": item["asset_id"],
                "source": str(raw),
                "output": str(optimized_dir / f"{item['asset_id']}.glb"),
                "target_faces": item["target_faces"],
            }
        )

    rejected_rug = source_dir / "area_rug.glb"
    shutil.copy2(rejected_rug, quarantine_dir / "area_rug_bad_trellis_source.glb")
    procedural_rug = optimized_dir / "area_rug_warm_procedural_001.glb"
    rug_inspection = create_procedural_rug(procedural_rug)

    optimization_config = reports_dir / "optimization_config.json"
    write_json(optimization_config, {"schema": "curated_asset_optimization_config_v1", "assets": optimization_assets})
    optimizer = Path(__file__).with_name("blender_optimize_asset_library.py")
    optimization_report = reports_dir / "optimization_report.json"
    subprocess.run(
        [
            str(args.blender), "-b", "--python", str(optimizer), "--",
            "--config", str(optimization_config), "--report", str(optimization_report),
        ],
        check=True,
    )

    optimized_reports = {
        item["asset_id"]: inspect_glb(optimized_dir / f"{item['asset_id']}.glb")
        for item in ASSETS
    }
    manifest_assets: list[dict[str, Any]] = []
    for item in ASSETS:
        width, length, height = item["dimensions"]
        entry: dict[str, Any] = {
            "asset_id": item["asset_id"],
            "category": item["category"],
            "styles": item["styles"],
            "qa_status": "approved",
            "quality_tier": item["quality_tier"],
            "glb_path": f"optimized/{item['asset_id']}.glb",
            "raw_glb_path": f"raw/{item['asset_id']}.glb",
            "dimensions": {"width": width, "length": length, "height": height},
            "asset_axis_to_z": 2,
            "asset_local_yaw_offset_degrees": 0.0,
            "source": {
                "pipeline": "tree_sage_flow2_image_scene",
                "source_id": item["source_id"],
                "source_glb": str(source_dir / f"{item['source_id']}.glb"),
            },
            "mesh": optimized_reports[item["asset_id"]],
        }
        if item.get("canonical_front_axis"):
            entry["asset_canonical_front"] = {"axis": item["canonical_front_axis"], "confidence": 0.9}
        if item.get("usage_constraints"):
            entry["usage_constraints"] = item["usage_constraints"]
        if item.get("corrections"):
            entry["corrections"] = item["corrections"]
        manifest_assets.append(entry)

    manifest_assets.append(
        {
            "asset_id": "dresser_warm_oak_001",
            "category": "dresser",
            "styles": ["modern", "warm", "wood"],
            "qa_status": "approved",
            "quality_tier": "derived_prototype",
            "glb_path": "optimized/nightstand_warm_oak_002.glb",
            "raw_glb_path": "raw/nightstand_warm_oak_002.glb",
            "dimensions": {"width": 1.2, "length": 0.5, "height": 0.9},
            "asset_axis_to_z": 2,
            "asset_local_yaw_offset_degrees": 0.0,
            "asset_canonical_front": {"axis": "-y", "confidence": 0.9},
            "corrections": ["derived a low two-drawer dresser variant from the approved cabinet asset"],
            "source": {"pipeline": "derived_reuse", "asset_id": "nightstand_warm_oak_002"},
            "mesh": optimized_reports["nightstand_warm_oak_002"],
        }
    )
    manifest_assets.append(
        {
            "asset_id": "area_rug_warm_procedural_001",
            "category": "area_rug",
            "styles": ["modern", "warm", "minimal"],
            "qa_status": "approved",
            "quality_tier": "procedural_replacement",
            "glb_path": "optimized/area_rug_warm_procedural_001.glb",
            "dimensions": {"width": 2.4, "length": 1.7, "height": 0.02},
            "asset_axis_to_z": 2,
            "asset_local_yaw_offset_degrees": 0.0,
            "usage_constraints": ["floor_only", "underlay"],
            "corrections": ["replaced malformed multi-slab TRELLIS rug with a clean procedural thin rug"],
            "mesh": rug_inspection,
            "source": {
                "pipeline": "procedural_replacement",
                "rejected_source": "quarantine/area_rug_bad_trellis_source.glb",
            },
        }
    )

    manifest = {
        "schema": "curated_scene_assets_v1",
        "library_id": "tree_sage_legacy_promoted_v1",
        "assets": manifest_assets,
    }
    write_json(output_dir / "manifest.json", manifest)
    qa_report = {
        "schema": "curated_asset_promotion_report_v1",
        "ok": True,
        "source_dir": str(source_dir),
        "library_dir": str(output_dir),
        "approved_count": len(manifest_assets),
        "promoted_from_trellis_count": len(ASSETS),
        "derived_reuse_count": 1,
        "procedural_replacement_count": 1,
        "quarantined": ["area_rug_bad_trellis_source.glb"],
        "raw_inspections": source_reports,
        "optimized_inspections": optimized_reports,
        "procedural_rug": rug_inspection,
    }
    write_json(reports_dir / "promotion_report.json", qa_report)
    print(json.dumps(qa_report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
