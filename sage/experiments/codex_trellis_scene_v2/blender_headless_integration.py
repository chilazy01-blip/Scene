"""Real Blender headless render used by the P014 integration tier."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

import bpy
from mathutils import Vector


def _args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def _look_at(obj: bpy.types.Object, target: Vector) -> None:
    obj.rotation_euler = (target - obj.location).to_track_quat("-Z", "Y").to_euler()


def _binding(path: Path) -> dict[str, object]:
    return {
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def main() -> None:
    args = _args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.mesh.primitive_cube_add(location=(0.0, 0.0, 0.5), scale=(0.5, 0.5, 0.5))
    cube = bpy.context.object
    cube.name = "P014_REQUIRED_CUBE"
    material = bpy.data.materials.new("P014_BLUE")
    material.diffuse_color = (0.08, 0.28, 0.72, 1.0)
    cube.data.materials.append(material)
    bpy.ops.object.light_add(type="AREA", location=(2.0, -2.0, 3.0))
    bpy.context.object.data.energy = 900
    bpy.context.object.data.shape = "DISK"
    bpy.context.object.data.size = 4.0
    bpy.ops.object.camera_add(location=(2.7, -2.7, 2.2))
    camera = bpy.context.object
    _look_at(camera, Vector((0.0, 0.0, 0.5)))
    bpy.context.scene.camera = camera
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x = 160
    scene.render.resolution_y = 160
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    world = bpy.data.worlds.new("P014_WORLD")
    world.color = (0.04, 0.04, 0.04)
    scene.world = world
    output = args.output_dir / "blender_headless_smoke.png"
    scene.render.filepath = str(output)
    bpy.ops.render.render(write_still=True)
    image = bpy.data.images.load(str(output), check_existing=False)
    width, height = image.size
    pixels = list(image.pixels[:])
    variance = sum((value - 0.5) ** 2 for value in pixels[0::4]) / max(
        1, len(pixels[0::4])
    )
    report = {
        "schema": "scene-v2-blender-headless-integration/v1",
        "ok": bool(width == 160 and height == 160 and variance > 0.01),
        "blender_version": bpy.app.version_string,
        "required_object": cube.name,
        "resolution": [width, height],
        "luminance_proxy_variance": variance,
        "render": {"path": str(output.resolve()), **_binding(output)},
    }
    report["report_hash"] = hashlib.sha256(
        json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    destination = args.output_dir / "blender_headless_integration.json"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=args.output_dir, delete=False
    ) as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(destination)
    if not report["ok"]:
        raise RuntimeError("Blender headless integration quality gate failed")


if __name__ == "__main__":
    main()
