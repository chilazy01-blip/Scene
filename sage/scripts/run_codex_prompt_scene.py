#!/usr/bin/env python3
"""Use local Codex once to plan a SAGE-style scene, then export it to GLB.

The script keeps the expensive/fragile official agent loop out of the critical
path while preserving the user-facing flow: prompt -> layout plan -> scene JSON
-> GLB export -> quick preview.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE_SCENE = os.environ.get("SAGE_CODEX_SOURCE_SCENE")
DEFAULT_OUTPUT_DIR = os.environ.get(
    "SAGE_CODEX_OUTPUT_DIR",
    "/data/wsj/main/scene_runs/codex_prompt_scene",
)
DEFAULT_EXPORT_SCRIPT = os.environ.get("SAGE_CODEX_EXPORT_SCRIPT")
DEFAULT_EXPORT_PYTHON = os.environ.get(
    "SAGE_CODEX_EXPORT_PYTHON",
    os.environ.get("SAGE_ORCH_PYTHON", "/data/wsj/anaconda3/envs/tree-sage-flow2/bin/python"),
)
DEFAULT_PREVIEW_SCRIPT = os.environ.get(
    "SAGE_CODEX_PREVIEW_SCRIPT",
    str(REPO_ROOT / "sage/scripts/render_layout_topdown.py"),
)
DEFAULT_PREVIEW_PYTHON = os.environ.get("SAGE_CODEX_PREVIEW_PYTHON", DEFAULT_EXPORT_PYTHON)
DEFAULT_MUJOCO_PYTHON = os.environ.get(
    "SAGE_CODEX_MUJOCO_PYTHON",
    "/data/wsj/anaconda3/envs/tree-sage-flow2/bin/python",
)
DEFAULT_MUJOCO_SERVER_ROOT = os.environ.get("SAGE_CODEX_MUJOCO_SERVER_ROOT")
DEFAULT_CODEX_MODEL = os.environ.get("SAGE_CODEX_MODEL", "gpt-5.6-sol")


PROMPT_PRESETS = {
    "codex_office": (
        "Generate a single compact AI research office / computer lab. It should contain two work areas, "
        "desks with matching chairs, shelves for books and components, a filing cabinet, a printer station, "
        "and a visible network router. Keep believable walking space and align furniture against walls."
    ),
    "official_room_living": (
        "A living room with a coffee table holding a small toy rubik cube, a student desk positioned away "
        "from the coffee table, and a round table with a coke can positioned away from both other tables"
    ),
    "official_room_bedroom": "A bedroom.",
    "official_room_kitchen": "A medium-sized kitchen.",
    "official_room_abandoned_restroom": "A medium-sized rusty, dusty, and abandoned restroom.",
    "official_room_starry_bedroom": "A medium-sized van gogh the starry night style bedroom.",
}


def point(x: float, y: float, z: float = 0.0) -> dict[str, float]:
    return {"x": round(float(x), 4), "y": round(float(y), 4), "z": round(float(z), 4)}


def dims(width: float, length: float, height: float) -> dict[str, float]:
    return {"width": float(width), "length": float(length), "height": float(height)}


def rot(z: float) -> dict[str, float]:
    return {"x": 0, "y": 0, "z": round(float(z), 2)}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def template_objects(template_layout: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for room in template_layout["rooms"]:
        for obj in room.get("objects", []):
            result.setdefault(obj["type"], deepcopy(obj))
    return result


def asset_catalog(templates: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    catalog = []
    for object_type, obj in sorted(templates.items()):
        catalog.append(
            {
                "type": object_type,
                "source_id": obj["source_id"],
                "dimensions": obj["dimensions"],
                "description": obj["description"],
            }
        )
    return catalog


def extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def fallback_plan(prompt_text: str) -> dict[str, Any]:
    return {
        "scene_id": "layout_codex_prompt_office",
        "room_type": "compact AI research office",
        "building_style": "modern practical office",
        "description": prompt_text,
        "room": {"width": 6.2, "length": 4.8, "ceiling_height": 2.7},
        "objects": [
            {"type": "desk", "id": "desk_primary", "x": 1.15, "y": 1.25, "rotation_z": 270},
            {"type": "chair", "id": "chair_primary", "x": 2.15, "y": 1.25, "rotation_z": 90},
            {"type": "desk", "id": "desk_secondary", "x": 4.75, "y": 1.05, "rotation_z": 0},
            {"type": "chair", "id": "chair_secondary", "x": 4.75, "y": 1.95, "rotation_z": 180},
            {"type": "shelf", "id": "shelf_north_left", "x": 1.1, "y": 4.55, "rotation_z": 180},
            {"type": "shelf", "id": "shelf_north_right", "x": 2.35, "y": 4.55, "rotation_z": 180},
            {"type": "cabinet", "id": "cabinet_west", "x": 0.25, "y": 3.45, "rotation_z": 270},
            {"type": "printer", "id": "printer_station", "x": 5.35, "y": 4.42, "rotation_z": 180},
            {"type": "router", "id": "router_station", "x": 5.86, "y": 4.43, "rotation_z": 180},
        ],
    }


def build_codex_prompt(prompt_text: str, catalog: list[dict[str, Any]]) -> str:
    return f"""
You are replacing the VLM planner for one SAGE reproduction run.
Use the user scene prompt to create a compact, plausible single-room layout plan.

User scene prompt:
{prompt_text}

Available reusable 3D asset types, with dimensions:
{json.dumps(catalog, indent=2)}

Return only JSON matching this shape:
{{
  "scene_id": "layout_codex_prompt_<short_name>",
  "room_type": "...",
  "building_style": "...",
  "description": "...",
  "room": {{"width": 4.5-8.0, "length": 3.5-6.0, "ceiling_height": 2.7}},
  "objects": [
    {{"type": "one available type", "id": "short_unique_id", "x": number, "y": number, "rotation_z": 0|90|180|270}}
  ]
}}

Rules:
- Use only available asset types. If the prompt asks for missing categories, approximate with the closest available office/lab asset.
- Place 8 to 14 total objects.
- Use a southwest-corner origin: (0, 0) is the room's southwest corner, x increases east, and y increases north.
- Every x must be in [0, room.width] and every y must be in [0, room.length]. Never use negative or centered-origin coordinates.
- Keep every object footprint, not only its center, inside the room.
- Put shelves/cabinets/printers/routers near walls.
- Put chairs facing desks.
- Avoid overlaps by keeping at least 0.45m between object centers unless they are functionally paired.
- Do not include markdown, comments, or any text outside the JSON.
""".strip()


def run_codex(prompt: str, output_dir: Path, model: str | None = None) -> dict[str, Any]:
    prompt_path = output_dir / "codex_request.txt"
    response_path = output_dir / "codex_response.txt"
    prompt_path.write_text(prompt, encoding="utf-8")

    cmd = [
        "codex",
        "exec",
        "--ignore-user-config",
        "--ignore-rules",
        "--disable",
        "plugins",
        "--disable",
        "plugin_sharing",
        "--disable",
        "plugin_hooks",
        "-c",
        'model_reasoning_effort="low"',
        "--ephemeral",
        "--cd",
        str(Path.cwd()),
        "--sandbox",
        "read-only",
        "--output-last-message",
        str(response_path),
        prompt,
    ]
    resolved_model = model or DEFAULT_CODEX_MODEL
    cmd[2:2] = ["--model", resolved_model]

    proc = subprocess.run(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=int(os.environ.get("SAGE_CODEX_TIMEOUT", "600")),
        check=False,
    )
    (output_dir / "codex_stdout.txt").write_text(proc.stdout, encoding="utf-8")
    (output_dir / "codex_stderr.txt").write_text(proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"codex exec failed with code {proc.returncode}; see {output_dir / 'codex_stderr.txt'}")
    return extract_json(response_path.read_text(encoding="utf-8"))


def make_object(template: dict[str, Any], object_id: str, room_id: str, x: float, y: float, zrot: float) -> dict[str, Any]:
    obj = deepcopy(template)
    obj["id"] = object_id
    obj["room_id"] = room_id
    obj["position"] = point(x, y, 0.0)
    obj["rotation"] = rot(zrot)
    obj["place_id"] = "floor"
    obj["placement_constraints"] = []
    return obj


def clamp_plan(plan: dict[str, Any], templates: dict[str, dict[str, Any]]) -> dict[str, Any]:
    room = plan.setdefault("room", {})
    room["width"] = min(max(float(room.get("width", 6.0)), 4.0), 8.0)
    room["length"] = min(max(float(room.get("length", 4.5)), 3.0), 6.0)
    room["ceiling_height"] = float(room.get("ceiling_height", 2.7))
    raw_objects = [obj for obj in plan.get("objects", []) if isinstance(obj, dict)]

    def centered_axis_offset(axis: str, extent: float) -> float:
        values = []
        for obj in raw_objects:
            try:
                values.append(float(obj.get(axis, 0.0)))
            except (TypeError, ValueError):
                continue
        tolerance = 0.05
        uses_centered_axis = (
            bool(values)
            and any(value < 0.0 for value in values)
            and all(-extent / 2.0 - tolerance <= value <= extent / 2.0 + tolerance for value in values)
        )
        return extent / 2.0 if uses_centered_axis else 0.0

    x_offset = centered_axis_offset("x", room["width"])
    y_offset = centered_axis_offset("y", room["length"])
    if x_offset or y_offset:
        plan["_input_coordinate_frame"] = "centered_origin_translated_to_southwest"
        plan["_coordinate_translation"] = {"x": x_offset, "y": y_offset}
    else:
        plan["_input_coordinate_frame"] = "southwest_origin"

    valid_objects = []
    seen = set()
    for idx, obj in enumerate(raw_objects):
        object_type = obj.get("type")
        if object_type not in templates:
            continue
        width = templates[object_type]["dimensions"]["width"]
        length = templates[object_type]["dimensions"]["length"]
        zrot = float(obj.get("rotation_z", 0))
        quarter_turn = int(round(zrot / 90.0)) % 2 == 1
        footprint_width = length if quarter_turn else width
        footprint_length = width if quarter_turn else length
        x = min(
            max(float(obj.get("x", 1.0)) + x_offset, footprint_width / 2 + 0.05),
            room["width"] - footprint_width / 2 - 0.05,
        )
        y = min(
            max(float(obj.get("y", 1.0)) + y_offset, footprint_length / 2 + 0.05),
            room["length"] - footprint_length / 2 - 0.05,
        )
        raw_id = re.sub(r"[^a-zA-Z0-9_]+", "_", str(obj.get("id") or f"{object_type}_{idx}")).strip("_")
        object_id = f"codex_{raw_id or object_type}_{idx:02d}"
        if object_id in seen:
            object_id = f"{object_id}_{idx}"
        seen.add(object_id)
        valid_objects.append(
            {
                "type": object_type,
                "id": object_id,
                "x": x,
                "y": y,
                "rotation_z": zrot,
            }
        )
    plan["objects"] = valid_objects[:14] or fallback_plan(plan.get("description", ""))["objects"]
    return plan


def build_layout(plan: dict[str, Any], templates: dict[str, dict[str, Any]], selected_prompt: str) -> dict[str, Any]:
    scene_id = re.sub(r"[^a-zA-Z0-9_]+", "_", str(plan.get("scene_id") or "layout_codex_prompt_scene")).strip("_")
    if not scene_id.startswith("layout_"):
        scene_id = f"layout_{scene_id}"
    room_id = "room_codex_prompt"
    room_width = float(plan["room"]["width"])
    room_length = float(plan["room"]["length"])
    ceiling = float(plan["room"].get("ceiling_height", 2.7))

    walls = [
        {"id": f"wall_{room_id}_north", "start_point": point(0, room_length), "end_point": point(room_width, room_length), "height": ceiling, "thickness": 0.1, "material": "room_6bca04af_wall"},
        {"id": f"wall_{room_id}_south", "start_point": point(0, 0), "end_point": point(room_width, 0), "height": ceiling, "thickness": 0.1, "material": "room_6bca04af_wall"},
        {"id": f"wall_{room_id}_east", "start_point": point(room_width, 0), "end_point": point(room_width, room_length), "height": ceiling, "thickness": 0.1, "material": "room_6bca04af_wall"},
        {"id": f"wall_{room_id}_west", "start_point": point(0, 0), "end_point": point(0, room_length), "height": ceiling, "thickness": 0.1, "material": "room_6bca04af_wall"},
    ]

    objects = [
        make_object(templates[item["type"]], item["id"], room_id, item["x"], item["y"], item["rotation_z"])
        for item in plan["objects"]
        if item["type"] in templates
    ]

    return {
        "id": scene_id,
        "rooms": [
            {
                "id": room_id,
                "room_type": str(plan.get("room_type") or "Codex planned room"),
                "position": point(0, 0),
                "dimensions": dims(room_width, room_length, ceiling),
                "walls": walls,
                "doors": [
                    {
                        "id": "door_codex_prompt_entry",
                        "wall_id": f"wall_{room_id}_east",
                        "position_on_wall": 0.55,
                        "width": 0.92,
                        "height": 2.05,
                        "door_type": "entry",
                        "opens_inward": True,
                        "opening": False,
                        "door_material": "Door_6",
                    }
                ],
                "objects": objects,
                "windows": [],
                "floor_material": "room_6bca04af_floor",
                "ceiling_height": ceiling,
            }
        ],
        "total_area": round(room_width * room_length, 2),
        "building_style": str(plan.get("building_style") or "practical generated scene"),
        "description": str(plan.get("description") or selected_prompt),
        "created_from_text": selected_prompt,
        "policy_analysis": {},
    }


def copy_assets(source_scene: Path, output_dir: Path) -> None:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in ["objects", "materials"]:
        shutil.copytree(source_scene / name, output_dir / name)


def run_export(layout_path: Path, output_dir: Path, python_bin: Path, export_script: Path) -> Path:
    export_dir = output_dir / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(python_bin), str(export_script), str(layout_path), str(export_dir)], check=True)
    return export_dir / layout_path.name.replace(".json", ".glb")


def run_preview(layout_path: Path, output_dir: Path, python_bin: Path, preview_script: Path) -> Path:
    preview = output_dir / "preview_topdown.png"
    subprocess.run([str(python_bin), str(preview_script), str(layout_path), str(preview)], check=True)
    return preview


def run_mujoco_check(layout_path: Path, python_bin: Path, server_root: Path | None = None) -> dict[str, Any]:
    code = f"""
