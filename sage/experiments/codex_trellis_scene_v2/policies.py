from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from .dimensions import dimension_policy_for_category

OBJECT_DEFINITIONS: dict[str, dict[str, Any]] = {
    "bed": {"dimensions": [1.8, 2.1, 1.05], "keywords": ["bed", "床", "双人床", "大床"]},
    "nightstand": {"dimensions": [0.55, 0.45, 0.62], "keywords": ["nightstand", "bedside table", "床头柜"]},
    "table_lamp": {"dimensions": [0.28, 0.28, 0.48], "keywords": ["table lamp", "table lamps", "bedside lamp", "bedside lamps", "台灯", "床头灯"]},
    "wardrobe": {"dimensions": [1.6, 0.62, 2.1], "keywords": ["wardrobe", "closet", "衣柜"]},
    "dresser": {"dimensions": [1.2, 0.5, 0.9], "keywords": ["dresser", "chest of drawers", "斗柜", "梳妆柜"]},
    "sofa": {"dimensions": [2.2, 0.92, 0.9], "keywords": ["sofa", "couch", "沙发"]},
    "coffee_table": {"dimensions": [1.1, 0.62, 0.42], "keywords": ["coffee table", "茶几"]},
    "tv_stand": {"dimensions": [1.7, 0.42, 0.58], "keywords": ["tv stand", "media console", "电视柜"]},
    "tv": {"dimensions": [1.25, 0.12, 0.75], "keywords": ["television", "tv", "电视"]},
    "accent_chair": {"dimensions": [0.82, 0.82, 0.92], "keywords": ["armchair", "accent chair", "休闲椅", "单人沙发"]},
    "side_table": {"dimensions": [0.48, 0.48, 0.55], "keywords": ["side table", "end table", "边几"]},
    "floor_lamp": {"dimensions": [0.4, 0.4, 1.65], "keywords": ["floor lamp", "落地灯"]},
    "refrigerator": {"dimensions": [0.82, 0.78, 1.9], "keywords": ["refrigerator", "fridge", "冰箱"]},
    "sink_cabinet": {"dimensions": [1.2, 0.65, 0.9], "keywords": ["sink", "sink cabinet", "水槽", "洗菜池"]},
    "stove": {"dimensions": [0.8, 0.65, 0.9], "keywords": ["stove", "range", "灶台", "炉灶"]},
    "counter": {"dimensions": [1.6, 0.65, 0.9], "keywords": ["counter", "worktop", "操作台", "橱柜"]},
    "dining_table": {"dimensions": [1.35, 0.8, 0.75], "keywords": ["dining table", "餐桌"]},
    "dining_chair": {"dimensions": [0.48, 0.52, 0.9], "keywords": ["dining chair", "餐椅"]},
    "desk": {"dimensions": [1.4, 0.72, 0.75], "keywords": ["desk", "书桌", "办公桌"]},
    "office_chair": {"dimensions": [0.62, 0.62, 1.05], "keywords": ["office chair", "desk chair", "办公椅"]},
    "bookcase": {"dimensions": [1.1, 0.36, 1.9], "keywords": ["bookcase", "bookshelf", "书柜", "书架"]},
    "cabinet": {"dimensions": [1.0, 0.48, 1.0], "keywords": ["cabinet", "文件柜", "储物柜"]},
    "area_rug": {
        "dimensions": [2.4, 1.7, 0.02],
        "keywords": ["area rug", "rug", "carpet", "地毯"],
        "placement_type": "floor_covering",
    },
    "wall_art": {
        "dimensions": [0.78, 0.045, 0.58],
        "keywords": ["wall art", "painting", "挂画", "装饰画"],
        "placement_type": "wall",
        "mount_height": 1.55,
    },
    "window": {
        "dimensions": [1.04, 0.08, 1.296],
        "keywords": ["window", "窗户", "窗"],
        "placement_type": "wall",
        "mount_height": 1.15,
    },
    "curtain_rod": {
        "dimensions": [1.45, 0.06, 0.06],
        "keywords": ["curtain rod", "窗帘杆"],
        "placement_type": "wall",
        "mount_height": 2.25,
    },
    "curtain_panel": {
        "dimensions": [0.55, 0.06, 1.9],
        "keywords": ["curtain", "curtain panel", "窗帘"],
        "placement_type": "wall",
        "mount_height": 0.25,
    },
    "potted_plant": {"dimensions": [0.24, 0.24, 0.36], "keywords": ["potted plant", "plant", "盆栽", "绿植"]},
    "alarm_clock": {"dimensions": [0.17, 0.13, 0.2], "keywords": ["alarm clock", "闹钟"]},
    "mug": {"dimensions": [0.12, 0.09, 0.11], "keywords": ["mug", "cup", "马克杯", "杯子"]},
    "book_stack": {
        "dimensions": [0.28, 0.20, 0.12],
        "keywords": ["book stack", "stack of books", "books", "书堆", "书本"],
        "placement_type": "support",
        "preferred_support_category": "desk",
    },
    "storage_box": {
        "dimensions": [0.46, 0.34, 0.28],
        "keywords": ["storage box", "storage boxes", "收纳箱", "储物箱"],
    },
    "pillow": {
        "dimensions": [0.62, 0.42, 0.16],
        "keywords": ["pillow", "pillows", "枕头"],
        "placement_type": "support",
        "preferred_support_category": "bed",
        "plural_default_count": 2,
    },
    "slipper": {
        "dimensions": [0.28, 0.12, 0.08],
        "keywords": ["slipper", "slippers", "pair of slippers", "拖鞋"],
        "plural_default_count": 2,
        "pair_instance_count": 2,
    },
    "toilet": {"dimensions": [0.42, 0.72, 0.78], "keywords": ["toilet", "马桶", "坐便器"]},
    "vanity_sink": {"dimensions": [0.9, 0.52, 0.88], "keywords": ["vanity sink", "bathroom vanity", "洗手台", "浴室柜"]},
    "shower": {"dimensions": [0.9, 0.9, 2.1], "keywords": ["shower", "shower enclosure", "淋浴", "淋浴房"]},
    "mirror": {
        "dimensions": [0.7, 0.06, 0.9],
        "keywords": ["mirror", "bathroom mirror", "镜子", "浴室镜"],
        "placement_type": "wall",
        "mount_height": 1.55,
    },
    "laundry_basket": {"dimensions": [0.45, 0.45, 0.62], "keywords": ["laundry basket", "hamper", "洗衣篮"]},
}


