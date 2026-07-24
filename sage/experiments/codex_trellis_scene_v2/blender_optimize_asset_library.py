#!/usr/bin/env python3
"""Create texture-preserving, reduced-poly GLBs for a curated asset library."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    argv = argv[argv.index("--") + 1 :] if "--" in argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    return parser.parse_args(argv)


def clear_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def mesh_objects() -> list[bpy.types.Object]:
    return [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]


def polygon_count(objects: list[bpy.types.Object]) -> int:
    return sum(len(obj.data.polygons) for obj in objects)


def optimize_one(source: Path, output: Path, target_faces: int) -> dict[str, object]:
    clear_scene()
    bpy.ops.import_scene.gltf(filepath=str(source))
    objects = mesh_objects()
    if not objects:
        raise RuntimeError(f"Imported asset contains no mesh: {source}")
    before_faces = polygon_count(objects)
    ratio = min(1.0, max(0.01, float(target_faces) / max(float(before_faces), 1.0)))

    if ratio < 0.999:
        for obj in objects:
            if len(obj.data.polygons) < 16:
                continue
            bpy.context.view_layer.objects.active = obj
            obj.select_set(True)
            modifier = obj.modifiers.new(name="CuratedDecimate", type="DECIMATE")
            modifier.decimate_type = "COLLAPSE"
            modifier.ratio = ratio
            modifier.use_collapse_triangulate = True
            bpy.ops.object.modifier_apply(modifier=modifier.name)
            obj.select_set(False)

    after_faces = polygon_count(objects)
    output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=str(output),
        export_format="GLB",
        export_apply=True,
        export_materials="EXPORT",
    )
    return {
        "source": str(source),
        "output": str(output),
        "before_faces": before_faces,
        "after_faces": after_faces,
        "target_faces": target_faces,
        "ratio": round(ratio, 8),
        "output_bytes": output.stat().st_size,
    }


def main() -> None:
    args = parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    rows: list[dict[str, object]] = []
    for item in config["assets"]:
        source = Path(item["source"]).resolve()
        output = Path(item["output"]).resolve()
        row: dict[str, object] = {"asset_id": item["asset_id"]}
        try:
            row.update(optimize_one(source, output, int(item["target_faces"])))
            row["ok"] = True
        except Exception as exc:
            row.update({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)

    report = {
        "schema": "curated_asset_optimization_report_v1",
        "ok": all(bool(row.get("ok")) for row in rows),
        "asset_count": len(rows),
        "assets": rows,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if not report["ok"]:
        raise RuntimeError("One or more curated assets failed optimization")


if __name__ == "__main__":
    main()