from isaacsim.isaac_mcp.server import create_single_room_layout_scene_from_room, simulate_the_scene
import json, tempfile, os
layout = json.load(open({str(layout_path)!r}))
room = layout['rooms'][0]
fd, room_path = tempfile.mkstemp(suffix='.json')
os.close(fd)
json.dump(room, open(room_path, 'w'))
create_result = create_single_room_layout_scene_from_room({str(layout_path.parent)!r}, room_path)
simulate_result = simulate_the_scene()
print(json.dumps({{"create": create_result, "simulate": simulate_result}}, default=str))
os.remove(room_path)
"""
    env = os.environ.copy()
    env["SAGE_SIM_BACKEND"] = "mujoco"
    if server_root is not None:
        existing_pythonpath = env.get("PYTHONPATH")
        env["PYTHONPATH"] = os.pathsep.join(
            part for part in (str(server_root), existing_pythonpath) if part
        )
    proc = subprocess.run(
        [str(python_bin), "-c", code],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    parsed = None
    for line in reversed(proc.stdout.splitlines()):
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            parsed = candidate
            break
    simulate = parsed.get("simulate") if isinstance(parsed, dict) else None
    unstable_objects = simulate.get("unstable_objects", []) if isinstance(simulate, dict) else []
    ok = (
        proc.returncode == 0
        and isinstance(simulate, dict)
        and simulate.get("status") == "success"
        and not unstable_objects
    )
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "create": parsed.get("create") if isinstance(parsed, dict) else None,
        "simulate": simulate,
        "unstable_objects": unstable_objects,
        "ok": ok,
    }


def require_path(
    parser: argparse.ArgumentParser,
    value: str | None,
    option: str,
    env_name: str,
    *,
    directory: bool = False,
) -> Path:
    if not value:
        parser.error(f"{option} is required (or set {env_name})")
    path = Path(value).expanduser().resolve()
    valid = path.is_dir() if directory else path.is_file()
    if not valid:
        expected = "directory" if directory else "file"
        parser.error(f"{option} must point to an existing {expected}: {path}")
    return path


def source_layout_path(parser: argparse.ArgumentParser, source_scene: Path, value: str | None) -> Path:
    if value:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = source_scene / path
        path = path.resolve()
        if not path.is_file():
            parser.error(f"--source-layout must point to an existing file: {path}")
        return path

    candidates = sorted(source_scene.glob("layout*.json"))
    if len(candidates) != 1:
        parser.error(
            "--source-scene must contain exactly one layout*.json file, "
            "or pass --source-layout / set SAGE_CODEX_SOURCE_LAYOUT"
        )
    return candidates[0].resolve()


def validate_source_assets(parser: argparse.ArgumentParser, source_scene: Path) -> None:
    missing = [name for name in ("objects", "materials") if not (source_scene / name).is_dir()]
    if missing:
        parser.error(
            f"--source-scene is missing required asset directories {missing}: {source_scene}"
        )


def selected_prompt(args: argparse.Namespace) -> str:
    if args.prompt:
        return args.prompt
    if args.prompt_file:
        return Path(args.prompt_file).read_text(encoding="utf-8").strip()
    return PROMPT_PRESETS[args.prompt_preset]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one local-Codex SAGE-style prompt scene.")
    parser.add_argument("--prompt-preset", default="codex_office", choices=sorted(PROMPT_PRESETS))
    parser.add_argument("--prompt-file")
    parser.add_argument("--prompt")
    parser.add_argument("--model", default=DEFAULT_CODEX_MODEL)
    parser.add_argument(
        "--source-scene",
        default=DEFAULT_SOURCE_SCENE,
        help="Reusable SAGE scene directory (env: SAGE_CODEX_SOURCE_SCENE).",
    )
    parser.add_argument(
        "--source-layout",
        default=os.environ.get("SAGE_CODEX_SOURCE_LAYOUT"),
        help="Source layout JSON; relative paths resolve under --source-scene (env: SAGE_CODEX_SOURCE_LAYOUT).",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help="Run output directory (env: SAGE_CODEX_OUTPUT_DIR).",
    )
    parser.add_argument(
        "--export-script",
        default=DEFAULT_EXPORT_SCRIPT,
        help="SAGE export_glb.py path (env: SAGE_CODEX_EXPORT_SCRIPT).",
    )
    parser.add_argument(
        "--export-python",
        default=DEFAULT_EXPORT_PYTHON,
        help="Python used for export_glb.py (env: SAGE_CODEX_EXPORT_PYTHON).",
    )
    parser.add_argument(
        "--preview-script",
        default=DEFAULT_PREVIEW_SCRIPT,
        help="Top-down preview script (env: SAGE_CODEX_PREVIEW_SCRIPT).",
    )
    parser.add_argument(
        "--preview-python",
        default=DEFAULT_PREVIEW_PYTHON,
        help="Python used for the preview script (env: SAGE_CODEX_PREVIEW_PYTHON).",
    )
    parser.add_argument(
        "--mujoco-python",
        default=DEFAULT_MUJOCO_PYTHON,
        help="Python used for the MuJoCo check (env: SAGE_CODEX_MUJOCO_PYTHON).",
    )
    parser.add_argument(
        "--mujoco-server-root",
        default=DEFAULT_MUJOCO_SERVER_ROOT,
        help="Directory containing isaacsim/isaac_mcp (env: SAGE_CODEX_MUJOCO_SERVER_ROOT).",
    )
    parser.add_argument("--fallback-if-codex-fails", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()

    source_scene = require_path(parser, args.source_scene, "--source-scene", "SAGE_CODEX_SOURCE_SCENE", directory=True)
    source_layout = source_layout_path(parser, source_scene, args.source_layout)
    validate_source_assets(parser, source_scene)
    export_script = require_path(parser, args.export_script, "--export-script", "SAGE_CODEX_EXPORT_SCRIPT")
    export_python = require_path(parser, args.export_python, "--export-python", "SAGE_CODEX_EXPORT_PYTHON")
    preview_script = require_path(parser, args.preview_script, "--preview-script", "SAGE_CODEX_PREVIEW_SCRIPT")
    preview_python = require_path(parser, args.preview_python, "--preview-python", "SAGE_CODEX_PREVIEW_PYTHON")
    mujoco_python = require_path(parser, args.mujoco_python, "--mujoco-python", "SAGE_CODEX_MUJOCO_PYTHON")
    mujoco_server_root = None
    if args.mujoco_server_root:
        mujoco_server_root = require_path(
            parser,
            args.mujoco_server_root,
            "--mujoco-server-root",
            "SAGE_CODEX_MUJOCO_SERVER_ROOT",
            directory=True,
        )
    output_dir = Path(args.output_dir).expanduser().resolve()
    copy_assets(source_scene, output_dir)

    template_layout = load_json(source_layout)
    templates = template_objects(template_layout)
    prompt_text = selected_prompt(args)
    (output_dir / "selected_prompt.txt").write_text(prompt_text + "\n", encoding="utf-8")
    codex_prompt = build_codex_prompt(prompt_text, asset_catalog(templates))

    try:
        plan = run_codex(codex_prompt, output_dir, model=args.model)
        plan["_planner"] = "codex_exec"
    except Exception as exc:
        (output_dir / "codex_error.txt").write_text(str(exc), encoding="utf-8")
        if not args.fallback_if_codex_fails:
            raise
        plan = fallback_plan(prompt_text)
        plan["_planner"] = "fallback_after_codex_error"

    plan = clamp_plan(plan, templates)
    write_json(output_dir / "codex_plan.json", plan)
    layout = build_layout(plan, templates, prompt_text)
    layout_path = output_dir / f"{layout['id']}.json"
    write_json(layout_path, layout)

    glb_path = run_export(layout_path, output_dir, export_python, export_script)
    preview_path = run_preview(layout_path, output_dir, preview_python, preview_script)
    mujoco_report = run_mujoco_check(layout_path, mujoco_python, mujoco_server_root)
    write_json(output_dir / "mujoco_check.json", mujoco_report)

    summary = {
        "planner": plan.get("_planner"),
        "prompt_path": str(output_dir / "selected_prompt.txt"),
        "plan_path": str(output_dir / "codex_plan.json"),
        "layout_path": str(layout_path),
        "glb_path": str(glb_path),
        "preview_path": str(preview_path),
        "mujoco_check_path": str(output_dir / "mujoco_check.json"),
        "mujoco_ok": bool(mujoco_report.get("ok")),
        "mujoco_unstable_objects": mujoco_report.get("unstable_objects", []),
    }
    write_json(output_dir / "run_summary.json", summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