COMPOSITE_COMPONENT_POLICIES: dict[str, dict[str, Any]] = {
    "bed": {
        "mode": "integrated",
        "absorbs_categories": ["pillow"],
        "require_single_parent_instance": True,
        "curated_asset_fallback": "assume_composite_asset_satisfies_requirement",
    }
}


ROOM_KEYWORDS = {
    "bedroom": ["bedroom", "bed room", "卧室", "主卧", "次卧", "床"],
    "living_room": ["living room", "livingroom", "lounge", "客厅", "起居室", "沙发", "电视"],
    "kitchen": ["kitchen", "厨房", "灶台", "冰箱", "水槽"],
    "study": ["study", "home office", "office", "书房", "办公室", "书桌"],
    "restroom": ["restroom", "bathroom", "washroom", "卫生间", "浴室", "洗手间", "马桶"],
}


STYLE_KEYWORDS = {
    "modern": ["modern", "现代"],
    "warm": ["warm", "cozy", "温馨", "暖色"],
    "wood": ["wood", "wooden", "oak", "walnut", "木", "原木", "胡桃木"],
    "minimal": ["minimal", "minimalist", "极简", "简约"],
    "scandinavian": ["scandinavian", "nordic", "北欧"],
    "japanese": ["japanese", "wabi", "日式", "侘寂"],
    "industrial": ["industrial", "工业"],
    "traditional": ["traditional", "classic", "传统", "复古"],
}


FUNCTIONAL_FRONT_CLEARANCE: dict[str, float] = {
    "nightstand": 0.55,
    "wardrobe": 0.85,
    "dresser": 0.7,
    "tv_stand": 0.6,
    "refrigerator": 0.95,
    "sink_cabinet": 0.8,
    "stove": 0.85,
    "counter": 0.8,
    "desk": 0.8,
    "bookcase": 0.7,
    "cabinet": 0.7,
    "vanity_sink": 0.75,
}


def _obj(
    object_id: str,
    category: str,
    *,
    required: bool = True,
    preferred_wall: str | None = None,
    wall_constraint_strength: str | None = None,
    support_id: str | None = None,
    support_offset: tuple[float, float] | None = None,
    placement_type: str | None = None,
    mount_height: float | None = None,
    priority: int = 50,
) -> dict[str, Any]:
    definition = OBJECT_DEFINITIONS[category]
    width, length, height = definition["dimensions"]
    placement_type = placement_type or ("support" if support_id else str(definition.get("placement_type", "floor")))
    mount_height = mount_height if mount_height is not None else definition.get("mount_height")
    result = {
        "id": object_id,
        "category": category,
        "required": required,
        "priority": priority,
        "placement_type": placement_type,
        "support_id": support_id,
        "support_offset": list(support_offset or (0.0, 0.0)),
        "preferred_wall": preferred_wall,
        "wall_constraint_strength": (
            "hard"
            if preferred_wall and placement_type == "wall"
            else (wall_constraint_strength or "soft")
        ),
        "wall_constraint_provenance": "room_policy_preference" if preferred_wall else None,
        "mount_height": mount_height,
        "dimensions": {"width": width, "length": length, "height": height},
        "requested_dimensions": {"width": width, "length": length, "height": height},
        "dimension_policy": dimension_policy_for_category(category),
    }
    if preferred_wall and category in FUNCTIONAL_FRONT_CLEARANCE:
        result["facing_constraint"] = {
            "mode": "into_room",
            "wall": preferred_wall,
            "contact_face": "back",
            "primary_interaction_face": "front",
            "local_front_fallback": "-y",
            "tolerance_degrees": 15.0,
            "front_clearance_depth": FUNCTIONAL_FRONT_CLEARANCE[category],
        }
    return result


FLOOR_MATERIAL_PRESETS: dict[str, dict[str, Any]] = {
    "warm_oak_plank": {
        "texture_type": "procedural_wood_plank",
        "base_color": [0.56, 0.36, 0.19, 1.0],
        "secondary_color": [0.72, 0.51, 0.30, 1.0],
        "roughness": 0.68,
    },
    "light_oak_plank": {
        "texture_type": "procedural_wood_plank",
        "base_color": [0.69, 0.50, 0.29, 1.0],
        "secondary_color": [0.84, 0.68, 0.44, 1.0],
        "roughness": 0.66,
    },
    "walnut_plank": {
        "texture_type": "procedural_wood_plank",
        "base_color": [0.31, 0.16, 0.075, 1.0],
        "secondary_color": [0.49, 0.28, 0.13, 1.0],
        "roughness": 0.70,
    },
    "gray_wash_plank": {
        "texture_type": "procedural_wood_plank",
        "base_color": [0.42, 0.40, 0.36, 1.0],
        "secondary_color": [0.61, 0.58, 0.52, 1.0],
        "roughness": 0.72,
    },
    "beige_ceramic_tile": {
        "texture_type": "procedural_tile",
        "base_color": [0.68, 0.62, 0.51, 1.0],
        "secondary_color": [0.82, 0.78, 0.68, 1.0],
        "roughness": 0.58,
    },
    "gray_stone_tile": {
        "texture_type": "procedural_stone_tile",
        "base_color": [0.43, 0.46, 0.47, 1.0],
        "secondary_color": [0.62, 0.65, 0.65, 1.0],
        "roughness": 0.74,
    },
    "terrazzo_tile": {
        "texture_type": "procedural_terrazzo",
        "base_color": [0.72, 0.70, 0.66, 1.0],
        "secondary_color": [0.88, 0.86, 0.80, 1.0],
        "roughness": 0.64,
    },
    "polished_concrete": {
        "texture_type": "procedural_concrete",
        "base_color": [0.46, 0.47, 0.46, 1.0],
        "secondary_color": [0.58, 0.59, 0.57, 1.0],
        "roughness": 0.52,
    },
}


WALL_MATERIAL_PRESETS: dict[str, dict[str, Any]] = {
    "warm_white_plaster": {
        "texture_type": "procedural_painted_plaster",
        "base_color": [0.89, 0.87, 0.82, 1.0],
        "secondary_color": [0.96, 0.94, 0.89, 1.0],
        "roughness": 0.84,
        "noise_scale": 42.0,
        "texture_scale_m": 1.0,
    },
    "cool_white_plaster": {
        "texture_type": "procedural_painted_plaster",
        "base_color": [0.88, 0.90, 0.91, 1.0],
        "secondary_color": [0.96, 0.97, 0.98, 1.0],
        "roughness": 0.85,
        "noise_scale": 44.0,
        "texture_scale_m": 1.0,
    },
    "soft_beige_limewash": {
        "texture_type": "procedural_limewash",
        "base_color": [0.72, 0.66, 0.56, 1.0],
        "secondary_color": [0.84, 0.79, 0.70, 1.0],
        "roughness": 0.88,
        "noise_scale": 28.0,
        "texture_scale_m": 1.2,
    },
    "light_gray_matte_paint": {
        "texture_type": "procedural_matte_paint",
        "base_color": [0.66, 0.68, 0.69, 1.0],
        "secondary_color": [0.76, 0.78, 0.79, 1.0],
        "roughness": 0.82,
        "noise_scale": 48.0,
        "texture_scale_m": 1.0,
    },
    "muted_sage_matte_paint": {
        "texture_type": "procedural_matte_paint",
        "base_color": [0.39, 0.48, 0.39, 1.0],
        "secondary_color": [0.51, 0.59, 0.50, 1.0],
        "roughness": 0.83,
        "noise_scale": 46.0,
        "texture_scale_m": 1.0,
    },
    "blue_gray_matte_paint": {
        "texture_type": "procedural_matte_paint",
        "base_color": [0.38, 0.46, 0.52, 1.0],
        "secondary_color": [0.50, 0.58, 0.64, 1.0],
        "roughness": 0.82,
        "noise_scale": 46.0,
        "texture_scale_m": 1.0,
    },
}


def floor_material_preset(material_id: str) -> dict[str, Any]:
    if material_id not in FLOOR_MATERIAL_PRESETS:
        raise ValueError(f"Unsupported floor material: {material_id}")
    material = deepcopy(FLOOR_MATERIAL_PRESETS[material_id])
    material.update(
        {
            "material_id": material_id,
            "embed_generated_texture": True,
            "bump_strength": 0.025,
        }
    )
    return material


def wall_material_preset(material_id: str) -> dict[str, Any]:
    if material_id not in WALL_MATERIAL_PRESETS:
        raise ValueError(f"Unsupported wall material: {material_id}")
    material = deepcopy(WALL_MATERIAL_PRESETS[material_id])
    material.update(
        {
            "material_id": material_id,
            "embed_generated_texture": True,
            "bump_strength": 0.012,
        }
    )
    return material


def _architecture(
    *,
    window_wall: str,
    window_wall_preferences: list[str],
    prefer_window_opposite_door: bool,
    window_center: float,
    window_width: float,
    window_height: float,
    window_sill: float,
    floor_material_id: str,
    wall_material_id: str,
) -> dict[str, Any]:
    return {
        "walls": ["north", "south", "east", "west"],
        "requirements": {
            "enclosing_wall_count": 4,
            "door_count": 1,
            "window_count_min": 1,
            "window_count_max": 2,
            "floor_material_required": True,
            "wall_material_required": True,
            "window_opposite_door_preferred": prefer_window_opposite_door,
        },
        "doors": [
            {
                "id": "entry_door",
                "wall": "east",
                "center": 0.75,
                "width": 0.9,
                "height": 2.1,
                "open_angle_degrees": 28.0,
                "clearance_depth": 1.1,
                "clearance_margin": 0.15,
                "hinge_side": "lower",
                "swing_direction": "inward",
                "hinge_articulation_status": "deferred_static_metadata_only",
                "asset_policy": {
                    "mode": "prefer_library",
                    "category": "door",
                    "fallback": "parametric",
                },
            }
        ],
        "windows": [
            {
                "id": "window_main",
                "wall": window_wall,
                "center": window_center,
                "width": window_width,
                "height": window_height,
                "sill_height": window_sill,
                "asset_policy": {
                    "mode": "prefer_library",
                    "category": "window",
                    "fallback": "parametric",
                },
            }
        ],
        "window_wall_preferences": window_wall_preferences,
        "soft_rules": [
            "place doors and windows on different walls unless explicitly requested otherwise",
            "reserve door swing and approach clearance before furniture layout",
            "keep tall furniture and wall fixtures clear of window openings",
        ],
        "floor": {
            "id": "floor",
            "required": True,
            "material": floor_material_preset(floor_material_id),
        },
        "wall_finish": {
            "default": wall_material_preset(wall_material_id),
            "overrides": {},
            "max_override_walls": 1,
        },
    }


