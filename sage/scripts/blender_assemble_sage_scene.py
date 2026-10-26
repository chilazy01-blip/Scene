#!/usr/bin/env python3
"""Assemble a SAGE-style scene in Blender from a JSON plan and per-object GLBs."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix, Vector


# Load the same pure-Python contract in Blender and orchestration.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from mesh_dimension_contract import runtime_mesh_fit_audit
from blender_mesh_bounds import mesh_bbox_world
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from sage.experiments.codex_trellis_scene_v2.asset_usage import asset_usage_violations


TARGET_TYPES = {"MESH", "CURVE", "SURFACE", "META", "FONT"}


def normalized_rgba(raw: object, fallback: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    if not isinstance(raw, (list, tuple)) or len(raw) < 3:
        return fallback
    try:
        values = [float(value) for value in raw[:4]]
    except (TypeError, ValueError):
        return fallback
    if max(values[:3]) > 1.0:
        values[:3] = [value / 255.0 for value in values[:3]]
    alpha = values[3] if len(values) > 3 else fallback[3]
    rgba = values[:3] + [alpha]
    return tuple(max(0.0, min(1.0, value)) for value in rgba)  # type: ignore[return-value]


def shifted_color(color: tuple[float, float, float, float], factor: float) -> tuple[float, float, float, float]:
    rgb = [max(0.0, min(1.0, channel * factor)) for channel in color[:3]]
    return (rgb[0], rgb[1], rgb[2], color[3])


def make_color_ramp(
    nodes: bpy.types.Nodes,
    color_a: tuple[float, float, float, float],
    color_b: tuple[float, float, float, float],
    position_a: float = 0.2,
    position_b: float = 1.0,
) -> bpy.types.Node:
    ramp = nodes.new(type="ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = position_a
    ramp.color_ramp.elements[0].color = color_a
    ramp.color_ramp.elements[1].position = position_b
    ramp.color_ramp.elements[1].color = color_b
    return ramp


def apply_bump_from_fac(
    nodes: bpy.types.Nodes,
    links: bpy.types.NodeLinks,
    fac_output: bpy.types.NodeSocket,
    bsdf: bpy.types.Node,
    strength: float,
    distance: float,
) -> None:
    if "Normal" not in bsdf.inputs or strength <= 0.0:
        return
    bump = nodes.new(type="ShaderNodeBump")
    if "Strength" in bump.inputs:
        bump.inputs["Strength"].default_value = strength
    if "Distance" in bump.inputs:
        bump.inputs["Distance"].default_value = distance
    links.new(fac_output, bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def apply_procedural_texture(
    mat: bpy.types.Material,
    bsdf: bpy.types.Node,
    base_color: tuple[float, float, float, float],
    spec: dict[str, object],
) -> None:
    if not mat.node_tree:
        return
    texture_type = str(spec.get("texture_type") or "")
    if not texture_type.startswith("procedural_"):
        return
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    secondary = normalized_rgba(spec.get("secondary_color"), shifted_color(base_color, 1.08))
    grain = normalized_rgba(spec.get("grain_color"), shifted_color(base_color, 0.72))
    if texture_type in {"procedural_painted_plaster", "procedural_limewash", "procedural_matte_paint"}:
        noise = nodes.new(type="ShaderNodeTexNoise")
        noise.inputs["Scale"].default_value = float(spec.get("noise_scale", 42.0) or 42.0)
        noise.inputs["Detail"].default_value = float(spec.get("noise_detail", 8.0) or 8.0)
        noise.inputs["Roughness"].default_value = 0.56
        ramp = make_color_ramp(nodes, shifted_color(base_color, 0.94), secondary, 0.12, 1.0)
        links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
        if "Base Color" in bsdf.inputs:
            links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
        apply_bump_from_fac(
            nodes,
            links,
            noise.outputs["Fac"],
            bsdf,
            float(spec.get("bump_strength", 0.014) or 0.014),
            0.06,
        )
    elif texture_type == "procedural_wood_plank":
        plank = nodes.new(type="ShaderNodeTexBrick")
        plank.offset = 0.5
        plank.offset_frequency = 2
        plank.inputs["Color1"].default_value = base_color
        plank.inputs["Color2"].default_value = secondary
        plank.inputs["Mortar"].default_value = grain
        plank.inputs["Scale"].default_value = float(spec.get("plank_scale", 4.0) or 4.0)
        plank.inputs["Mortar Size"].default_value = float(spec.get("mortar_size", 0.012) or 0.012)
        plank.inputs["Mortar Smooth"].default_value = 0.025
        plank.inputs["Brick Width"].default_value = float(spec.get("plank_width", 1.25) or 1.25)
        plank.inputs["Row Height"].default_value = float(spec.get("plank_height", 0.18) or 0.18)
        if "Base Color" in bsdf.inputs:
            links.new(plank.outputs["Color"], bsdf.inputs["Base Color"])
        apply_bump_from_fac(
            nodes,
            links,
            plank.outputs["Fac"],
            bsdf,
            float(spec.get("bump_strength", 0.03) or 0.03),
            0.022,
        )
    elif texture_type == "procedural_low_pile_carpet":
        noise = nodes.new(type="ShaderNodeTexNoise")
        noise.inputs["Scale"].default_value = float(spec.get("noise_scale", 72.0) or 72.0)
        noise.inputs["Detail"].default_value = float(spec.get("noise_detail", 12.0) or 12.0)
        noise.inputs["Roughness"].default_value = 0.7
        ramp = make_color_ramp(nodes, shifted_color(base_color, 0.88), secondary, 0.25, 1.0)
        links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
        if "Base Color" in bsdf.inputs:
            links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
        apply_bump_from_fac(
            nodes,
            links,
            noise.outputs["Fac"],
            bsdf,
            float(spec.get("bump_strength", 0.018) or 0.018),
            0.035,
        )
    elif texture_type == "procedural_tile":
        brick = nodes.new(type="ShaderNodeTexBrick")
        brick.offset = 0.0
        brick.offset_frequency = 1
        brick.squash = 1.0
        brick.squash_frequency = 1
        brick.inputs["Color1"].default_value = base_color
        brick.inputs["Color2"].default_value = secondary
        brick.inputs["Mortar"].default_value = shifted_color(base_color, 0.45)
        brick.inputs["Scale"].default_value = float(spec.get("tile_scale", 5.0) or 5.0)
        brick.inputs["Mortar Size"].default_value = float(spec.get("mortar_size", 0.018) or 0.018)
        links.new(brick.outputs["Color"], bsdf.inputs["Base Color"])
        apply_bump_from_fac(
            nodes,
            links,
            brick.outputs["Fac"],
            bsdf,
            float(spec.get("bump_strength", 0.018) or 0.018),
            0.025,
        )


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []
    parser = argparse.ArgumentParser(description="Assemble a scene GLB with Blender.")
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--asset-dir", required=True, type=Path)
    parser.add_argument("--output-glb", required=True, type=Path)
    parser.add_argument("--preview-image", type=Path)
    parser.add_argument("--preview-image-center", type=Path)
    parser.add_argument("--relationship-preview", type=Path)
    return parser.parse_args(argv)


def clear_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def make_floor_texture_image(
    name: str,
    texture_type: str,
    base_color: tuple[float, float, float, float],
    secondary_color: tuple[float, float, float, float],
    size: int = 512,
) -> bpy.types.Image:
    def encode_srgb(color: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
        def encode(channel: float) -> float:
            channel = max(0.0, min(1.0, channel))
            if channel <= 0.0031308:
                return 12.92 * channel
            return 1.055 * (channel ** (1.0 / 2.4)) - 0.055

        return (encode(color[0]), encode(color[1]), encode(color[2]), color[3])

    image = bpy.data.images.new(name, width=size, height=size, alpha=True)
    image.colorspace_settings.name = "sRGB"
    pixels: list[float] = []
    if texture_type == "procedural_wood_plank":
        row_height = 64
        plank_length = 128
        mortar = 3
        for y in range(size):
            row = y // row_height
            local_y = y % row_height
            offset = (row % 2) * (plank_length // 2)
            for x in range(size):
                shifted_x = (x + offset) % plank_length
                if local_y < mortar or shifted_x < mortar:
                    color = shifted_color(base_color, 0.48)
                else:
                    plank_index = row * 8 + (x + offset) // plank_length
                    variation = 0.82 + ((plank_index * 37) % 23) / 100.0
                    grain = 0.035 * math.sin(x * 0.21 + plank_index * 1.7)
                    mix = 0.22 + ((plank_index * 13) % 17) / 100.0
                    color = tuple(
                        max(
                            0.0,
                            min(
                                1.0,
                                (base_color[channel] * (1.0 - mix) + secondary_color[channel] * mix)
                                * variation
                                + grain,
                            ),
                        )
                        for channel in range(3)
                    ) + (1.0,)
                pixels.extend(encode_srgb(color))
    elif texture_type in {"procedural_tile", "procedural_stone_tile"}:
        tile_size = 72
        mortar = 4
        mortar_color = shifted_color(base_color, 0.52)
        for y in range(size):
            tile_y = y // tile_size
            for x in range(size):
                tile_x = x // tile_size
                if x % tile_size < mortar or y % tile_size < mortar:
                    color = mortar_color
                else:
                    variation = 0.93 + ((tile_x * 11 + tile_y * 17) % 9) / 100.0
                    source = base_color if (tile_x + tile_y) % 2 == 0 else secondary_color
                    if texture_type == "procedural_stone_tile":
                        variation += 0.035 * math.sin(x * 0.043 + y * 0.071 + tile_x * 1.9)
                    color = tuple(
                        max(0.0, min(1.0, source[channel] * variation))
                        for channel in range(3)
                    ) + (1.0,)
                pixels.extend(encode_srgb(color))
    elif texture_type == "procedural_terrazzo":
        tile_size = 128
        mortar = 3
        chip_colors = (
            shifted_color(base_color, 0.48),
            shifted_color(secondary_color, 0.72),
            (0.50, 0.27, 0.20, 1.0),
            (0.20, 0.35, 0.39, 1.0),
        )
        for y in range(size):
            for x in range(size):
                if x % tile_size < mortar or y % tile_size < mortar:
                    color = shifted_color(base_color, 0.68)
                else:
                    surface = 0.96 + 0.025 * math.sin(x * 0.031 + y * 0.047)
                    color = tuple(
                        max(0.0, min(1.0, base_color[channel] * surface))
                        for channel in range(3)
                    ) + (1.0,)
                    chip_hash = ((x * 73856093) ^ (y * 19349663) ^ ((x + y) * 83492791)) & 0xFFFF
                    if chip_hash > 64220:
                        chip = chip_colors[(chip_hash // 73) % len(chip_colors)]
                        color = chip
                pixels.extend(encode_srgb(color))
    else:
        for y in range(size):
            for x in range(size):
                noise = (
                    0.035 * math.sin(x * 0.071 + y * 0.029)
                    + 0.018 * math.sin(x * 0.017 - y * 0.061)
                )
                mix = 0.16 + 0.08 * math.sin((x + y) * 0.011)
                color = tuple(
                    max(
                        0.0,
                        min(
                            1.0,
                            base_color[channel] * (1.0 - mix)
                            + secondary_color[channel] * mix
                            + noise,
                        ),
                    )
                    for channel in range(3)
                ) + (1.0,)
                pixels.extend(encode_srgb(color))
    image.pixels.foreach_set(pixels)
    image.update()
    image.pack()
    return image


def make_wall_texture_image(
    name: str,
    texture_type: str,
    base_color: tuple[float, float, float, float],
    secondary_color: tuple[float, float, float, float],
    size: int = 512,
    contrast: float = 1.0,
) -> bpy.types.Image:
    """Create a subtle, deterministic, tileable wall finish for glTF export."""

    def encode_srgb(color: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
        def encode(channel: float) -> float:
            channel = max(0.0, min(1.0, channel))
            if channel <= 0.0031308:
                return 12.92 * channel
            return 1.055 * (channel ** (1.0 / 2.4)) - 0.055

        return (encode(color[0]), encode(color[1]), encode(color[2]), color[3])

    image = bpy.data.images.new(name, width=size, height=size, alpha=True)
    image.colorspace_settings.name = "sRGB"
    pixels: list[float] = []
    limewash = texture_type in {"procedural_limewash", "procedural_clay_plaster"}
    for y in range(size):
        phase_y = math.tau * y / size
        for x in range(size):
            phase_x = math.tau * x / size
            if texture_type == "procedural_wood_slat":
                period = size / 12.0
                gap = 6
                local_x = x % period
                if local_x < gap:
                    color = shifted_color(base_color, 0.30)
                else:
                    slat = x // period
                    variation = 0.86 + ((slat * 17) % 19) / 100.0
                    grain = 0.025 * math.sin(y * 0.085 + slat * 1.7)
                    color = tuple(
                        max(0.0, min(1.0, secondary_color[channel] * variation + grain))
                        for channel in range(3)
                    ) + (1.0,)
                pixels.extend(encode_srgb(color))
                continue
            if texture_type == "procedural_brick_wall":
                brick_w, brick_h, mortar = 112, 54, 5
                row = y // brick_h
                shifted_x = (x + (brick_w // 2 if row % 2 else 0)) % brick_w
                if shifted_x < mortar or y % brick_h < mortar:
                    color = (0.62, 0.58, 0.51, 1.0)
                else:
                    brick = (x + row * 31) // brick_w
                    variation = 0.82 + ((brick * 23 + row * 11) % 24) / 100.0
                    source = base_color if (brick + row) % 2 else secondary_color
                    color = tuple(
                        max(0.0, min(1.0, source[channel] * variation))
                        for channel in range(3)
                    ) + (1.0,)
                pixels.extend(encode_srgb(color))
                continue
            fine = (
                0.52 * math.sin(7.0 * phase_x + 5.0 * phase_y)
                + 0.30 * math.cos(13.0 * phase_x - 9.0 * phase_y)
                + 0.18 * math.sin(23.0 * phase_x + 19.0 * phase_y)
            )
            broad = (
                0.55 * math.sin(2.0 * phase_x + phase_y)
                + 0.45 * math.cos(phase_x - 2.0 * phase_y)
            ) if limewash else 0.0
            if texture_type == "procedural_linen_wallpaper":
                weave = 0.55 * math.sin(48.0 * phase_x) + 0.45 * math.sin(52.0 * phase_y)
                fine = 0.65 * fine + 0.35 * weave
            elif texture_type == "procedural_microcement":
                broad = 0.65 * math.sin(1.5 * phase_x + phase_y) + 0.35 * math.cos(phase_x - 1.5 * phase_y)
            mix = 0.10 + 0.035 * fine + (0.045 * broad if limewash else 0.0)
            value_shift = contrast * (0.007 * fine + (0.012 * broad if limewash else 0.0))
            color = tuple(
                max(
                    0.0,
                    min(
                        1.0,
                        base_color[channel] * (1.0 - mix)
                        + secondary_color[channel] * mix
                        + value_shift,
                    ),
                )
                for channel in range(3)
            ) + (1.0,)
            pixels.extend(encode_srgb(color))
    image.pixels.foreach_set(pixels)
    image.update()
    image.pack()
    return image


def add_exportable_wall_pbr(mat, bsdf, spec, texture_type):
    """Packed image inputs survive GLB export, unlike a procedural Bump node."""
    import numpy as np
    size = 512
    y, x = np.mgrid[0:size, 0:size] / size
    fine = .52*np.sin(math.tau*(7*x+5*y)) + .30*np.cos(math.tau*(13*x-9*y)) + .18*np.sin(math.tau*(23*x+19*y))
    if texture_type == 'procedural_wood_slat':
        # Twelve slats per UV tile, with rounded groove transitions.
        height = .5 + .5*np.tanh(8*(np.cos(math.tau*12*x)+.82))
    else:
        height = .5 + .35*fine + .15*np.sin(math.tau*(2*x+y))
    relief = float(spec.get('finish_relief_m', .0006))
    tile_m = float(spec.get('texture_scale_m', 1.0))
    dx = (np.roll(height,-1,axis=1)-np.roll(height,1,axis=1))*relief*size/(2*tile_m)
    dy = (np.roll(height,-1,axis=0)-np.roll(height,1,axis=0))*relief*size/(2*tile_m)
    normals = np.stack((-dx,-dy,np.ones_like(dx)),axis=-1)
    normals /= np.linalg.norm(normals,axis=-1,keepdims=True)
    pixels = np.ones((size,size,4),dtype=np.float32)
    pixels[:,:,:3] = normals*.5+.5
    normal = bpy.data.images.new(mat.name+'_normal',width=size,height=size,alpha=True)
    normal.colorspace_settings.name='Non-Color'
    normal.pixels.foreach_set(pixels.ravel());normal.update();normal.pack()
    nodes,links=mat.node_tree.nodes,mat.node_tree.links
    tex=nodes.new('ShaderNodeTexImage');tex.image=normal;tex.extension='REPEAT'
    decode=nodes.new('ShaderNodeNormalMap');decode.space='TANGENT'
    links.new(tex.outputs['Color'],decode.inputs['Color']);links.new(decode.outputs['Normal'],bsdf.inputs['Normal'])
    rough=np.clip(float(spec.get('roughness',.85))+.045*fine,0,1)
    pixels[:,:,:3]=rough[:,:,None]
    image=bpy.data.images.new(mat.name+'_roughness',width=size,height=size,alpha=True)
    image.colorspace_settings.name='Non-Color'
    image.pixels.foreach_set(pixels.ravel());image.update();image.pack()
    tex=nodes.new('ShaderNodeTexImage');tex.image=image;tex.extension='REPEAT'
    links.new(tex.outputs['Color'],bsdf.inputs['Roughness'])
    mat['exported_finish_relief_m']=relief


def make_material(
    name: str,
    color: tuple[float, float, float, float],
    spec: object | None = None,
) -> bpy.types.Material:
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = color
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF") if mat.node_tree else None
    if bsdf:
        if "Base Color" in bsdf.inputs:
            bsdf.inputs["Base Color"].default_value = color
        if "Alpha" in bsdf.inputs:
            bsdf.inputs["Alpha"].default_value = color[3]
        if "Roughness" in bsdf.inputs:
            roughness = 0.82
            if isinstance(spec, dict):
                try:
                    roughness = float(spec.get("roughness", roughness) or roughness)
                except (TypeError, ValueError):
                    pass
            bsdf.inputs["Roughness"].default_value = max(0.0, min(1.0, roughness))
    texture_image = None
    if isinstance(spec, dict) and spec.get("texture_image"):
        candidate = Path(str(spec.get("texture_image")))
        if candidate.exists():
            texture_image = candidate
    if texture_image and mat.node_tree and bsdf:
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        tex = nodes.new(type="ShaderNodeTexImage")
        tex.name = "sampled_floor_image_texture" if name.startswith("floor") else "sampled_image_texture"
        tex.image = bpy.data.images.load(str(texture_image), check_existing=True)
        tex.extension = "REPEAT"
        links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    elif isinstance(spec, dict) and mat.node_tree and bsdf:
        texture_type = str(spec.get("texture_type") or "")
        generated_floor = name.startswith("floor") and texture_type in {
            "procedural_wood_plank",
            "procedural_tile",
            "procedural_stone_tile",
            "procedural_terrazzo",
            "procedural_concrete",
        }
        generated_wall = name.startswith("wall_") and texture_type in {
            "procedural_painted_plaster",
            "procedural_limewash",
            "procedural_matte_paint",
            "procedural_clay_plaster",
            "procedural_linen_wallpaper",
            "procedural_wood_slat",
            "procedural_microcement",
            "procedural_brick_wall",
        }
        if bool(spec.get("embed_generated_texture")) and (generated_floor or generated_wall):
            texture_factory = make_floor_texture_image if generated_floor else make_wall_texture_image
            generated = texture_factory(
                f"{name}_{texture_type}",
                texture_type,
                color,
                normalized_rgba(spec.get("secondary_color"), shifted_color(color, 1.08)),
                **({"contrast": float(spec.get("finish_contrast", 1.0))} if generated_wall else {}),
            )
            tex = mat.node_tree.nodes.new(type="ShaderNodeTexImage")
            tex.name = "generated_floor_texture" if generated_floor else "generated_wall_texture"
            tex.image = generated
            tex.extension = "REPEAT"
            mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
            if generated_wall and spec.get('embed_pbr_maps'):
                add_exportable_wall_pbr(mat, bsdf, spec, texture_type)
        else:
            apply_procedural_texture(mat, bsdf, color, spec)
    return mat


def material_color_from_spec(spec: object, fallback: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    if not isinstance(spec, dict):
        return fallback
    raw_color = spec.get("base_color") or spec.get("color") or spec.get("diffuse_color")
    color = normalized_rgba(raw_color, fallback)
    try:
        alpha = float(spec.get("alpha", color[3]) or color[3])
    except (TypeError, ValueError):
        alpha = color[3]
    return (color[0], color[1], color[2], max(0.0, min(1.0, alpha)))


def material_by_name(
    name: str,
    color: tuple[float, float, float, float],
    spec: object | None = None,
) -> bpy.types.Material:
    existing = bpy.data.materials.get(name)
    if existing:
        return existing
    return make_material(name, color, spec)


def is_rug_plan(obj_plan: dict) -> bool:
    text = " ".join(
        str(obj_plan.get(key, ""))
        for key in ("id", "category", "semantic_class", "layout_role", "description", "asset_prompt")
    )
    normalized = text.lower().replace("_", " ")
    return any(keyword in normalized for keyword in ("rug", "carpet", "floor mat", "area rug"))


def apply_material_override(objects: list[bpy.types.Object], mat: bpy.types.Material) -> None:
    for obj in objects:
        data = getattr(obj, "data", None)
        if obj.type not in TARGET_TYPES or data is None or not hasattr(data, "materials"):
            continue
        data.materials.clear()
        data.materials.append(mat)


def add_box(
    name: str,
    center: tuple[float, float, float],
    extents: tuple[float, float, float],
    mat: bpy.types.Material,
) -> bpy.types.Object:
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=center)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = extents
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(mat)
    return obj


def apply_planar_xy_uv(
    obj: bpy.types.Object,
    width: float,
    length: float,
    repeat_x: float = 2.0,
    repeat_y: float = 3.0,
) -> None:
    mesh = obj.data
    if not isinstance(mesh, bpy.types.Mesh):
        return
    uv_layer = mesh.uv_layers.active or mesh.uv_layers.new(name="UVMap")
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            vertex = mesh.vertices[mesh.loops[loop_index].vertex_index]
            uv_layer.data[loop_index].uv = (
                (vertex.co.x / max(width, 1e-6) + 0.5) * repeat_x,
                (vertex.co.y / max(length, 1e-6) + 0.5) * repeat_y,
            )


def apply_continuous_wall_uv(
    obj: bpy.types.Object,
    wall: str,
    texture_scale_m: float,
) -> None:
    """Project wall UVs from room-space coordinates so split panels stay aligned."""

    mesh = obj.data
    if not isinstance(mesh, bpy.types.Mesh):
        return
    scale = max(float(texture_scale_m), 1e-6)
    uv_layer = mesh.uv_layers.active or mesh.uv_layers.new(name="UVMap")
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            vertex = mesh.vertices[mesh.loops[loop_index].vertex_index]
            world = obj.matrix_world @ vertex.co
            along = world.x if wall in {"north", "south"} else world.y
            uv_layer.data[loop_index].uv = (along / scale, world.z / scale)


def add_rug_underlay(obj_plan: dict, mat: bpy.types.Material) -> None:
    dims = obj_plan.get("dimensions") if isinstance(obj_plan.get("dimensions"), dict) else {}
    width = float(dims.get("width", 1.0) or 1.0)
    length = float(dims.get("length", 1.0) or 1.0)
    height = min(max(float(dims.get("height", 0.018) or 0.018), 0.008), 0.024)
    x = float(obj_plan.get("x", 0.0) or 0.0)
    y = float(obj_plan.get("y", 0.0) or 0.0)
    z = float(obj_plan.get("z", 0.0) or 0.0) + height * 0.5 + 0.002
    yaw = math.radians(
        float(obj_plan.get("yaw", 0.0) or 0.0)
        + float(obj_plan.get("footprint_yaw_offset_degrees", 0.0) or 0.0)
    )
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(x, y, z))
    obj = bpy.context.object
    obj.name = f"{obj_plan.get('id', 'rug')}_visual_underlay"
    obj["scene_object_id"] = str(obj_plan['id'])
    obj["scene_auxiliary_geometry"] = "rug_visual_underlay"
    obj.dimensions = (width, length, height)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.rotation_euler[2] = yaw
    obj.data.materials.append(mat)


def architecture_openings(architecture: object, wall: str) -> list[dict[str, float | str]]:
    if not isinstance(architecture, dict):
        return []
    openings: list[dict[str, float | str]] = []
    for opening_type, key in (("door", "doors"), ("window", "windows")):
        raw_items = architecture.get(key, [])
        if not isinstance(raw_items, list):
            continue
        for raw in raw_items:
            if not isinstance(raw, dict) or str(raw.get("wall")) != wall:
                continue
            center = float(raw.get("center", 0.0) or 0.0)
            opening_width = float(raw.get("width", 0.0) or 0.0)
            bottom = 0.0 if opening_type == "door" else float(raw.get("sill_height", 0.0) or 0.0)
            openings.append(
                {
                    "id": str(raw.get("id") or f"{opening_type}_{len(openings)}"),
                    "type": opening_type,
                    "start": center - opening_width / 2.0,
                    "end": center + opening_width / 2.0,
                    "bottom": bottom,
                    "top": bottom + float(raw.get("height", 0.0) or 0.0),
                }
            )
    return openings


def solid_vertical_intervals(
    active_openings: list[dict[str, float | str]], wall_height: float
) -> list[tuple[float, float]]:
    blocked = sorted(
        (
            max(0.0, float(item["bottom"])),
            min(wall_height, float(item["top"])),
        )
        for item in active_openings
    )
    solids: list[tuple[float, float]] = []
    cursor = 0.0
    for bottom, top in blocked:
        if bottom > cursor + 1e-5:
            solids.append((cursor, bottom))
        cursor = max(cursor, top)
    if cursor < wall_height - 1e-5:
        solids.append((cursor, wall_height))
    return solids


def add_wall_panels(
    wall: str,
    room_width: float,
    room_length: float,
    room_height: float,
    openings: list[dict[str, float | str]],
    mat: bpy.types.Material,
    material_spec: object = None,
) -> None:
    extent = room_width if wall in {"north", "south"} else room_length
    endpoints = {0.0, extent}
    for opening in openings:
        endpoints.add(max(0.0, min(extent, float(opening["start"]))))
        endpoints.add(max(0.0, min(extent, float(opening["end"]))))
    ordered = sorted(endpoints)
    panel_index = 0
    for start, end in zip(ordered, ordered[1:]):
        if end - start <= 1e-5:
            continue
        midpoint = (start + end) / 2.0
        active = [
            item
            for item in openings
            if float(item["start"]) < midpoint < float(item["end"])
        ]
        for bottom, top in solid_vertical_intervals(active, room_height):
            if top - bottom <= 1e-5:
                continue
            along_center = (start + end) / 2.0
            z_center = (bottom + top) / 2.0
            if wall == "north":
                center = (along_center, room_length + 0.04, z_center)
                extents = (end - start, 0.08, top - bottom)
            elif wall == "south":
                center = (along_center, -0.04, z_center)
                extents = (end - start, 0.08, top - bottom)
            elif wall == "east":
                center = (room_width + 0.04, along_center, z_center)
                extents = (0.08, end - start, top - bottom)
            else:
                center = (-0.04, along_center, z_center)
                extents = (0.08, end - start, top - bottom)
            panel = add_box(f"wall_{wall}_panel_{panel_index}", center, extents, mat)
            texture_scale_m = (
                float(material_spec.get("texture_scale_m", 1.0) or 1.0)
                if isinstance(material_spec, dict)
                else 1.0
            )
            apply_continuous_wall_uv(panel, wall, texture_scale_m)
            if isinstance(material_spec, dict):
                panel["wall_material_id"] = str(
                    material_spec.get("material_id") or "unspecified"
                )
            panel_index += 1


def add_wall_aligned_box(
    name: str,
    wall: str,
    room_width: float,
    room_length: float,
    along_center: float,
    z_center: float,
    along_size: float,
    depth: float,
    z_size: float,
    mat: bpy.types.Material,
) -> None:
    if wall == "north":
        center = (along_center, room_length, z_center)
        extents = (along_size, depth, z_size)
    elif wall == "south":
        center = (along_center, 0.0, z_center)
        extents = (along_size, depth, z_size)
    elif wall == "east":
        center = (room_width, along_center, z_center)
        extents = (depth, along_size, z_size)
    else:
        center = (0.0, along_center, z_center)
        extents = (depth, along_size, z_size)
    add_box(name, center, extents, mat)
    bpy.context.object["architecture_wall"] = wall


def add_door_leaf(
    door: dict[str, object],
    room_width: float,
    room_length: float,
    mat: bpy.types.Material,
) -> None:
    wall = str(door.get("wall", "east"))
    center = float(door.get("center", 0.75) or 0.75)
    door_width = float(door.get("width", 0.9) or 0.9)
    door_height = float(door.get("height", 2.1) or 2.1)
    angle = math.radians(float(door.get("open_angle_degrees", 28.0) or 28.0))
    start = center - door_width / 2.0
    if wall == "east":
        hinge = Vector((room_width - 0.015, start, 0.0))
        direction = Vector((-math.sin(angle), math.cos(angle), 0.0))
        extents = (0.045, door_width, door_height)
        yaw = angle
    elif wall == "west":
        hinge = Vector((0.015, start, 0.0))
        direction = Vector((math.sin(angle), math.cos(angle), 0.0))
        extents = (0.045, door_width, door_height)
        yaw = -angle
    elif wall == "north":
        hinge = Vector((start, room_length - 0.015, 0.0))
        direction = Vector((math.cos(angle), -math.sin(angle), 0.0))
        extents = (door_width, 0.045, door_height)
        yaw = -angle
    else:
        hinge = Vector((start, 0.015, 0.0))
        direction = Vector((math.cos(angle), math.sin(angle), 0.0))
        extents = (door_width, 0.045, door_height)
        yaw = angle
    leaf_center = hinge + direction * (door_width / 2.0)
    add_box(
        str(door.get("id") or "entry_door") + "_leaf",
        (leaf_center.x, leaf_center.y, door_height / 2.0),
        extents,
        mat,
    )
    bpy.context.object.rotation_euler[2] = yaw
    bpy.context.object["architecture_wall"] = wall


ARCHITECTURE_FINISHES = {
    "soft_white_black": {
        "frame": (0.88, 0.88, 0.84, 1.0),
        "body": (0.82, 0.82, 0.78, 1.0),
        "hardware": (0.05, 0.05, 0.045, 1.0),
    },
    "soft_white": {
        "frame": (0.90, 0.90, 0.87, 1.0),
        "body": (0.87, 0.88, 0.85, 1.0),
        "hardware": (0.22, 0.22, 0.20, 1.0),
    },
    "warm_oak_brass": {
        "frame": (0.42, 0.23, 0.10, 1.0),
        "body": (0.60, 0.37, 0.16, 1.0),
        "hardware": (0.68, 0.47, 0.12, 1.0),
    },
    "light_oak_black": {
        "frame": (0.58, 0.40, 0.20, 1.0),
        "body": (0.72, 0.55, 0.31, 1.0),
        "hardware": (0.055, 0.055, 0.05, 1.0),
    },
    "dark_oak_black": {
        "frame": (0.20, 0.11, 0.055, 1.0),
        "body": (0.32, 0.18, 0.08, 1.0),
        "hardware": (0.04, 0.04, 0.035, 1.0),
    },
    "dark_timber": {
        "frame": (0.20, 0.11, 0.055, 1.0),
        "body": (0.28, 0.15, 0.07, 1.0),
        "hardware": (0.04, 0.04, 0.035, 1.0),
    },
    "charcoal_steel": {
        "frame": (0.055, 0.06, 0.065, 1.0),
        "body": (0.10, 0.11, 0.12, 1.0),
        "hardware": (0.40, 0.42, 0.43, 1.0),
    },
    "dark_bronze": {
        "frame": (0.055, 0.032, 0.018, 1.0),
        "body": (0.10, 0.055, 0.025, 1.0),
        "hardware": (0.54, 0.37, 0.13, 1.0),
    },
    "walnut_brass": {
        "frame": (0.22, 0.09, 0.035, 1.0),
        "body": (0.38, 0.16, 0.06, 1.0),
        "hardware": (0.72, 0.51, 0.16, 1.0),
    },
    "walnut": {
        "frame": (0.24, 0.10, 0.04, 1.0),
        "body": (0.36, 0.15, 0.055, 1.0),
        "hardware": (0.42, 0.28, 0.10, 1.0),
    },
}


def opening_finish_materials(opening: dict, opening_type: str) -> dict[str, bpy.types.Material]:
    raw = opening.get("finish_profile")
    raw = raw if isinstance(raw, dict) else {}
    profile_id = str(raw.get("profile_id") or ("soft_white_black" if opening_type == "door" else "soft_white"))
    palette = ARCHITECTURE_FINISHES.get(profile_id, ARCHITECTURE_FINISHES["soft_white"])
    return {
        "frame": material_by_name(f"architecture_{profile_id}_frame", palette["frame"]),
        "body": material_by_name(f"architecture_{profile_id}_body", palette["body"]),
        "hardware": material_by_name(f"architecture_{profile_id}_hardware", palette["hardware"]),
        "glass": material_by_name("architecture_window_glass", (0.43, 0.66, 0.78, 0.34)),
    }


def add_opening_finish_overlay(
    opening: dict,
    opening_type: str,
    room_width: float,
    room_length: float,
) -> None:
    """Add style-specific trim without mutating the curated source GLB."""

    mats = opening_finish_materials(opening, opening_type)
    wall = str(opening.get("wall", "north"))
    center = float(opening.get("center", 0.0) or 0.0)
    width = float(opening.get("width", 1.0) or 1.0)
    height = float(opening.get("height", 1.0) or 1.0)
    opening_id = str(opening.get("id") or opening_type)
    if opening_type == "door":
        add_wall_aligned_box(
            f"{opening_id}_finish_panel", wall, room_width, room_length,
            center, height * 0.52, max(0.1, width - 0.14), 0.018,
            max(0.1, height - 0.20), mats["body"],
        )
        for z_value in (height * 0.34, height * 0.69):
            add_wall_aligned_box(
                f"{opening_id}_finish_rail_{int(z_value * 100)}", wall,
                room_width, room_length, center, z_value,
                max(0.1, width - 0.22), 0.035, 0.035, mats["frame"],
            )
        add_wall_aligned_box(
            f"{opening_id}_finish_handle", wall, room_width, room_length,
            center + width * 0.32, min(1.02, height * 0.5),
            0.11, 0.055, 0.028, mats["hardware"],
        )
        return
    sill = float(opening.get("sill_height", 1.0) or 1.0)
    frame = 0.055
    for suffix, along in (("left", center - width / 2.0), ("right", center + width / 2.0), ("mullion", center)):
        add_wall_aligned_box(
            f"{opening_id}_finish_{suffix}", wall, room_width, room_length,
            along, sill + height / 2.0, frame, 0.14, height, mats["frame"],
        )
    for suffix, z_value in (("bottom", sill), ("top", sill + height)):
        add_wall_aligned_box(
            f"{opening_id}_finish_{suffix}", wall, room_width, room_length,
            center, z_value, width + frame * 2.0, 0.14, frame, mats["frame"],
        )


def add_architecture_details(
    architecture: object,
    room_width: float,
    room_length: float,
    asset_dir: Path | None = None,
) -> None:
    if not isinstance(architecture, dict):
        return
    frame = 0.07
    depth = 0.12

    for raw in architecture.get("doors", []):
        if not isinstance(raw, dict):
            continue
        if import_architecture_asset(
            raw, "door", room_width, room_length, asset_dir
        ):
            add_opening_finish_overlay(raw, "door", room_width, room_length)
            continue
        mats = opening_finish_materials(raw, "door")
        wall = str(raw.get("wall", "east"))
        center = float(raw.get("center", 0.75) or 0.75)
        opening_width = float(raw.get("width", 0.9) or 0.9)
        opening_height = float(raw.get("height", 2.1) or 2.1)
        opening_id = str(raw.get("id") or "entry_door")
        for suffix, along in (("left", center - opening_width / 2.0), ("right", center + opening_width / 2.0)):
            add_wall_aligned_box(
                f"{opening_id}_frame_{suffix}", wall, room_width, room_length,
                along, opening_height / 2.0, frame, depth, opening_height, mats["frame"],
            )
        add_wall_aligned_box(
            f"{opening_id}_frame_top", wall, room_width, room_length,
            center, opening_height + frame / 2.0, opening_width + frame * 2.0,
            depth, frame, mats["frame"],
        )
        add_door_leaf(raw, room_width, room_length, mats["body"])

    for raw in architecture.get("windows", []):
        if not isinstance(raw, dict):
            continue
        if import_architecture_asset(
            raw, "window", room_width, room_length, asset_dir
        ):
            add_opening_finish_overlay(raw, "window", room_width, room_length)
            continue
        mats = opening_finish_materials(raw, "window")
        wall = str(raw.get("wall", "north"))
        center = float(raw.get("center", 0.0) or 0.0)
        opening_width = float(raw.get("width", 1.0) or 1.0)
        opening_height = float(raw.get("height", 1.0) or 1.0)
        sill = float(raw.get("sill_height", 1.0) or 1.0)
        opening_id = str(raw.get("id") or "window")
        add_wall_aligned_box(
            f"{opening_id}_glass", wall, room_width, room_length,
            center, sill + opening_height / 2.0, opening_width - frame,
            0.025, opening_height - frame, mats["glass"],
        )
        for suffix, along in (("left", center - opening_width / 2.0), ("right", center + opening_width / 2.0)):
            add_wall_aligned_box(
                f"{opening_id}_frame_{suffix}", wall, room_width, room_length,
                along, sill + opening_height / 2.0, frame, depth, opening_height, mats["frame"],
            )
        for suffix, z_value in (("bottom", sill), ("top", sill + opening_height)):
            add_wall_aligned_box(
                f"{opening_id}_frame_{suffix}", wall, room_width, room_length,
                center, z_value, opening_width + frame * 2.0, depth, frame, mats["frame"],
            )
        add_opening_finish_overlay(raw, "window", room_width, room_length)


def add_room(
    room: dict[str, object],
    architecture: object = None,
    asset_dir: Path | None = None,
) -> None:
    width = float(room["width"])
    length = float(room["length"])
    height = float(room["height"])
    material_plan = room.get("materials") if isinstance(room.get("materials"), dict) else {}
    walls_plan = material_plan.get("walls") if isinstance(material_plan, dict) and isinstance(material_plan.get("walls"), dict) else {}
    global_wall_plan = material_plan.get("global_wall") if isinstance(material_plan, dict) else None
    architecture_wall_finish = architecture.get("wall_finish") if isinstance(architecture, dict) else None
    architecture_wall_finish = architecture_wall_finish if isinstance(architecture_wall_finish, dict) else {}
    architecture_default_wall = architecture_wall_finish.get("default")
    architecture_default_wall = architecture_default_wall if isinstance(architecture_default_wall, dict) else None
    architecture_wall_overrides = architecture_wall_finish.get("overrides")
    architecture_wall_overrides = architecture_wall_overrides if isinstance(architecture_wall_overrides, dict) else {}
    architecture_floor = architecture.get("floor") if isinstance(architecture, dict) else None
    architecture_floor = architecture_floor if isinstance(architecture_floor, dict) else {}
    floor_plan = architecture_floor.get("material") or (
        material_plan.get("floor") if isinstance(material_plan, dict) else None
    )
    floor_material_id = (
        str(floor_plan.get("material_id") or "warm_gray")
        if isinstance(floor_plan, dict)
        else "warm_gray"
    )
    floor_mat = make_material(
        f"floor_{floor_material_id}",
        material_color_from_spec(floor_plan, (0.82, 0.80, 0.74, 1.0)),
        floor_plan,
    )
    default_wall_plan = architecture_default_wall or global_wall_plan
    default_wall_color = material_color_from_spec(default_wall_plan, (0.89, 0.885, 0.855, 1.0))
    wall_specs = {}
    for wall_id in ("wall_north", "wall_south", "wall_west", "wall_east"):
        wall = wall_id.removeprefix("wall_")
        architecture_override = architecture_wall_overrides.get(wall)
        legacy_override = walls_plan.get(wall_id) if isinstance(walls_plan, dict) else None
        wall_specs[wall_id] = architecture_override or legacy_override or default_wall_plan
    wall_mats: dict[str, bpy.types.Material] = {}
    wall_material_cache: dict[str, bpy.types.Material] = {}
    for wall_id in ("wall_north", "wall_south", "wall_west", "wall_east"):
        spec = wall_specs[wall_id]
        cache_key = json.dumps(spec, ensure_ascii=False, sort_keys=True) if isinstance(spec, dict) else str(spec)
        material = wall_material_cache.get(cache_key)
        if material is None:
            material_id = str(spec.get("material_id") or "default") if isinstance(spec, dict) else "default"
            material = make_material(
                f"wall_{material_id}_material",
                material_color_from_spec(spec, default_wall_color),
                spec,
            )
            wall_material_cache[cache_key] = material
        wall_mats[wall_id] = material
    floor = add_box("floor", (width / 2.0, length / 2.0, -0.025), (width, length, 0.05), floor_mat)
    floor["floor_material_id"] = floor_material_id
    apply_planar_xy_uv(floor, width, length)
    if not isinstance(architecture, dict):
        legacy_walls = {
            "north": add_box("wall_north", (width / 2.0, length + 0.04, height / 2.0), (width, 0.08, height), wall_mats["wall_north"]),
            "south": add_box("wall_south", (width / 2.0, -0.04, height / 2.0), (width, 0.08, height), wall_mats["wall_south"]),
            "west": add_box("wall_west", (-0.04, length / 2.0, height / 2.0), (0.08, length, height), wall_mats["wall_west"]),
            "east": add_box("wall_east", (width + 0.04, length / 2.0, height / 2.0), (0.08, length, height), wall_mats["wall_east"]),
        }
        for wall, obj in legacy_walls.items():
            spec = wall_specs[f"wall_{wall}"]
            texture_scale_m = float(spec.get("texture_scale_m", 1.0) or 1.0) if isinstance(spec, dict) else 1.0
            apply_continuous_wall_uv(obj, wall, texture_scale_m)
        return
    for wall in ("north", "south", "west", "east"):
        add_wall_panels(
            wall,
            width,
            length,
            height,
            architecture_openings(architecture, wall),
            wall_mats[f"wall_{wall}"],
            wall_specs[f"wall_{wall}"],
        )
    add_architecture_details(architecture, width, length, asset_dir)


def imported_objects(before: set[bpy.types.Object]) -> list[bpy.types.Object]:
    return [obj for obj in bpy.context.scene.objects if obj not in before]


def axis_to_z_matrix(axis_to_z: int, axis_sign: float = 1.0) -> Matrix:
    sign = -1.0 if float(axis_sign) < 0.0 else 1.0
    if axis_to_z == 0:
        if sign < 0.0:
            return Matrix(((0.0, 0.0, 1.0, 0.0), (0.0, 1.0, 0.0, 0.0), (-1.0, 0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0)))
        return Matrix(((0.0, 0.0, -1.0, 0.0), (0.0, 1.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0)))
    if axis_to_z == 1:
        if sign < 0.0:
            return Matrix(((1.0, 0.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0), (0.0, -1.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0)))
        return Matrix(((1.0, 0.0, 0.0, 0.0), (0.0, 0.0, -1.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0)))
    return Matrix.Identity(4)


def parent_roots(objects: list[bpy.types.Object], root: bpy.types.Object) -> None:
    imported_set = set(objects)
    root_candidates = [obj for obj in objects if obj.parent not in imported_set]
    for obj in root_candidates:
        world = obj.matrix_world.copy()
        obj.parent = root
        obj.matrix_world = world


def bake_canonical_asset_reflection(
    objects: list[bpy.types.Object], axis: str
) -> dict[str, object]:
    """Bake one left/right reflection into mesh vertices before world placement."""

    axis = str(axis).lower()
    if axis not in {"x", "y"}:
        raise ValueError(f"Unsupported handedness reflection axis: {axis!r}")
    reflection = Matrix.Diagonal(
        (-1.0, 1.0, 1.0, 1.0)
        if axis == "x"
        else (1.0, -1.0, 1.0, 1.0)
    )
    renderables = [obj for obj in objects if obj.type in TARGET_TYPES]
    unsupported = [obj.name for obj in renderables if obj.type != "MESH"]
    if unsupported:
        raise RuntimeError(
            "Handedness reflection requires bakeable mesh geometry; unsupported "
            + ", ".join(unsupported)
        )
    if not renderables:
        raise RuntimeError("Handedness reflection requested for an asset with no mesh")

    reflected_vertices = 0
    for obj in renderables:
        obj.data = obj.data.copy()
        local_reflection = (
            obj.matrix_world.inverted_safe() @ reflection @ obj.matrix_world
        )
        obj.data.transform(local_reflection, shape_keys=True)
        if local_reflection.to_3x3().determinant() < 0.0:
            obj.data.flip_normals()
        obj.data.validate(clean_customdata=False)
        obj.data.update()
        reflected_vertices += len(obj.data.vertices)
    return {
        "axis": axis,
        "space": "canonical_asset_local",
        "baked": True,
        "mesh_count": len(renderables),
        "vertex_count": reflected_vertices,
    }


def transform_imported_asset(
    objects: list[bpy.types.Object], obj_plan: dict
) -> bpy.types.Object:
    axis_matrix = axis_to_z_matrix(
        int(obj_plan.get("asset_axis_to_z", 2)),
        float(obj_plan.get("asset_axis_to_z_sign", 1.0) or 1.0),
    )
    asset_local_offset = float(obj_plan.get("asset_local_yaw_offset_degrees", 0.0) or 0.0)
    canonical_transform = Matrix.Rotation(math.radians(asset_local_offset), 4, "Z") @ axis_matrix
    if canonical_transform != Matrix.Identity(4):
        # Apply once per hierarchy, including imported empty roots. Mutating
        # parent and child world transforms together can rotate a child twice.
        imported_set = set(objects)
        roots = [obj for obj in objects if obj.parent not in imported_set]
        worlds = [(obj, obj.matrix_world.copy()) for obj in roots]
        for obj, world in worlds:
            obj.matrix_world = canonical_transform @ world
        bpy.context.view_layer.update()

    reflection_result = None
    reflection_axis = str(obj_plan.get("asset_reflection_axis") or "")
    if reflection_axis:
        reflection_space = str(
            obj_plan.get("asset_reflection_space") or "canonical_asset_local"
        )
        if reflection_space != "canonical_asset_local":
            raise ValueError(
                f"Unsupported reflection space for {obj_plan['id']}: {reflection_space}"
            )
        reflection_result = bake_canonical_asset_reflection(
            objects, reflection_axis
        )
        print(
            "baked handedness reflection "
            f"for {obj_plan['id']}: axis={reflection_axis}",
            flush=True,
        )

    renderables = [obj for obj in objects if obj.type in TARGET_TYPES]
    min_v, max_v = mesh_bbox_world(renderables)
    center = (min_v + max_v) * 0.5
    extents = max_v - min_v
    dims = obj_plan["dimensions"]
    dimension_policy = obj_plan.get("dimension_policy")
    dimension_policy = dimension_policy if isinstance(dimension_policy, dict) else {}
    dimension_resolution = obj_plan.get("dimension_resolution")
    dimension_resolution = (
        dimension_resolution if isinstance(dimension_resolution, dict) else {}
    )
    if bool(dimension_policy.get("enforce_at_assembly")):
        if not dimension_resolution or not bool(dimension_resolution.get("accepted")):
            raise ValueError(
                f"Missing accepted dimension resolution for {obj_plan['id']}"
            )
        effective = dimension_resolution.get("effective_dimensions")
        if not isinstance(effective, dict):
            raise ValueError(
                f"Missing effective dimensions for {obj_plan['id']}"
            )
        for axis in ("width", "length", "height"):
            if abs(float(dims[axis]) - float(effective[axis])) > 1e-5:
                raise ValueError(
                    f"Plan dimensions changed after resolution for {obj_plan['id']}: {axis}"
                )
    target = Vector((float(dims["width"]), float(dims["length"]), float(dims["height"])))
    if any(not math.isfinite(v) or v <= 0 for v in (*extents, *target)):
        raise ValueError(f"Invalid source or target dimensions for {obj_plan['id']}")
    scale = Vector(
        (
            target.x / max(float(extents.x), 1e-6),
            target.y / max(float(extents.y), 1e-6),
            target.z / max(float(extents.z), 1e-6),
        )
    )
    mesh_fit = runtime_mesh_fit_audit(
        [float(scale.x), float(scale.y), float(scale.z)], dimension_policy, dimension_resolution
    )
    if (dimension_policy.get("enforce_at_assembly")
            or dimension_resolution.get("requires_runtime_bounds_check")
            or mesh_fit["evaluated"]):
        if not mesh_fit["evaluated"] or mesh_fit["passes"] is not True:
            raise ValueError(
                f"Runtime dimension policy failed for {obj_plan['id']}: {mesh_fit}"
            )

    root = bpy.data.objects.new(f"{obj_plan['id']}_root", None)
    bpy.context.scene.collection.objects.link(root)
    if dimension_resolution:
        root["dimension_policy_mode"] = str(
            dimension_resolution.get("policy_mode") or dimension_policy.get("mode") or ""
        )
        root["dimension_resolution_status"] = str(
            dimension_resolution.get("status") or ""
        )
        root["dimension_requested_json"] = json.dumps(
            dimension_resolution.get("requested_dimensions"), sort_keys=True
        )
        root["dimension_source_json"] = json.dumps(
            dimension_resolution.get("source_dimensions"), sort_keys=True
        )
        root["dimension_effective_json"] = json.dumps(
            dimension_resolution.get("effective_dimensions"), sort_keys=True
        )
        root["dimension_adaptation_scale_json"] = json.dumps(
            dimension_resolution.get("scale_factors"), sort_keys=True
        )
    root["imported_raw_extents"] = [float(extents.x), float(extents.y), float(extents.z)]
    root["mesh_normalization_scale"] = [float(scale.x), float(scale.y), float(scale.z)]
    root["runtime_mesh_fit_audit_json"] = json.dumps(mesh_fit, sort_keys=True)
    if reflection_result is not None:
        root["asset_reflection_axis"] = str(reflection_result["axis"])
        root["asset_reflection_space"] = str(reflection_result["space"])
        root["asset_reflection_baked"] = bool(reflection_result["baked"])
        root["asset_reflection_mesh_count"] = int(
            reflection_result["mesh_count"]
        )
        root["asset_reflection_vertex_count"] = int(
            reflection_result["vertex_count"]
        )
        root["asset_pair_role"] = str(obj_plan.get("asset_pair_role") or "")
    parent_roots(objects, root)

    yaw = math.radians(
        float(obj_plan.get("yaw", 0.0) or 0.0)
        + float(obj_plan.get("footprint_yaw_offset_degrees", 0.0) or 0.0)
    )
    final_matrix = (
        Matrix.Translation((float(obj_plan["x"]), float(obj_plan["y"]), float(obj_plan.get("z", 0.0))))
        @ Matrix.Rotation(yaw, 4, "Z")
        @ Matrix.Translation((0.0, 0.0, target.z / 2.0))
        @ Matrix.Diagonal((scale.x, scale.y, scale.z, 1.0))
        @ Matrix.Translation((-center.x, -center.y, -center.z))
    )
    if obj_plan.get("rigid_body_pose_matrix_z_up") is not None:
        pose = Matrix(obj_plan["rigid_body_pose_matrix_z_up"])
        rotation = pose.to_3x3()
        if abs(rotation.determinant() - 1.0) > 1e-6 or any(
            abs((rotation.transposed() @ rotation)[i][j] - float(i == j)) > 1e-6
            for i in range(3) for j in range(3)
        ):
            raise ValueError("Physical pose must be a proper rigid transform")
        final_matrix = pose @ Matrix.Diagonal((scale.x, scale.y, scale.z, 1.0)) @ Matrix.Translation((-center.x, -center.y, -center.z))
    root.matrix_world = final_matrix
    bpy.context.view_layer.update()
    # Undo only the final rigid placement. Comparing world AABB dimensions to
    # local target dimensions would repeat the rotated-box error at readback.
    if obj_plan.get("rigid_body_pose_matrix_z_up") is not None:
        frame = Matrix(obj_plan["rigid_body_pose_matrix_z_up"]).inverted()
    else:
        frame = Matrix.Rotation(-yaw, 4, "Z")
    actual_min, actual_max = mesh_bbox_world(renderables, frame=frame)
    actual = actual_max - actual_min
    errors = [abs(float(actual[i]) - float(target[i])) for i in range(3)]
    tolerance = 2e-5
    passes = all(error <= max(tolerance, float(target[i]) * 1e-5) for i, error in enumerate(errors))
    root["runtime_dimensions_audit_json"] = json.dumps({
        "evaluated": True, "passes": passes, "method": "evaluated_vertices_in_placement_frame",
        "actual_dimensions": list(actual), "target_dimensions": list(target),
        "absolute_errors_m": errors, "absolute_tolerance_m": tolerance,
    }, sort_keys=True)
    if not passes:
        raise ValueError(f"Actual assembled dimensions differ from plan for {obj_plan['id']}: {errors}")
    return root


def import_asset(asset_path: Path, obj_plan: dict) -> list[bpy.types.Object]:
    usage_failures = asset_usage_violations(obj_plan)
    if usage_failures:
        raise ValueError(f"Asset use constraints failed before import: {usage_failures}")
    before = set(bpy.context.scene.objects)
    bpy.ops.import_scene.gltf(filepath=str(asset_path))
    objects = imported_objects(before)
    for index, imported in enumerate(objects):
        source_name = imported.name
        if imported.type == "MESH":
            imported.name = (
                f"{obj_plan['id']}_geometry_{index:03d}_{source_name}"
            )
        else:
            imported.name = f"{obj_plan['id']}_node_{index:03d}_{source_name}"
        if getattr(imported, "data", None):
            imported.data.name = f"{obj_plan['id']}_{imported.data.name}"
    root = transform_imported_asset(objects, obj_plan)
    category = str(obj_plan.get("category") or "")
    placement_type = str(obj_plan.get("placement_type") or "floor")
    preferred_wall = str(obj_plan.get("preferred_wall") or "")
    mounted_wall = (
        preferred_wall
        if preferred_wall
        and (
            placement_type == "wall"
            or category in {"wall_art", "mirror", "wall_fixture"}
        )
        else ""
    )
    for imported in (root, *objects):
        imported["scene_object_id"] = str(obj_plan["id"])
        imported["scene_category"] = category
        imported["scene_placement_type"] = placement_type
        imported["scene_mounted_wall"] = mounted_wall
    if is_rug_plan(obj_plan) and not obj_plan.get('preserve_source_materials'):
        rug_mat = material_by_name("rug_visual_separate_from_floor", (0.86, 0.83, 0.74, 1.0))
        apply_material_override(objects, rug_mat)
        add_rug_underlay(obj_plan, rug_mat)
    return [root, *objects]


def audit_exported_dimensions(scene_glb: Path, plan: dict, report_path: Path | None = None) -> dict:
    """Reload the exported GLB and check tight dimensions in placement frames.

    This deliberately discards the current scene, so callers render/save any
    desired Blender project before invoking it.
    """
    clear_scene()
    bpy.ops.import_scene.gltf(filepath=str(scene_glb))
    bpy.context.view_layer.update()
    rows = []
    for obj_plan in plan.get("objects", []):
        identifier = str(obj_plan["id"])
        meshes = [obj for obj in bpy.context.scene.objects if obj.type in TARGET_TYPES
                  and str(obj.get("scene_object_id") or "") == identifier]
        if not meshes:
            rows.append({"object_id": identifier, "passes": False, "reason": "missing geometry"})
            continue
        yaw = math.radians(float(obj_plan.get("yaw",0)) + float(obj_plan.get("footprint_yaw_offset_degrees",0) or 0))
        frame = Matrix.Rotation(-yaw,4,"Z")
        if obj_plan.get("rigid_body_pose_matrix_z_up") is not None:
            frame = Matrix(obj_plan["rigid_body_pose_matrix_z_up"]).inverted()
        low, high = mesh_bbox_world(meshes, frame=frame)
        actual = high-low
        target = [float(obj_plan["dimensions"][axis]) for axis in ("width","length","height")]
        errors = [abs(float(actual[i])-target[i]) for i in range(3)]
        passes = all(e <= max(2e-5,target[i]*1e-5) for i,e in enumerate(errors))
        usage_failures = asset_usage_violations(obj_plan,plan.get("room"))
        rows.append(dict(object_id=identifier,evaluated=True,passes=passes and not usage_failures,
                         dimensions_m=list(actual),expected_dimensions_m=target,errors_m=errors,usage_failures=usage_failures))
    report = dict(schema="exported_glb_dimension_audit_v1",source_glb=str(scene_glb),
                  source_sha256=hashlib.sha256(scene_glb.read_bytes()).hexdigest(),
                  method="fresh GLB import; evaluated vertices; inverse rigid placement frame",
                  object_count=len(rows),passes=bool(rows) and all(r["passes"] for r in rows),results=rows)
    path = report_path or scene_glb.with_suffix(".dimensions.json")
    path.write_text(json.dumps(report,indent=2)+"\n")
    if not report["passes"]:
        raise RuntimeError(f"Exported GLB dimension/use audit failed: {path}")
    return report


def import_architecture_asset(
    opening: dict,
    opening_type: str,
    room_width: float,
    room_length: float,
    asset_dir: Path | None,
) -> bool:
    binding = opening.get("asset_binding")
    if not isinstance(binding, dict) or str(binding.get("status")) != "reused":
        return False
    staged_relative = binding.get("staged_relative")
    if not staged_relative or asset_dir is None:
        return False
    asset_path = asset_dir / str(staged_relative)
    if not asset_path.is_file():
        print(
            f"architecture asset missing, using parametric fallback: {asset_path}",
            flush=True,
        )
        return False

    wall = str(opening.get("wall") or "north")
    center = float(opening.get("center", 0.0) or 0.0)
    opening_width = float(opening.get("width", 1.0) or 1.0)
    opening_height = float(opening.get("height", 1.0) or 1.0)
    if wall == "north":
        x, y = center, room_length
    elif wall == "south":
        x, y = center, 0.0
    elif wall == "east":
        x, y = room_width, center
    else:
        x, y = 0.0, center
    z = 0.0 if opening_type == "door" else float(opening.get("sill_height", 0.0) or 0.0)
    obj_plan = {
        "id": str(opening.get("id") or opening_type),
        "dimensions": {
            "width": opening_width,
            "length": 0.08 if opening_type == "door" else 0.10,
            "height": opening_height,
        },
        "x": x,
        "y": y,
        "z": z,
        "yaw": float(binding.get("placement_yaw_degrees", 0.0) or 0.0),
        "requested_dimensions": binding.get("requested_dimensions"),
        "source_dimensions": binding.get("source_dimensions"),
        "dimension_policy": binding.get("dimension_policy"),
        "dimension_resolution": binding.get("dimension_resolution"),
        "asset_source": "curated_library",
    }
    for key in (
        "asset_axis_to_z",
        "asset_axis_to_z_sign",
        "asset_local_yaw_offset_degrees",
        "footprint_yaw_offset_degrees",
    ):
        if key in binding:
            obj_plan[key] = binding[key]
    print(
        f"importing architecture {opening_type} {obj_plan['id']}: {asset_path}",
        flush=True,
    )
    imported = import_asset(asset_path, obj_plan)
    for obj in imported:
        obj["architecture_wall"] = wall
        obj["architecture_opening_type"] = opening_type
        obj["architecture_asset_id"] = str(binding.get("asset_id") or "")
    return True


def point_at(obj: bpy.types.Object, target: Vector) -> None:
    obj.rotation_euler = (target - obj.location).to_track_quat("-Z", "Y").to_euler()


def add_area_light(
    name: str,
    location: tuple[float, float, float],
    target: Vector,
    *,
    energy: float,
    size: float,
) -> bpy.types.Object:
    bpy.ops.object.light_add(type="AREA", location=location)
    light = bpy.context.object
    light.name = name
    light.data.energy = energy
    light.data.shape = "DISK"
    light.data.size = size
    point_at(light, target)
    return light


def render_front_45_preview(
    plan: dict,
    output_path: Path,
    *,
    view: str = "left",
) -> None:
    room = plan["room"]
    width = float(room["width"])
    length = float(room["length"])
    height = float(room["height"])
    radius = max(width, length)
    target = Vector((width * 0.5, length * 0.52, min(1.0, height * 0.38)))

    if view not in {"left", "center"}:
        raise ValueError(f"Unsupported front 45 preview view: {view}")
    scene = bpy.context.scene
    for obj in list(scene.objects):
        if bool(obj.get("preview_rig")):
            bpy.data.objects.remove(obj, do_unlink=True)

    # Reset the previous render's visibility. The legacy left view uses the
    # southwest corner; the center view stays on the room's front-center axis
    # and uses a 45-degree downward sightline.
    hidden_walls = {"south", "west"} if view == "left" else {"south"}
    for obj in bpy.context.scene.objects:
        architecture_wall = str(obj.get("architecture_wall", ""))
        if architecture_wall or obj.name.startswith("wall_"):
            obj.hide_render = False
        mounted_wall = str(obj.get("scene_mounted_wall", ""))
        if architecture_wall in hidden_walls or mounted_wall in hidden_walls or any(
            obj.name.startswith(f"wall_{wall}_panel_") for wall in hidden_walls
        ):
            obj.hide_render = True

    camera_name = f"front_{view}_45_camera"
    camera_data = bpy.data.cameras.new(camera_name)
    camera = bpy.data.objects.new(camera_name, camera_data)
    bpy.context.scene.collection.objects.link(camera)
    if view == "center":
        camera_y = -radius * 0.45
        horizontal_distance = target.y - camera_y
        camera.location = (
            width * 0.5,
            camera_y,
            target.z + horizontal_distance,
        )
    else:
        camera.location = (
            width * 0.5 - radius * 0.95,
            length * 0.5 - radius * 0.95,
            max(3.2, height * 1.55),
        )
    camera["preview_rig"] = True
    camera_data.lens = 38.0
    camera_data.clip_start = 0.05
    camera_data.clip_end = 200.0
    point_at(camera, target)
    bpy.context.scene.camera = camera

    key_light = add_area_light(
        "preview_key_light",
        (width * 0.5, length * 0.15, height + 2.2),
        target,
        energy=1050.0,
        size=max(width, length) * 0.75,
    )
    key_light["preview_rig"] = True
    fill_x = width + 1.2
    fill_light = add_area_light(
        "preview_fill_light",
        (fill_x, length * 0.55, height * 1.25),
        target,
        energy=650.0,
        size=max(width, length) * 0.55,
    )
    fill_light["preview_rig"] = True
    bpy.ops.object.light_add(
        type="SUN",
        location=(width * 0.5, length * 0.5, height + 3.0),
    )
    sun = bpy.context.object
    sun.name = "preview_sun"
    sun["preview_rig"] = True
    sun.data.energy = 1.4
    sun.rotation_euler = tuple(math.radians(value) for value in (28.0, -22.0, -35.0))

    try:
        scene.render.engine = "BLENDER_EEVEE_NEXT"
    except TypeError:
        scene.render.engine = "BLENDER_EEVEE"
    if hasattr(scene, "eevee") and hasattr(scene.eevee, "taa_render_samples"):
        scene.eevee.taa_render_samples = 32
    scene.render.resolution_x = 960
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.film_transparent = False
    scene.render.filepath = str(output_path)
    if scene.world is None:
        scene.world = bpy.data.worlds.new("preview_world")
    scene.world.use_nodes = True
    background = scene.world.node_tree.nodes.get("Background") if scene.world.node_tree else None
    if background:
        background.inputs["Color"].default_value = (0.055, 0.065, 0.08, 1.0)
        background.inputs["Strength"].default_value = 0.55
    try:
        scene.view_settings.look = "AgX - Medium High Contrast"
    except TypeError:
        pass

    output_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"rendering front {view} 45 preview: {output_path}", flush=True)
    bpy.ops.render.render(write_still=True)
    if not output_path.is_file() or output_path.stat().st_size <= 0:
        raise RuntimeError(f"Blender did not create preview image: {output_path}")


def render_relationship_preview(plan: dict, output_path: Path) -> None:
    """Render a plan-authored diagnostic view of relation-heavy objects."""

    spec = plan.get("relationship_preview")
    if not isinstance(spec, dict):
        raise ValueError("relationship_preview output requires plan.relationship_preview")
    location = spec.get("camera_location")
    target_value = spec.get("target")
    if not (
        isinstance(location, list)
        and len(location) == 3
        and isinstance(target_value, list)
        and len(target_value) == 3
    ):
        raise ValueError("relationship_preview requires 3D camera_location and target")

    scene = bpy.context.scene
    for obj in list(scene.objects):
        if bool(obj.get("preview_rig")):
            bpy.data.objects.remove(obj, do_unlink=True)
    hidden_walls = {str(value) for value in spec.get("hidden_walls", ["south"])}
    for obj in scene.objects:
        architecture_wall = str(obj.get("architecture_wall", ""))
        if architecture_wall or obj.name.startswith("wall_"):
            obj.hide_render = False
        mounted_wall = str(obj.get("scene_mounted_wall", ""))
        if architecture_wall in hidden_walls or mounted_wall in hidden_walls or any(
            obj.name.startswith(f"wall_{wall}_panel_") for wall in hidden_walls
        ):
            obj.hide_render = True

    target = Vector(tuple(float(value) for value in target_value))
    camera_data = bpy.data.cameras.new("relationship_preview_camera")
    camera = bpy.data.objects.new("relationship_preview_camera", camera_data)
    scene.collection.objects.link(camera)
    camera.location = tuple(float(value) for value in location)
    camera["preview_rig"] = True
    camera_data.lens = float(spec.get("lens_mm", 48.0) or 48.0)
    camera_data.clip_start = 0.05
    camera_data.clip_end = 200.0
    point_at(camera, target)
    scene.camera = camera

    room = plan["room"]
    width = float(room["width"])
    length = float(room["length"])
    height = float(room["height"])
    for name, light_location, energy, size in [
        (
            "relationship_key_light",
            (width * 0.72, length * 0.18, height + 1.8),
            1250.0,
            max(width, length) * 0.55,
        ),
        (
            "relationship_fill_light",
            (width * 0.18, length * 0.72, height * 1.15),
            700.0,
            max(width, length) * 0.45,
        ),
    ]:
        light = add_area_light(
            name,
            light_location,
            target,
            energy=energy,
            size=size,
        )
        light["preview_rig"] = True

    try:
        scene.render.engine = "BLENDER_EEVEE_NEXT"
    except TypeError:
        scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = int(spec.get("resolution_x", 1280) or 1280)
    scene.render.resolution_y = int(spec.get("resolution_y", 900) or 900)
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.film_transparent = False
    scene.render.filepath = str(output_path)
    if scene.world is None:
        scene.world = bpy.data.worlds.new("relationship_preview_world")
    scene.world.use_nodes = True
    background = scene.world.node_tree.nodes.get("Background") if scene.world.node_tree else None
    if background:
        background.inputs["Color"].default_value = (0.06, 0.07, 0.085, 1.0)
        background.inputs["Strength"].default_value = 0.6
    output_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"rendering relationship preview: {output_path}", flush=True)
    bpy.ops.render.render(write_still=True)
    if not output_path.is_file() or output_path.stat().st_size <= 0:
        raise RuntimeError(f"Blender did not create relationship preview: {output_path}")


def main() -> None:
    args = parse_args()
    print(f"loading plan: {args.plan}", flush=True)
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    clear_scene()
    print("adding room", flush=True)
    add_room(plan["room"], plan.get("architecture"), args.asset_dir)
    for obj in plan.get("objects", []):
        asset_path = args.asset_dir / f"{obj['id']}.glb"
        if not asset_path.exists():
            raise FileNotFoundError(f"Missing asset for {obj['id']}: {asset_path}")
        print(f"importing {obj['id']}: {asset_path}", flush=True)
        import_asset(asset_path, obj)
        print(f"imported {obj['id']}", flush=True)

    args.output_glb.parent.mkdir(parents=True, exist_ok=True)
    print(f"exporting scene: {args.output_glb}", flush=True)
    bpy.ops.export_scene.gltf(
        filepath=str(args.output_glb),
        export_format="GLB",
        export_extras=True,
    )
    if args.preview_image:
        render_front_45_preview(plan, args.preview_image, view="left")
    if args.preview_image_center:
        render_front_45_preview(plan, args.preview_image_center, view="center")
    if args.relationship_preview:
        render_relationship_preview(plan, args.relationship_preview)
    audit_exported_dimensions(args.output_glb, plan)
    print(
        json.dumps(
            {
                "output_glb": str(args.output_glb),
                "preview_image": str(args.preview_image) if args.preview_image else None,
                "preview_image_center": str(args.preview_image_center) if args.preview_image_center else None,
                "relationship_preview": str(args.relationship_preview) if args.relationship_preview else None,
            },
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
