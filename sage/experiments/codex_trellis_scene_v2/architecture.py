from __future__ import annotations

from copy import deepcopy
from typing import Any

from .policies import (
    FLOOR_MATERIAL_PRESETS,
    WALL_MATERIAL_PRESETS,
    floor_material_preset,
    wall_material_preset,
)


FLOOR_MATERIAL_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("terrazzo_tile", ("terrazzo", "水磨石")),
    ("polished_concrete", ("polished concrete", "concrete floor", "清水混凝土", "混凝土地面")),
    ("gray_stone_tile", ("gray stone", "grey stone", "slate tile", "灰色石材", "灰石", "石材地板")),
    ("beige_ceramic_tile", ("beige tile", "ceramic tile", "米色瓷砖", "陶瓷砖", "瓷砖地板")),
    ("gray_wash_plank", ("gray wash", "grey wash", "灰色木地板", "灰洗木")),
    ("walnut_plank", ("walnut floor", "walnut plank", "胡桃木地板", "深色木地板")),
    ("light_oak_plank", ("light oak", "pale oak", "浅橡木", "浅色木地板")),
    ("warm_oak_plank", ("warm oak", "oak floor", "暖橡木", "橡木地板", "原木地板")),
)

WALL_MATERIAL_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("muted_sage_matte_paint", ("sage green wall", "sage wall", "鼠尾草绿墙", "灰绿色墙")),
    ("blue_gray_matte_paint", ("blue gray wall", "blue-grey wall", "蓝灰色墙")),
    ("light_gray_matte_paint", ("light gray wall", "light grey wall", "浅灰色墙")),
    ("soft_beige_limewash", ("beige limewash wall", "limewash wall", "米色石灰墙", "石灰墙")),
    ("cool_white_plaster", ("cool white wall", "冷白墙")),
    ("warm_white_plaster", ("warm white wall", "暖白墙")),
)

WINDOW_WALL_KEYWORDS: dict[str, tuple[str, ...]] = {
    "north": ("window on the north", "north wall window", "北墙窗", "窗户在北墙", "北侧窗"),
    "south": ("window on the south", "south wall window", "南墙窗", "窗户在南墙", "南侧窗"),
    "east": ("window on the east", "east wall window", "东墙窗", "窗户在东墙", "东侧窗"),
    "west": ("window on the west", "west wall window", "西墙窗", "窗户在西墙", "西侧窗"),
}

SAME_WALL_KEYWORDS = (
    "door and window on the same wall",
    "window and door on the same wall",
    "门窗同墙",
    "门和窗在同一面墙",
    "门窗在同一侧",
)

OPPOSITE_WALL = {
    "north": "south",
    "south": "north",
    "east": "west",
    "west": "east",
}


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def _prompt_floor_material(text: str) -> str | None:
    for material_id, keywords in FLOOR_MATERIAL_KEYWORDS:
        if _contains_any(text, keywords):
            return material_id
    return None


def _prompt_wall_material(text: str) -> str | None:
    for material_id, keywords in WALL_MATERIAL_KEYWORDS:
        if _contains_any(text, keywords):
            return material_id
    return None


def _prompt_window_wall(text: str) -> str | None:
    for wall, keywords in WINDOW_WALL_KEYWORDS.items():
        if _contains_any(text, keywords):
            return wall
    return None


def _window_center(room: dict[str, Any], wall: str, opening_width: float) -> float:
    extent = float(room["width"] if wall in {"north", "south"} else room["length"])
    half = opening_width / 2.0
    return max(half + 0.05, min(extent - half - 0.05, extent / 2.0))


def plan_architecture(
    brief: dict[str, Any],
    *,
    floor_material_override: str | None = None,
    wall_material_override: str | None = None,
    accent_wall_override: str | None = None,
    accent_wall_material_override: str | None = None,
    window_wall_override: str | None = None,
) -> dict[str, Any]:
    """Freeze the room shell before asset resolution and furniture layout."""

    architecture = deepcopy(brief["architecture"])
    room = deepcopy(brief["room"])
    prompt_text = " ".join(
        str(brief.get(key) or "") for key in ("original_prompt", "expanded_description")
    )
    decisions: list[dict[str, Any]] = []
    constraint_overrides: dict[str, bool] = {
        "door_window_same_wall": False,
        "door_window_opposite_wall": False,
    }

    current_floor = architecture.get("floor", {}).get("material", {})
    default_material = str(current_floor.get("material_id") or "warm_oak_plank")
    prompt_material = _prompt_floor_material(prompt_text)
    selected_material = floor_material_override or prompt_material or default_material
    if selected_material not in FLOOR_MATERIAL_PRESETS:
        raise ValueError(f"Unsupported floor material: {selected_material}")
    architecture["floor"]["material"] = floor_material_preset(selected_material)
    decisions.append(
        {
            "decision": "floor_material",
            "value": selected_material,
            "source": "cli_override" if floor_material_override else ("prompt" if prompt_material else "room_policy"),
        }
    )

    wall_finish = architecture.get("wall_finish")
    wall_finish = deepcopy(wall_finish) if isinstance(wall_finish, dict) else {}
    current_wall_material = wall_finish.get("default")
    current_wall_material = (
        current_wall_material if isinstance(current_wall_material, dict) else {}
    )
    default_wall_material = str(
        current_wall_material.get("material_id") or "warm_white_plaster"
    )
    prompt_wall_material = _prompt_wall_material(prompt_text)
    selected_wall_material = (
        wall_material_override or prompt_wall_material or default_wall_material
    )
    if selected_wall_material not in WALL_MATERIAL_PRESETS:
        raise ValueError(f"Unsupported wall material: {selected_wall_material}")
    if bool(accent_wall_override) != bool(accent_wall_material_override):
        raise ValueError(
            "--accent-wall and --accent-wall-material must be provided together"
        )
    if accent_wall_material_override and accent_wall_material_override not in WALL_MATERIAL_PRESETS:
        raise ValueError(
            f"Unsupported accent wall material: {accent_wall_material_override}"
        )
    wall_overrides: dict[str, dict[str, Any]] = {}
    if accent_wall_override and accent_wall_material_override:
        wall_overrides[accent_wall_override] = wall_material_preset(
            accent_wall_material_override
        )
    wall_finish.update(
        {
            "default": wall_material_preset(selected_wall_material),
            "overrides": wall_overrides,
            "max_override_walls": 1,
        }
    )
    architecture["wall_finish"] = wall_finish
    decisions.append(
        {
            "decision": "wall_finish",
            "default_material_id": selected_wall_material,
            "default_source": (
                "cli_override"
                if wall_material_override
                else ("prompt" if prompt_wall_material else "room_policy")
            ),
            "override_wall": accent_wall_override,
            "override_material_id": accent_wall_material_override,
            "override_source": "cli_override" if accent_wall_override else None,
        }
    )

    doors = [item for item in architecture.get("doors", []) if isinstance(item, dict)]
    windows = [item for item in architecture.get("windows", []) if isinstance(item, dict)]
    door_walls = {str(item.get("wall")) for item in doors}
    primary_door_wall = str(doors[0].get("wall")) if doors else ""
    opposite_door_wall = OPPOSITE_WALL.get(primary_door_wall)
    requirements = architecture.get("requirements")
    requirements = requirements if isinstance(requirements, dict) else {}
    prefer_opposite = bool(requirements.get("window_opposite_door_preferred"))
    explicit_prompt_wall = _prompt_window_wall(prompt_text)
    same_wall_requested = _contains_any(prompt_text, SAME_WALL_KEYWORDS)
    selected_wall = window_wall_override or explicit_prompt_wall
    wall_source = "cli_override" if window_wall_override else ("prompt" if explicit_prompt_wall else "room_policy")

    if not selected_wall and same_wall_requested and doors:
        selected_wall = str(doors[0].get("wall", "east"))
        wall_source = "prompt_same_wall_override"
    explicit_wall_choice = bool(
        window_wall_override or explicit_prompt_wall or same_wall_requested
    )
    if selected_wall and selected_wall in door_walls:
        constraint_overrides["door_window_same_wall"] = bool(
            explicit_wall_choice
        )
    if (
        selected_wall
        and prefer_opposite
        and opposite_door_wall
        and selected_wall != opposite_door_wall
    ):
        constraint_overrides["door_window_opposite_wall"] = explicit_wall_choice

    if not selected_wall:
        current_wall = str(windows[0].get("wall")) if windows else ""
        preferences = [
            str(item) for item in architecture.get("window_wall_preferences", [])
            if str(item) in {"north", "south", "east", "west"}
        ]
        candidates = [
            opposite_door_wall if prefer_opposite else "",
            current_wall,
            *preferences,
            "north",
            "south",
            "west",
            "east",
        ]
        selected_wall = next(
            (wall for wall in candidates if wall and wall not in door_walls),
            current_wall or "north",
        )

    for window in windows:
        if str(window.get("wall")) != selected_wall:
            window["wall"] = selected_wall
            window["center"] = _window_center(room, selected_wall, float(window.get("width", 1.0)))
    architecture["windows"] = windows
    decisions.append(
        {
            "decision": "window_wall",
            "value": selected_wall,
            "source": wall_source,
            "door_walls": sorted(door_walls),
            "preferred_opposite_wall": opposite_door_wall if prefer_opposite else None,
            "same_wall_soft_constraint_overridden": constraint_overrides["door_window_same_wall"],
            "opposite_wall_soft_constraint_overridden": constraint_overrides["door_window_opposite_wall"],
        }
    )

    architecture["constraint_overrides"] = constraint_overrides
    architecture["planning"] = {
        "planner": "deterministic_architecture_skill",
        "stage_order": [
            "text_expansion",
            "architecture_planning",
            "asset_resolution",
            "object_layout",
            "validation",
        ],
        "hinge_articulation_status": "deferred_static_metadata_only",
        "decisions": deepcopy(decisions),
    }
    brief["architecture"] = architecture
    brief["architecture_planning"] = {
        "planner": "deterministic_architecture_skill",
        "floor_material_id": selected_material,
        "wall_material_id": selected_wall_material,
        "wall_material_overrides": {
            wall: material["material_id"] for wall, material in wall_overrides.items()
        },
        "window_wall": selected_wall,
        "constraint_overrides": deepcopy(constraint_overrides),
    }
    return {
        "schema": "codex_trellis_architecture_plan_v2",
        "room_type": brief["room_type"],
        "room": room,
        "architecture": deepcopy(architecture),
        "decisions": decisions,
        "stage_order": architecture["planning"]["stage_order"],
    }