ROOM_POLICIES: dict[str, dict[str, Any]] = {
    "bedroom": {
        "room": {"width": 5.2, "length": 4.4, "height": 2.7},
        "architecture": _architecture(
            window_wall="west",
            window_wall_preferences=["west", "south", "north"],
            prefer_window_opposite_door=True,
            window_center=2.6,
            window_width=1.4,
            window_height=1.15,
            window_sill=1.05,
            floor_material_id="warm_oak_plank",
            wall_material_id="warm_white_plaster",
        ),
        "objects": [
            _obj(
                "bed",
                "bed",
                preferred_wall="north",
                wall_constraint_strength="hard",
                priority=100,
            ),
            _obj("nightstand_left", "nightstand", preferred_wall="north", priority=80),
            _obj("nightstand_right", "nightstand", preferred_wall="north", priority=80),
            _obj("lamp_left", "table_lamp", support_id="nightstand_left", support_offset=(-0.12, 0.0), priority=30),
            _obj("lamp_right", "table_lamp", support_id="nightstand_right", support_offset=(0.12, 0.0), priority=30),
            _obj("wardrobe", "wardrobe", preferred_wall="east", priority=90),
            _obj("dresser", "dresser", preferred_wall="south", priority=70),
            _obj("dresser_plant", "potted_plant", required=False, support_id="dresser", priority=25),
            _obj("bedside_clock", "alarm_clock", required=False, support_id="nightstand_left", support_offset=(0.15, 0.0), priority=20),
            _obj("bedside_mug", "mug", required=False, support_id="nightstand_right", support_offset=(-0.15, 0.0), priority=15),
        ],
        "relations": [
            ["bed", "against", "north_wall"],
            {
                "source": "nightstand_left",
                "type": "left_of",
                "target": "bed",
                "strength": "soft",
                "parameters": {
                    "reference_frame": "room",
                    "side_role": "left",
                    "role_locked": True,
                    "role_reference_frame": "room",
                    "role_source": "room_policy",
                },
            },
            {
                "source": "nightstand_right",
                "type": "right_of",
                "target": "bed",
                "strength": "soft",
                "parameters": {
                    "reference_frame": "room",
                    "side_role": "right",
                    "role_locked": True,
                    "role_reference_frame": "room",
                    "role_source": "room_policy",
                },
            },
            {
                "source": "nightstand_left",
                "type": "aligned_with",
                "target": "bed",
                "strength": "soft",
                "parameters": {
                    "reference_frame": "target_local",
                    "source_anchor": "back_face",
                    "target_anchor": "back_face",
                    "axis": "depth",
                    "alignment_tolerance": 0.1,
                },
            },
            {
                "source": "nightstand_right",
                "type": "aligned_with",
                "target": "bed",
                "strength": "soft",
                "parameters": {
                    "reference_frame": "target_local",
                    "source_anchor": "back_face",
                    "target_anchor": "back_face",
                    "axis": "depth",
                    "alignment_tolerance": 0.1,
                },
            },
            {
                "source": "nightstand_left",
                "type": "mirror_symmetric",
                "target": "nightstand_right",
                "strength": "soft",
                "parameters": {
                    "reference_id": "bed",
                    "axis": "left_right",
                    "alignment_tolerance": 0.1,
                },
            },
            ["lamp_left", "on", "nightstand_left"],
            ["lamp_right", "on", "nightstand_right"],
        ],
        "soft_rules": ["bedside symmetry", "clear access on both sides of the bed"],
        "object_budget": {"hard_min": 7, "target_max": 12, "max_auto_inferred_objects": 2, "hard_runtime_limit": 40, "floor_occupancy_min": 0.20, "floor_occupancy_max": 0.38},
        "allowed_optional_categories": ["accent_chair", "floor_lamp"],
    },
    "living_room": {
        "room": {"width": 5.8, "length": 4.8, "height": 2.7},
        "architecture": _architecture(
            window_wall="south",
            window_wall_preferences=["south", "west", "north"],
            prefer_window_opposite_door=False,
            window_center=2.9,
            window_width=1.8,
            window_height=1.2,
            window_sill=1.05,
            floor_material_id="light_oak_plank",
            wall_material_id="warm_white_plaster",
        ),
        "objects": [
            _obj("sofa", "sofa", preferred_wall="south", priority=100),
            _obj("coffee_table", "coffee_table", priority=85),
            _obj("tv_stand", "tv_stand", preferred_wall="north", priority=95),
            _obj("tv", "tv", support_id="tv_stand", priority=60),
            _obj("accent_chair", "accent_chair", preferred_wall="west", priority=75),
            _obj("side_table_left", "side_table", priority=55),
            _obj("side_table_right", "side_table", priority=55),
            _obj("floor_lamp", "floor_lamp", preferred_wall="east", priority=45),
        ],
        "relations": [
            ["sofa", "faces", "tv"],
            ["coffee_table", "in_front_of", "sofa"],
            ["tv", "on", "tv_stand"],
        ],
        "soft_rules": ["coherent seating group", "clear path from door to seating"],
        "object_budget": {"hard_min": 8, "target_max": 12, "max_auto_inferred_objects": 3, "hard_runtime_limit": 40, "floor_occupancy_min": 0.15, "floor_occupancy_max": 0.34},
        "allowed_optional_categories": ["bookcase", "cabinet", "area_rug", "wall_art"],
    },
    "kitchen": {
        "room": {"width": 5.5, "length": 4.5, "height": 2.7},
        "architecture": _architecture(
            window_wall="north",
            window_wall_preferences=["north", "south"],
            prefer_window_opposite_door=False,
            window_center=1.05,
            window_width=1.2,
            window_height=1.0,
            window_sill=1.15,
            floor_material_id="beige_ceramic_tile",
            wall_material_id="cool_white_plaster",
        ),
        "objects": [
            _obj("refrigerator", "refrigerator", preferred_wall="west", priority=100),
            _obj("sink_cabinet", "sink_cabinet", preferred_wall="north", priority=95),
            _obj("stove", "stove", preferred_wall="north", priority=95),
            _obj("counter", "counter", preferred_wall="north", priority=85),
            _obj("dining_table", "dining_table", priority=80),
            _obj("dining_chair_left", "dining_chair", priority=55),
            _obj("dining_chair_right", "dining_chair", priority=55),
        ],
        "relations": [
            ["refrigerator", "work_triangle", "sink_cabinet"],
            ["sink_cabinet", "work_triangle", "stove"],
            ["dining_chair_left", "faces", "dining_table"],
            ["dining_chair_right", "faces", "dining_table"],
        ],
        "soft_rules": ["compact refrigerator-sink-stove work triangle", "clear cooking aisle"],
        "object_budget": {"hard_min": 7, "target_max": 11, "max_auto_inferred_objects": 2, "hard_runtime_limit": 40, "floor_occupancy_min": 0.17, "floor_occupancy_max": 0.36},
        "allowed_optional_categories": ["cabinet", "wall_art"],
    },
    "study": {
        "room": {"width": 4.8, "length": 4.0, "height": 2.7},
        "architecture": _architecture(
            window_wall="north",
            window_wall_preferences=["north", "south", "west"],
            prefer_window_opposite_door=False,
            window_center=2.4,
            window_width=1.4,
            window_height=1.1,
            window_sill=1.1,
            floor_material_id="walnut_plank",
            wall_material_id="soft_beige_limewash",
        ),
        "objects": [
            _obj("desk", "desk", preferred_wall="north", priority=100),
            _obj("office_chair", "office_chair", priority=80),
            _obj("bookcase", "bookcase", preferred_wall="east", priority=90),
            _obj("cabinet", "cabinet", preferred_wall="west", priority=70),
            _obj("floor_lamp", "floor_lamp", preferred_wall="south", priority=45),
        ],
        "relations": [["office_chair", "faces", "desk"]],
        "soft_rules": ["chair faces desk", "clear path from door to desk"],
        "object_budget": {"hard_min": 5, "target_max": 9, "max_auto_inferred_objects": 2, "hard_runtime_limit": 40, "floor_occupancy_min": 0.12, "floor_occupancy_max": 0.32},
        "allowed_optional_categories": ["side_table", "accent_chair", "wall_art"],
    },
    "restroom": {
        "room": {"width": 3.4, "length": 3.0, "height": 2.7},
        "architecture": _architecture(
            window_wall="north",
            window_wall_preferences=["north", "south"],
            prefer_window_opposite_door=False,
            window_center=2.65,
            window_width=0.75,
            window_height=0.65,
            window_sill=1.65,
            floor_material_id="gray_stone_tile",
            wall_material_id="cool_white_plaster",
        ),
        "objects": [
            _obj("toilet", "toilet", preferred_wall="north", priority=100),
            _obj("vanity_sink", "vanity_sink", preferred_wall="east", priority=95),
            _obj("shower", "shower", preferred_wall="west", priority=100),
            _obj("vanity_mirror", "mirror", preferred_wall="east", placement_type="wall", mount_height=1.55, priority=80),
            _obj("laundry_basket", "laundry_basket", preferred_wall="south", priority=45),
        ],
        "relations": [
            ["vanity_mirror", "above", "vanity_sink"],
            ["shower", "separated_from", "toilet"],
        ],
        "soft_rules": ["dry and wet zones remain visually separated", "clear access to toilet and vanity"],
        "object_budget": {"hard_min": 5, "target_max": 8, "max_auto_inferred_objects": 2, "hard_runtime_limit": 40, "floor_occupancy_min": 0.16, "floor_occupancy_max": 0.38},
        "allowed_optional_categories": ["cabinet", "wall_art"],
    },
}


