from __future__ import annotations

import json
import hashlib
import os
import subprocess
from pathlib import Path
from typing import Any

from .io_utils import write_json


def write_preview_svg(plan: dict[str, Any], path: Path) -> None:
    room = plan["room"]
    room_width = float(room["width"])
    room_length = float(room["length"])
    scale = min(900.0 / room_width, 650.0 / room_length)
    margin = 70.0
    canvas_width = room_width * scale + margin * 2.0
    canvas_height = room_length * scale + margin * 2.0

    def sx(x: float) -> float:
        return margin + x * scale

    def sy(y: float) -> float:
        return canvas_height - margin - y * scale

    colors = {
        "floor": "#8db3d3",
        "support": "#d4a54f",
    }
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{canvas_width:.0f}" height="{canvas_height:.0f}" viewBox="0 0 {canvas_width:.2f} {canvas_height:.2f}">',
        '<rect width="100%" height="100%" fill="#f5f2ea"/>',
        f'<rect x="{margin:.2f}" y="{margin:.2f}" width="{room_width * scale:.2f}" height="{room_length * scale:.2f}" fill="#e7e1d4" stroke="#222" stroke-width="4"/>',
        f'<rect x="{sx(room_width - 1.1):.2f}" y="{sy(1.35):.2f}" width="{1.1 * scale:.2f}" height="{1.2 * scale:.2f}" fill="#e88c8c" opacity="0.28"/>',
    ]
    for obj in plan["objects"]:
        dims = obj["dimensions"]
        width = float(dims["width"])
        length = float(dims["length"])
        if int(round(float(obj.get("yaw", 0.0)) / 90.0)) % 2 == 1:
            width, length = length, width
        x = sx(float(obj["x"]) - width / 2.0)
        y = sy(float(obj["y"]) + length / 2.0)
        color = colors.get(str(obj.get("placement_type")), "#8db3d3")
        lines.append(
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{width * scale:.2f}" height="{length * scale:.2f}" fill="{color}" stroke="#23313f" stroke-width="2"/>'
        )
        lines.append(
            f'<text x="{sx(float(obj["x"])):.2f}" y="{sy(float(obj["y"])):.2f}" font-size="12" text-anchor="middle" fill="#111">{obj["id"]}</text>'
        )
    lines.append(
        f'<text x="{margin:.2f}" y="35" font-size="20" fill="#111">{plan["scene_id"]} / {plan["room_type"]}</text>'
    )
    lines.append("</svg>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def assemble_with_blender(
    plan_path: Path,
    asset_dir: Path,
    output_glb: Path,
    *,
    blender_bin: Path,
    preview_image: Path | None = None,
    preview_image_center: Path | None = None,
) -> dict[str, Any]:
    if not blender_bin.is_file():
        raise FileNotFoundError(f"Blender binary not found: {blender_bin}")
    assembler = Path(__file__).resolve().parents[2] / "scripts" / "blender_assemble_sage_scene.py"
    if not assembler.is_file():
        raise FileNotFoundError(f"Existing Blender assembler not found: {assembler}")
    output_glb.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(blender_bin),
        "--background",
        "--python-exit-code",
        "1",
        "--python",
        str(assembler),
        "--",
        "--plan",
        str(plan_path),
        "--asset-dir",
        str(asset_dir),
        "--output-glb",
        str(output_glb),
    ]
    if preview_image is not None:
        preview_image.parent.mkdir(parents=True, exist_ok=True)
        cmd.extend(["--preview-image", str(preview_image)])
    if preview_image_center is not None:
        preview_image_center.parent.mkdir(parents=True, exist_ok=True)
        cmd.extend(["--preview-image-center", str(preview_image_center)])
    proc = subprocess.run(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=int(os.environ.get("SAGE_BLENDER_TIMEOUT", "900")),
        check=False,
    )
    stdout_path = output_glb.parent / "blender_stdout.txt"
    stderr_path = output_glb.parent / "blender_stderr.txt"
    stdout_path.write_text(proc.stdout, encoding="utf-8")
    stderr_path.write_text(proc.stderr, encoding="utf-8")
    if proc.returncode != 0 or not output_glb.is_file() or output_glb.stat().st_size <= 0:
        raise RuntimeError(
            f"Blender assembly failed with code {proc.returncode}; see {stderr_path}"
        )
    dimensions_path = output_glb.with_suffix(".dimensions.json")
    if not dimensions_path.is_file():
        raise RuntimeError("Blender assembly omitted the actual GLB dimension readback")
    dimensions_audit = json.loads(dimensions_path.read_text())
    if (dimensions_audit.get("passes") is not True
            or dimensions_audit.get("source_sha256") != hashlib.sha256(output_glb.read_bytes()).hexdigest()):
        raise RuntimeError("Actual GLB dimension readback failed or its source binding changed")
    if preview_image is not None and (
        not preview_image.is_file() or preview_image.stat().st_size <= 0
    ):
        raise RuntimeError(
            f"Blender assembly did not create the requested preview image; see {stderr_path}"
        )
    if preview_image_center is not None and (
        not preview_image_center.is_file() or preview_image_center.stat().st_size <= 0
    ):
        raise RuntimeError(
            f"Blender assembly did not create the requested center preview image; see {stderr_path}"
        )
    return {
        "ok": True,
        "returncode": proc.returncode,
        "scene_glb": str(output_glb),
        "preview_image": str(preview_image) if preview_image else None,
        "preview_image_center": str(preview_image_center) if preview_image_center else None,
        "stdout": str(stdout_path),
        "stderr": str(stderr_path),
    }


def run_mujoco_proxy(
    plan: dict[str, Any],
    output_dir: Path,
    *,
    python_bin: Path,
) -> dict[str, Any]:
    server_root = Path(__file__).resolve().parents[2] / "server"
    backend = server_root / "isaacsim" / "isaac_mcp" / "local_mujoco_backend.py"
    if not backend.is_file():
        raise FileNotFoundError(f"Local MuJoCo backend not found: {backend}")
    room_payload = {
        "id": "room_v2_proxy",
        "dimensions": plan["room"],
        "objects": [
            {
                "id": obj["id"],
                "dimensions": obj["dimensions"],
                "position": {"x": obj["x"], "y": obj["y"], "z": obj.get("z", 0.0)},
                "rotation": {"x": 0.0, "y": 0.0, "z": obj.get("yaw", 0.0)},
                "place_id": "wall" if obj.get("placement_type") == "wall" else "floor",
            }
            for obj in plan["objects"]
        ],
    }
    room_path = output_dir / "mujoco_room_proxy.json"
    write_json(room_path, room_payload)
    code = f"""
from isaacsim.isaac_mcp.local_mujoco_backend import create_single_room_layout_scene_from_room, simulate_the_scene
import json
create = create_single_room_layout_scene_from_room({str(output_dir)!r}, {str(room_path)!r})
simulate = simulate_the_scene()
print(json.dumps({{"create": create, "simulate": simulate}}))
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        value for value in (str(server_root), env.get("PYTHONPATH")) if value
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
    unstable = simulate.get("unstable_objects", []) if isinstance(simulate, dict) else []
    return {
        "ok": proc.returncode == 0 and isinstance(simulate, dict) and not unstable,
        "returncode": proc.returncode,
        "create": parsed.get("create") if isinstance(parsed, dict) else None,
        "simulate": simulate,
        "unstable_objects": unstable,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }
