#!/usr/bin/env python3
"""Build presentation-ready bedroom/living-room GLBs and multi-view renders."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", choices=("bedroom", "living_room"), required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--source-glb", type=Path)
    parser.add_argument("--resolution", type=int, default=640)
    parser.add_argument(
        "--view",
        action="append",
        help="Render only the named view; may be repeated. The GLB is still exported.",
    )
    parser.add_argument("--skip-render", action="store_true")
    return parser.parse_args(argv)


def material(name: str, color, *, roughness=0.55, metallic=0.0):
    existing = bpy.data.materials.get(name)
    if existing is not None:
        return existing
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1.0)
    mat.use_nodes = True
    node = mat.node_tree.nodes.get("Principled BSDF")
    node.inputs["Base Color"].default_value = (*color, 1.0)
    node.inputs["Roughness"].default_value = roughness
    node.inputs["Metallic"].default_value = metallic
    return mat


def apply_bevel(obj, amount=0.025, segments=3):
    modifier = obj.modifiers.new("PresentationBevel", "BEVEL")
    modifier.width = amount
    modifier.segments = segments
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    obj.select_set(False)


def cube(name, location, dimensions, mat, *, rotation_z=0.0, bevel=0.018):
    bpy.ops.mesh.primitive_cube_add(location=location, rotation=(0.0, 0.0, rotation_z))
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = dimensions
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if bevel:
        apply_bevel(obj, min(bevel, min(dimensions) * 0.22))
    obj.data.materials.append(mat)
    return obj


def cylinder(name, location, radius, depth, mat, *, vertices=32):
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=vertices, radius=radius, depth=depth, location=location
    )
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(mat)
    apply_bevel(obj, min(0.015, radius * 0.15), 2)
    return obj


def sphere(name, location, scale, mat):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(mat)
    return obj


def add_area_light(name, location, energy, size, color, target):
    data = bpy.data.lights.new(name, "AREA")
    data.energy = energy
    data.shape = "DISK"
    data.size = size
    data.color = color
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    point_at(obj, target)
    return obj


def point_at(obj, target):
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def add_camera(name, location, target, *, lens=46.0, ortho_scale=None):
    data = bpy.data.cameras.new(name)
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    if ortho_scale is not None:
        data.type = "ORTHO"
        data.ortho_scale = ortho_scale
    else:
        data.lens = lens
    point_at(obj, target)
    return obj


def add_book_stack(prefix, base, colors, wood, *, count=4, width=0.34, depth=0.22):
    x, y, z = base
    for index in range(count):
        height = 0.035 + (index % 2) * 0.008
        cube(
            f"{prefix}_book_{index + 1:02d}",
            (x + (index % 2) * 0.012, y, z + height / 2),
            (width - index * 0.018, depth, height),
            colors[index % len(colors)],
            rotation_z=(0.025 if index % 2 else -0.018),
            bevel=0.006,
        )
        z += height + 0.004
    cube(f"{prefix}_bookmark", (x, y - depth * 0.48, z - 0.02), (0.015, 0.025, 0.10), wood, bevel=0.002)


def add_rug(name, center, size, base_mat, accent_mat):
    x, y = center
    width, length = size
    cube(name, (x, y, 0.022), (width, length, 0.035), base_mat, bevel=0.035)
    for index in range(-4, 5):
        cube(
            f"{name}_stripe_{index + 5:02d}",
            (x + index * width / 10.0, y, 0.043),
            (width / 28.0, length * 0.94, 0.006),
            accent_mat,
            bevel=0.004,
        )


def add_plant(prefix, location, pot_mat, leaf_mat, *, scale=1.0):
    x, y, z = location
    cylinder(f"{prefix}_pot", (x, y, z + 0.18 * scale), 0.18 * scale, 0.36 * scale, pot_mat)
    cylinder(f"{prefix}_soil", (x, y, z + 0.365 * scale), 0.155 * scale, 0.025 * scale, material("soil", (0.10, 0.055, 0.025), roughness=0.9))
    for index, angle in enumerate((0, 45, 95, 145, 205, 260, 315)):
        rad = math.radians(angle)
        stem_x = x + math.cos(rad) * 0.055 * scale
        stem_y = y + math.sin(rad) * 0.055 * scale
        cylinder(f"{prefix}_stem_{index:02d}", (stem_x, stem_y, z + 0.57 * scale), 0.012 * scale, 0.42 * scale, leaf_mat, vertices=16)
        leaf = sphere(
            f"{prefix}_leaf_{index:02d}",
            (
                x + math.cos(rad) * 0.20 * scale,
                y + math.sin(rad) * 0.20 * scale,
                z + (0.65 + (index % 3) * 0.08) * scale,
            ),
            (0.18 * scale, 0.075 * scale, 0.055 * scale),
            leaf_mat,
        )
        leaf.rotation_euler[2] = rad


def add_lamp(prefix, location, metal, shade, *, height=1.7):
    x, y, z = location
    cylinder(f"{prefix}_base", (x, y, z + 0.035), 0.22, 0.07, metal)
    cylinder(f"{prefix}_stem", (x, y, z + height * 0.48), 0.025, height * 0.88, metal, vertices=20)
    bpy.ops.mesh.primitive_cone_add(
        vertices=40,
        radius1=0.34,
        radius2=0.22,
        depth=0.42,
        location=(x, y, z + height),
    )
    lamp = bpy.context.object
    lamp.name = f"{prefix}_shade"
    lamp.data.materials.append(shade)


def setup_render(resolution: int):
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x = resolution
    scene.render.resolution_y = resolution
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.render.image_settings.color_mode = "RGBA"
    scene.view_settings.look = "AgX - Medium High Contrast"
    world = scene.world or bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.035, 0.045, 0.065, 1.0)
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.30


def render_views(output_dir: Path, views, hide_by_view=None):
    scene = bpy.context.scene
    outputs = []
    hide_by_view = hide_by_view or {}
    for label, camera in views:
        original_engine = scene.render.engine
        if label.endswith("_top"):
            scene.render.engine = "BLENDER_WORKBENCH"
            scene.display.shading.light = "STUDIO"
            scene.display.shading.color_type = "MATERIAL"
            scene.display.shading.show_shadows = True
            scene.display.shading.show_cavity = True
        for obj in scene.objects:
            obj.hide_render = False
        for prefix in hide_by_view.get(label, []):
            for obj in scene.objects:
                if obj.name.startswith(prefix):
                    obj.hide_render = True
        scene.camera = camera
        output_path = output_dir / f"{label}.png"
        scene.render.filepath = str(output_path)
        bpy.ops.render.render(write_still=True)
        outputs.append(str(output_path))
        scene.render.engine = original_engine
    for obj in scene.objects:
        obj.hide_render = False
    return outputs


def add_bedroom_details():
    blue = material("BedroomTextileBlue", (0.08, 0.20, 0.34), roughness=0.78)
    blue_light = material("BedroomTextileLight", (0.32, 0.50, 0.66), roughness=0.82)
    brass = material("BrushedBrass", (0.48, 0.29, 0.10), roughness=0.28, metallic=0.72)
    cream = material("BedroomCream", (0.86, 0.80, 0.70), roughness=0.72)
    dark = material("BedroomDark", (0.055, 0.065, 0.08), roughness=0.42)
    book_red = material("BookRust", (0.48, 0.12, 0.07), roughness=0.65)
    book_green = material("BookSage", (0.16, 0.31, 0.20), roughness=0.68)
    wood = material("WarmOakAccent", (0.42, 0.20, 0.075), roughness=0.56)

    cube("curtain_left", (0.10, 1.79, 1.35), (0.10, 0.38, 2.15), blue, bevel=0.04)
    cube("curtain_left_fold", (0.16, 1.86, 1.35), (0.08, 0.09, 2.08), blue_light, bevel=0.03)
    cube("curtain_right", (0.10, 3.39, 1.35), (0.10, 0.38, 2.15), blue, bevel=0.04)
    cube("curtain_right_fold", (0.16, 3.32, 1.35), (0.08, 0.09, 2.08), blue_light, bevel=0.03)
    cylinder("curtain_rod", (0.13, 2.59, 2.48), 0.025, 1.95, brass, vertices=24).rotation_euler[0] = math.radians(90)

    cube("desk_laptop_base", (4.78, 2.47, 0.785), (0.42, 0.28, 0.025), dark, bevel=0.012)
    screen = cube("desk_laptop_screen", (4.78, 2.59, 0.96), (0.42, 0.025, 0.31), dark, bevel=0.012)
    screen.rotation_euler[0] = math.radians(-8)
    add_book_stack("desk_books", (4.94, 2.02, 0.77), [book_red, book_green, cream], wood, count=3, width=0.26, depth=0.17)

    cube("wall_shelf_upper", (5.09, 3.55, 1.62), (0.16, 0.95, 0.07), wood, bevel=0.012)
    for index, z in enumerate((1.69, 1.69, 1.69, 1.69, 1.69)):
        cube(
            f"wall_shelf_book_{index + 1:02d}",
            (4.96, 3.31 + index * 0.11, z + 0.12 + (index % 2) * 0.02),
            (0.11, 0.075, 0.24 + (index % 2) * 0.04),
            [book_red, book_green, cream, blue, dark][index],
            bevel=0.006,
        )
    cylinder("wall_shelf_vase", (4.96, 3.83, 1.82), 0.09, 0.26, cream)

    cylinder("ceiling_pendant_cord", (2.6, 2.2, 2.52), 0.012, 0.34, dark, vertices=16)
    bpy.ops.mesh.primitive_cone_add(vertices=40, radius1=0.28, radius2=0.12, depth=0.27, location=(2.6, 2.2, 2.28))
    bpy.context.object.name = "ceiling_pendant_shade"
    bpy.context.object.data.materials.append(brass)
    add_area_light("BedroomKey", (2.6, 1.5, 5.8), 900, 5.0, (1.0, 0.82, 0.64), (2.6, 2.2, 0.5))
    add_area_light("BedroomFill", (-2.0, 1.8, 3.8), 650, 4.0, (0.55, 0.72, 1.0), (2.2, 2.3, 0.8))


def build_bedroom(args):
    if args.source_glb is None or not args.source_glb.is_file():
        raise FileNotFoundError("bedroom requires --source-glb")
    bpy.ops.import_scene.gltf(filepath=str(args.source_glb.resolve()))
    for obj in list(bpy.data.objects):
        if obj.type in {"CAMERA", "LIGHT"}:
            bpy.data.objects.remove(obj, do_unlink=True)
    add_bedroom_details()
    setup_render(args.resolution)
    views = [
        ("bedroom_hero", add_camera("BedroomHero", (7.6, -6.4, 5.1), (2.6, 2.25, 0.85), lens=52)),
        ("bedroom_front", add_camera("BedroomFront", (2.6, -7.2, 2.05), (2.6, 2.45, 0.95), lens=55)),
        ("bedroom_top", add_camera("BedroomTop", (2.6, 2.2, 9.8), (2.6, 2.2, 0.0), ortho_scale=6.2)),
        ("bedroom_detail", add_camera("BedroomDetail", (7.0, -1.3, 2.55), (4.55, 2.45, 0.85), lens=62)),
    ]
    hide = {
        "bedroom_hero": ["wall_south", "wall_east"],
        "bedroom_front": ["wall_south"],
        "bedroom_detail": ["wall_south", "wall_east", "entry_door"],
    }
    if args.view:
        views = [item for item in views if item[0] in set(args.view)]
        if not views:
            raise ValueError(f"no requested bedroom view found: {args.view}")
    return [] if args.skip_render else render_views(args.output_dir, views, hide)


def add_sofa(wood, upholstery, light, accent):
    cube("sofa_plinth", (3.25, 0.76, 0.24), (2.75, 0.78, 0.28), wood, bevel=0.06)
    cube("sofa_back", (3.25, 0.51, 0.91), (2.72, 0.25, 1.04), upholstery, bevel=0.10)
    cube("sofa_arm_left", (1.90, 0.88, 0.69), (0.26, 0.95, 0.72), upholstery, bevel=0.10)
    cube("sofa_arm_right", (4.60, 0.88, 0.69), (0.26, 0.95, 0.72), upholstery, bevel=0.10)
    for index in range(3):
        x = 2.35 + index * 0.90
        cube(f"sofa_seat_cushion_{index + 1}", (x, 1.00, 0.52), (0.82, 0.66, 0.22), light, bevel=0.09)
        cushion = cube(f"sofa_back_cushion_{index + 1}", (x, 0.72, 0.99), (0.78, 0.18, 0.67), light, bevel=0.10)
        cushion.rotation_euler[0] = math.radians(-7)
    cube("sofa_throw_pillow_left", (2.05, 1.02, 0.89), (0.36, 0.20, 0.42), accent, rotation_z=0.15, bevel=0.09)
    cube("sofa_throw_pillow_right", (4.42, 1.02, 0.89), (0.36, 0.20, 0.42), accent, rotation_z=-0.15, bevel=0.09)
    for x in (2.05, 4.45):
        for y in (0.55, 1.05):
            cylinder(f"sofa_leg_{x}_{y}", (x, y, 0.105), 0.035, 0.21, wood, vertices=16)


def add_lounge_chair(prefix, center, yaw, wood, upholstery, accent):
    x, y = center
    cube(f"{prefix}_seat", (x, y, 0.52), (0.76, 0.72, 0.20), upholstery, rotation_z=yaw, bevel=0.08)
    back = cube(f"{prefix}_back", (x, y - 0.30, 0.96), (0.76, 0.18, 0.82), accent, rotation_z=yaw, bevel=0.09)
    back.rotation_euler[0] = math.radians(-8)
    for sx in (-0.30, 0.30):
        for sy in (-0.27, 0.27):
            cube(f"{prefix}_leg_{sx}_{sy}", (x + sx, y + sy, 0.24), (0.07, 0.07, 0.42), wood, rotation_z=yaw, bevel=0.012)


def build_living_room(args):
    warm_white = material("LivingWarmWhite", (0.78, 0.72, 0.64), roughness=0.78)
    wall = material("LivingWall", (0.52, 0.60, 0.61), roughness=0.86)
    floor = material("LivingFloorOak", (0.34, 0.16, 0.065), roughness=0.64)
    wood = material("LivingWalnut", (0.22, 0.075, 0.025), roughness=0.48)
    sofa = material("LivingSofa", (0.16, 0.27, 0.31), roughness=0.84)
    sofa_light = material("LivingSofaLight", (0.26, 0.42, 0.45), roughness=0.88)
    rust = material("LivingRust", (0.58, 0.17, 0.07), roughness=0.78)
    cream = material("LivingCream", (0.83, 0.74, 0.59), roughness=0.80)
    black = material("LivingBlack", (0.025, 0.03, 0.035), roughness=0.32)
    glass = material("LivingGlass", (0.05, 0.09, 0.11), roughness=0.12, metallic=0.18)
    brass = material("LivingBrass", (0.52, 0.30, 0.08), roughness=0.26, metallic=0.75)
    green = material("LivingLeaf", (0.07, 0.30, 0.12), roughness=0.72)
    red = material("LivingBookRed", (0.47, 0.07, 0.04), roughness=0.68)
    blue = material("LivingBookBlue", (0.05, 0.18, 0.38), roughness=0.68)

    cube("living_floor", (3.2, 2.4, -0.04), (6.4, 4.8, 0.08), floor, bevel=0.0)
    cube("living_north_wall", (3.2, 4.84, 1.45), (6.4, 0.08, 2.9), wall, bevel=0.0)
    cube("living_west_wall", (-0.04, 2.4, 1.45), (0.08, 4.8, 2.9), wall, bevel=0.0)
    cube("living_east_wall", (6.44, 2.4, 1.45), (0.08, 4.8, 2.9), wall, bevel=0.0)

    add_rug("living_area_rug", (3.2, 2.25), (4.3, 2.55), cream, rust)
    add_sofa(wood, sofa, sofa_light, rust)
    add_lounge_chair("lounge_left", (1.10, 2.45), -0.34, wood, cream, rust)
    add_lounge_chair("lounge_right", (5.35, 2.40), 0.34, wood, cream, sofa_light)

    cube("coffee_table_top", (3.2, 2.35, 0.48), (1.65, 0.82, 0.10), wood, bevel=0.055)
    for x in (2.55, 3.85):
        for y in (2.05, 2.65):
            cylinder(f"coffee_leg_{x}_{y}", (x, y, 0.25), 0.045, 0.45, brass, vertices=20)
    add_book_stack("coffee_books", (2.92, 2.30, 0.55), [red, blue, cream], wood, count=3, width=0.42, depth=0.28)
    cylinder("coffee_tray", (3.55, 2.35, 0.57), 0.25, 0.035, black)
    cylinder("coffee_vase", (3.55, 2.35, 0.72), 0.09, 0.28, cream)
    sphere("coffee_vase_leaf", (3.55, 2.35, 0.91), (0.18, 0.08, 0.05), green)

    cube("tv_console_body", (3.2, 4.48, 0.39), (2.75, 0.46, 0.70), wood, bevel=0.045)
    for index in range(4):
        cube(f"tv_console_door_{index + 1}", (2.24 + index * 0.64, 4.235, 0.40), (0.58, 0.035, 0.55), warm_white, bevel=0.012)
    cube("television", (3.2, 4.68, 1.55), (2.25, 0.09, 1.28), black, bevel=0.045)
    cube("television_screen", (3.2, 4.625, 1.55), (2.10, 0.012, 1.13), glass, bevel=0.025)
    cube("soundbar", (3.2, 4.20, 0.81), (1.15, 0.12, 0.11), black, bevel=0.035)
    cylinder("console_vase", (4.25, 4.22, 0.90), 0.10, 0.32, rust)

    cube("bookcase_left", (0.32, 3.77, 1.25), (0.12, 1.55, 2.45), wood, bevel=0.018)
    cube("bookcase_right", (1.45, 3.77, 1.25), (0.12, 1.55, 2.45), wood, bevel=0.018)
    cube("bookcase_top", (0.885, 3.77, 2.45), (1.25, 1.55, 0.12), wood, bevel=0.018)
    for shelf_index, z in enumerate((0.18, 0.72, 1.27, 1.82)):
        cube(f"bookcase_shelf_{shelf_index + 1}", (0.885, 3.77, z), (1.25, 1.55, 0.09), wood, bevel=0.012)
        for book_index in range(6):
            height = 0.28 + (book_index % 3) * 0.05
            cube(
                f"shelf_{shelf_index + 1}_book_{book_index + 1}",
                (0.49 + book_index * 0.15, 3.18 + (book_index % 2) * 0.03, z + 0.06 + height / 2),
                (0.10, 0.28, height),
                [red, blue, cream, rust, sofa_light, warm_white][book_index],
                rotation_z=(book_index - 2.5) * 0.012,
                bevel=0.006,
            )
    add_plant("living_plant", (5.72, 4.14, 0.0), cream, green, scale=1.15)
    add_lamp("living_floor_lamp", (5.72, 1.08, 0.0), brass, cream, height=1.72)

    cube("west_window_frame", (0.08, 2.20, 1.62), (0.07, 2.05, 1.45), warm_white, bevel=0.01)
    cube("west_window_glass", (0.125, 2.20, 1.62), (0.02, 1.82, 1.25), glass, bevel=0.005)
    cube("west_curtain_left", (0.16, 1.03, 1.48), (0.12, 0.38, 2.30), rust, bevel=0.045)
    cube("west_curtain_right", (0.16, 3.37, 1.48), (0.12, 0.38, 2.30), rust, bevel=0.045)
    rod = cylinder("west_curtain_rod", (0.18, 2.20, 2.70), 0.025, 2.85, brass, vertices=24)
    rod.rotation_euler[0] = math.radians(90)

    for index, color in enumerate((rust, cream, sofa_light)):
        cube(f"wall_art_panel_{index + 1}", (5.99, 3.15 - index * 0.62, 1.62), (0.05, 0.45, 0.68), color, bevel=0.018)

    cylinder("living_pendant_cord", (3.2, 2.25, 2.67), 0.012, 0.32, black, vertices=16)
    bpy.ops.mesh.primitive_cone_add(vertices=40, radius1=0.34, radius2=0.15, depth=0.30, location=(3.2, 2.25, 2.42))
    bpy.context.object.name = "living_pendant_shade"
    bpy.context.object.data.materials.append(brass)

    setup_render(args.resolution)
    add_area_light("LivingKey", (3.2, 1.7, 6.0), 1250, 5.5, (1.0, 0.78, 0.57), (3.2, 2.25, 0.5))
    add_area_light("LivingWindowFill", (-2.4, 2.2, 3.4), 900, 4.5, (0.55, 0.72, 1.0), (2.7, 2.2, 0.8))
    add_area_light("LivingTVFill", (7.5, 3.0, 3.0), 600, 4.0, (1.0, 0.60, 0.38), (3.5, 2.4, 0.8))
    views = [
        ("living_room_hero", add_camera("LivingHero", (8.4, -7.2, 5.2), (3.15, 2.35, 0.9), lens=52)),
        ("living_room_front", add_camera("LivingFront", (3.2, -7.8, 2.25), (3.2, 2.35, 0.95), lens=55)),
        ("living_room_top", add_camera("LivingTop", (3.2, 2.4, 10.2), (3.2, 2.4, 0.0), ortho_scale=7.2)),
        ("living_room_detail", add_camera("LivingDetail", (7.1, -0.8, 2.8), (3.55, 2.45, 0.72), lens=62)),
    ]
    hide = {
        "living_room_hero": ["living_east_wall"],
        "living_room_detail": ["living_east_wall"],
    }
    if args.view:
        views = [item for item in views if item[0] in set(args.view)]
        if not views:
            raise ValueError(f"no requested living-room view found: {args.view}")
    return [] if args.skip_render else render_views(args.output_dir, views, hide)


def mesh_bounds():
    points = []
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        points.extend(obj.matrix_world @ Vector(corner) for corner in obj.bound_box)
    if not points:
        return None
    return {
        "minimum_xyz": [round(min(p[i] for p in points), 6) for i in range(3)],
        "maximum_xyz": [round(max(p[i] for p in points), 6) for i in range(3)],
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if args.scene == "bedroom":
        images = build_bedroom(args)
    else:
        images = build_living_room(args)
    glb_path = args.output_dir / f"{args.scene}_showcase.glb"
    bpy.ops.export_scene.gltf(
        filepath=str(glb_path.resolve()),
        export_format="GLB",
        export_apply=True,
        export_cameras=True,
        export_lights=True,
    )
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    report = {
        "schema": "scene_progress_showcase_v1",
        "scene": args.scene,
        "source_glb": str(args.source_glb.resolve()) if args.source_glb else None,
        "output_glb": str(glb_path.resolve()),
        "output_glb_size_bytes": glb_path.stat().st_size,
        "output_glb_sha256": sha256(glb_path),
        "rendered_views": sorted(
            str(path.resolve()) for path in args.output_dir.glob(f"{args.scene}*.png")
        ),
        "rendered_in_this_invocation": images,
        "mesh_object_count": len(meshes),
        "material_count": len(bpy.data.materials),
        "camera_count": len([obj for obj in bpy.context.scene.objects if obj.type == "CAMERA"]),
        "light_count": len([obj for obj in bpy.context.scene.objects if obj.type == "LIGHT"]),
        "bounds": mesh_bounds(),
        "presentation_asset": True,
        "benchmark_claim": False,
    }
    report_path = args.output_dir / "showcase_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