HARD_RULES = {
    "inside_room": True,
    "no_floor_collisions": True,
    "support_containment": True,
    "door_clearance": {"depth": 1.1, "width": 1.2},
    "wall_affinity_tolerance": 0.35,
    "main_walkway_width": 0.8,
}


def room_policy(room_type: str) -> dict[str, Any]:
    if room_type not in ROOM_POLICIES:
        raise ValueError(f"Unsupported room type: {room_type}")
    policy = deepcopy(ROOM_POLICIES[room_type])
    policy["room_type"] = room_type
    policy["hard_rules"] = deepcopy(HARD_RULES)
    policy["object_budget"]["required_object_ids"] = [
        str(obj["id"]) for obj in policy["objects"] if obj.get("required", True)
    ]
    return policy


def detect_room_type(text: str, override: str | None = None) -> str:
    if override:
        return override
    lowered = text.lower()
    scores = {
        room_type: sum(1 for keyword in keywords if keyword.lower() in lowered)
        for room_type, keywords in ROOM_KEYWORDS.items()
    }
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "bedroom"


def _contains_keyword(text: str, keyword: str) -> bool:
    lowered = text.lower()
    normalized = keyword.lower()
    if re.fullmatch(r"[a-z0-9 _-]+", normalized):
        pattern = r"(?<![a-z0-9])" + re.escape(normalized) + r"(?![a-z0-9])"
        return re.search(pattern, lowered) is not None
    return normalized in lowered


