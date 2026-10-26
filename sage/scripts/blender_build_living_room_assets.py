#!/usr/bin/env python3
"""Build deterministic, style-coherent living-room assets for certification."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


ASSETS = {
    "sofa_warm_boucle_001": ("sofa", (2.20, 0.92, 0.90)),
    "coffee_table_light_oak_001": ("coffee_table", (1.10, 0.62, 0.42)),
    "tv_stand_light_oak_001": ("tv_stand", (1.70, 0.42, 0.58)),
    "tv_charcoal_001": ("tv", (1.25, 0.12, 0.75)),
    "accent_chair_boucle_001": ("accent_chair", (0.82, 0.82, 0.92)),
    "side_table_oak_brass_001": ("side_table", (0.48, 0.48, 0.55)),
    "floor_lamp_brass_001": ("floor_lamp", (0.40, 0.40, 1.65)),
    "open_bookcase_light_oak_001": ("bookcase", (1.10, 0.36, 1.90)),
}


def args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def mat(name: str, color: tuple[float, float, float, float], roughness: float = 0.65, metallic: float = 0.0):
    material = bpy.data.materials.new(name)
    material.diffuse_color = color
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = color
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    return material


def bevel(obj: bpy.types.Object, width: float, segments: int = 3) -> None:
    modifier = obj.modifiers.new("soft_edge", "BEVEL")
    modifier.width = width
    modifier.segments = segments
    modifier.limit_method = "ANGLE"
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    obj.select_set(False)


def box(name: str, center, size, material, radius: float = 0.0):
    bpy.ops.mesh.primitive_cube_add(location=center)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if radius:
        bevel(obj, min(radius, min(size) * 0.22))
    obj.data.materials.append(material)
    return obj


def cylinder(name: str, center, radius: float, depth: float, material, vertices: int = 48):
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth, location=center)
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(material)
    return obj


def geometry_bounds() -> tuple[Vector, Vector]:
    """Return evaluated world bounds for every mesh in the current asset.

    The report is deliberately derived from exported geometry rather than from
    the design constants.  This keeps deterministic/curated assets under the
    same fit contract as generated assets and prevents a future builder change
    from silently reintroducing stretched furniture.
    """

    points = [
        obj.matrix_world @ Vector(corner)
        for obj in bpy.context.scene.objects
        if obj.type == "MESH"
        for corner in obj.bound_box
    ]
    if not points:
        raise RuntimeError("asset builder produced no mesh geometry")
    return (
        Vector(tuple(min(float(point[index]) for point in points) for index in range(3))),
        Vector(tuple(max(float(point[index]) for point in points) for index in range(3))),
    )


def fit_audit(requested: tuple[float, float, float]) -> dict:
    bpy.context.view_layer.update()
    lower, upper = geometry_bounds()
    actual = tuple(float(upper[index] - lower[index]) for index in range(3))
    fit = tuple(float(requested[index]) / max(actual[index], 1e-8) for index in range(3))
    anisotropy = max(fit) / max(min(fit), 1e-8)
    relative_errors = tuple(
        abs(actual[index] - float(requested[index])) / max(float(requested[index]), 1e-8)
        for index in range(3)
    )
    ok = bool(anisotropy <= 1.10 and max(relative_errors) <= 0.08)
    return {
        "ok": ok,
        "actual_dimensions": dict(zip(("width", "length", "height"), actual)),
        "requested_to_actual_scale": dict(zip(("x", "y", "z"), fit)),
        "fit_anisotropy": anisotropy,
        "maximum_relative_dimension_error": max(relative_errors),
        "limits": {"fit_anisotropy_maximum": 1.10, "relative_dimension_error_maximum": 0.08},
    }


def palette():
    return {
        "boucle": mat("cream_boucle", (0.78, 0.70, 0.59, 1), 0.92),
        "boucle_light": mat("cream_boucle_light", (0.88, 0.82, 0.72, 1), 0.94),
        "sage": mat("muted_sage", (0.30, 0.42, 0.32, 1), 0.82),
        "oak": mat("light_oak", (0.60, 0.38, 0.18, 1), 0.64),
        "oak_light": mat("light_oak_highlight", (0.76, 0.55, 0.30, 1), 0.67),
        "charcoal": mat("charcoal", (0.035, 0.045, 0.05, 1), 0.46),
        "screen": mat("screen", (0.008, 0.016, 0.024, 1), 0.20),
        "brass": mat("brushed_brass", (0.50, 0.31, 0.08, 1), 0.34, 0.72),
        "shade": mat("linen_shade", (0.84, 0.76, 0.62, 1), 0.9),
    }


def build_sofa(p):
    box("sofa_base", (0, 0, .26), (1.94, .78, .30), p["boucle"], .055)
    box("sofa_arm_left", (-1.02, 0, .50), (.16, .88, .58), p["boucle"], .055)
    box("sofa_arm_right", (1.02, 0, .50), (.16, .88, .58), p["boucle"], .055)
    box("sofa_back", (0, .37, .62), (1.94, .16, .56), p["boucle"], .05)
    for i, x in enumerate((-.63, 0, .63), 1):
        box(f"sofa_seat_cushion_{i}", (x, -.08, .47), (.58, .58, .18), p["boucle_light"], .045)
        cushion = box(f"sofa_back_cushion_{i}", (x, .23, .69), (.56, .16, .36), p["boucle_light"], .05)
        cushion.rotation_euler[0] = math.radians(-6)
    for x in (-.88, .88):
        for y in (-.30, .30):
            box(f"sofa_oak_foot_{x}_{y}", (x, y, .07), (.10, .10, .14), p["oak"], .012)


def build_chair(p):
    box("chair_base", (0, 0, .25), (.68, .78, .28), p["boucle"], .07)
    box("chair_seat", (0, -.04, .46), (.60, .58, .20), p["boucle_light"], .06)
    back = box("chair_back", (0, .27, .69), (.64, .18, .50), p["sage"], .07)
    back.rotation_euler[0] = math.radians(-7)
    for x in (-.35, .35):
        box(f"chair_arm_{x}", (x, -.01, .60), (.12, .72, .30), p["boucle"], .05)
    for x in (-.27, .27):
        for y in (-.25, .25):
            box(f"chair_leg_{x}_{y}", (x, y, .10), (.07, .07, .20), p["oak"], .01)


def build_coffee_table(p):
    box("coffee_top", (0, 0, .37), (1.10, .62, .10), p["oak_light"], .055)
    box("coffee_shelf", (0, 0, .16), (.88, .48, .055), p["oak"], .025)
    for x in (-.44, .44):
        for y in (-.20, .20):
            box(f"coffee_leg_{x}_{y}", (x, y, .19), (.07, .07, .38), p["oak"], .012)


def build_tv_stand(p):
    # Keep decorative fronts inside the declared 0.42 m footprint.  The first
    # version measured only the cabinet carcass and let doors/pulls protrude to
    # 0.4605 m, precisely the sort of metadata/geometry mismatch the fit gate
    # is meant to catch.
    box("console_body", (0, 0, .32), (1.70, .38, .44), p["oak"], .035)
    box("console_top", (0, 0, .56), (1.70, .42, .04), p["oak_light"], .012)
    for x in (-.56, 0, .56):
        box(f"console_door_{x}", (x, -.198, .34), (.50, .016, .32), p["oak_light"], .006)
        box(f"console_pull_{x}", (x, -.2075, .42), (.12, .005, .025), p["brass"], .002)
    for x in (-.72, .72):
        box(f"console_foot_{x}", (x, 0, .06), (.09, .30, .12), p["charcoal"], .01)


def build_tv(p):
    box("tv_frame", (0, 0, .42), (1.25, .10, .66), p["charcoal"], .025)
    box("tv_screen", (0, -.055, .43), (1.17, .010, .58), p["screen"], .004)
    cylinder("tv_neck", (0, 0, .075), .035, .15, p["charcoal"], 32)
    box("tv_foot", (0, 0, .02), (.38, .12, .04), p["charcoal"], .015)


def build_side_table(p):
    cylinder("side_top", (0, 0, .51), .24, .08, p["oak_light"])
    cylinder("side_column", (0, 0, .28), .035, .46, p["brass"], 32)
    cylinder("side_base", (0, 0, .035), .18, .07, p["brass"])


def build_floor_lamp(p):
    cylinder("lamp_base", (0, 0, .035), .20, .07, p["brass"])
    cylinder("lamp_stem", (0, 0, .79), .018, 1.52, p["brass"], 32)
    bpy.ops.mesh.primitive_cone_add(vertices=48, radius1=.20, radius2=.13, depth=.33, location=(0, 0, 1.485))
    bpy.context.object.name = "lamp_linen_shade"
    bpy.context.object.data.materials.append(p["shade"])
    cylinder("lamp_cap", (0, 0, 1.65 - .012), .09, .024, p["brass"], 32)


def build_bookcase(p):
    box("bookcase_left", (-.515, 0, .95), (.07, .36, 1.90), p["oak"], .018)
    box("bookcase_right", (.515, 0, .95), (.07, .36, 1.90), p["oak"], .018)
    box("bookcase_back", (0, .16, .95), (1.03, .04, 1.90), p["oak_light"], .012)
    for index, z in enumerate((.035, .63, 1.22, 1.865)):
        box(f"bookcase_shelf_{index}", (0, 0, z), (1.10, .36, .07), p["oak"], .018)


BUILDERS = {
    "sofa": build_sofa,
    "coffee_table": build_coffee_table,
    "tv_stand": build_tv_stand,
    "tv": build_tv,
    "accent_chair": build_chair,
    "side_table": build_side_table,
    "floor_lamp": build_floor_lamp,
    "bookcase": build_bookcase,
}


def main() -> None:
    parsed = args()
    parsed.output_dir.mkdir(parents=True, exist_ok=True)
    report_path = parsed.output_dir / "build_report.json"
    report_path.write_text(
        json.dumps({"schema": "scene-v2-deterministic-living-assets/v1", "ok": False, "status": "building"}, indent=2) + "\n",
        encoding="utf-8",
    )
    rows = []
    for asset_id, (category, dimensions) in ASSETS.items():
        bpy.ops.wm.read_factory_settings(use_empty=True)
        p = palette()
        BUILDERS[category](p)
        for obj in bpy.context.scene.objects:
            if obj.type == "MESH":
                obj["asset_id"] = asset_id
                obj["category"] = category
        audit = fit_audit(dimensions)
        if not audit["ok"]:
            raise RuntimeError(f"{asset_id} violates deterministic asset fit contract: {audit}")
        output = parsed.output_dir / f"{asset_id}.glb"
        bpy.ops.export_scene.gltf(
            filepath=str(output), export_format="GLB", export_apply=True,
            export_materials="EXPORT", export_extras=True,
        )
        rows.append({
            "asset_id": asset_id,
            "category": category,
            "dimensions": dict(zip(("width", "length", "height"), dimensions)),
            "component_count": sum(obj.type == "MESH" for obj in bpy.context.scene.objects),
            "fit_audit": audit,
            "glb": str(output.resolve()),
            "bytes": output.stat().st_size,
        })
    report_path.write_text(
        json.dumps({"schema": "scene-v2-deterministic-living-assets/v1", "ok": True, "assets": rows}, indent=2) + "\n",
        encoding="utf-8",
    )
    (parsed.output_dir / "turntable_plan.json").write_text(
        json.dumps(
            {
                "schema": "scene-v2-asset-turntable-plan/v1",
                "objects": [
                    {
                        "id": row["asset_id"],
                        "category": row["category"],
                        "dimensions": row["dimensions"],
                        "requested_dimensions": row["dimensions"],
                        "asset_axis_to_z": 2,
                        "asset_axis_to_z_sign": 1.0,
                        "asset_local_yaw_offset_degrees": 0.0,
                    }
                    for row in rows
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