def detect_styles(text: str) -> list[str]:
    styles = [
        style
        for style, keywords in STYLE_KEYWORDS.items()
        if any(_contains_keyword(text, keyword) for keyword in keywords)
    ]
    return styles or ["modern", "warm"]


def detect_explicit_categories(text: str) -> list[str]:
    return [
        category
        for category, definition in OBJECT_DEFINITIONS.items()
        if any(_contains_keyword(text, keyword) for keyword in definition["keywords"])
    ]


_COUNT_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "七": 7,
    "六": 6,
    "五": 5,
    "四": 4,
    "三": 3,
    "两": 2,
    "二": 2,
    "一": 1,
}


def detect_explicit_category_counts(text: str) -> dict[str, int]:
    """Return requested instance counts without treating the scene target as a cap."""
    lowered = text.lower()
    counts: dict[str, int] = {}
    for category in detect_explicit_categories(text):
        definition = OBJECT_DEFINITIONS[category]
        requested = 1
        for keyword in definition["keywords"]:
            normalized = str(keyword).lower()
            if not _contains_keyword(text, normalized):
                continue
            if re.fullmatch(r"[a-z0-9 _-]+", normalized):
                keyword_pattern = re.escape(normalized)
                if not normalized.endswith("s"):
                    keyword_pattern += "s?"
                match = re.search(
                    rf"(?:exactly\s+|at\s+least\s+)?(\d+|one|two|three|four|five|six)"
                    rf"(?:\s+[a-z-]+){{0,3}}\s+{keyword_pattern}(?![a-z0-9])",
                    lowered,
                )
                if match:
                    raw_count = match.group(1)
                    requested = max(requested, int(raw_count) if raw_count.isdigit() else _COUNT_WORDS[raw_count])
                elif normalized.endswith("s") and definition.get("plural_default_count"):
                    requested = max(requested, int(definition["plural_default_count"]))
            else:
                for count_word, value in _COUNT_WORDS.items():
                    if f"{count_word}{normalized}" in lowered or f"{count_word}个{normalized}" in lowered:
                        requested = max(requested, value)
        pair_instance_count = int(definition.get("pair_instance_count", 0) or 0)
        if pair_instance_count:
            pair_match = re.search(
                rf"(?:exactly\s+|at\s+least\s+)?(\d+|one|two|three|four|five|six)"
                rf"(?:\s+[a-z-]+){{0,2}}\s+pairs?\s+of\s+{re.escape(category)}s?(?![a-z0-9])",
                lowered,
            )
            if pair_match:
                raw_count = pair_match.group(1)
                pair_count = (
                    int(raw_count)
                    if raw_count.isdigit()
                    else _COUNT_WORDS[raw_count]
                )
                requested = max(requested, pair_count * pair_instance_count)
        counts[category] = requested
    return counts
