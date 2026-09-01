from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import trimesh


GLTF_AXIS_SCHEMA = "codex_trellis_gltf_axis_export_v1"


def z_up_to_gltf_y_up_matrix() -> np.ndarray:
    """Return the boundary transform for a Z-up scene written as glTF Y-up.

    Trimesh does not insert this convention change when exporting a scene.  A
    standards-compliant consumer such as Blender therefore rotates an
    unconverted Z-up scene onto its side.  Applying -90 degrees around X before
    export makes Blender's glTF Y-up -> Z-up import transform recover the
    original world coordinates.
    """

    return trimesh.transformations.rotation_matrix(-math.pi / 2.0, [1.0, 0.0, 0.0])


def gltf_y_up_to_z_up_matrix() -> np.ndarray:
    """Return the inverse transform used by Z-up glTF consumers."""

    return trimesh.transformations.rotation_matrix(math.pi / 2.0, [1.0, 0.0, 0.0])


def _bounds_list(scene: trimesh.Scene) -> list[list[float]]:
    bounds = np.asarray(scene.bounds, dtype=np.float64)
    return [[float(value) for value in row] for row in bounds]


def export_z_up_scene_glb(
    scene: trimesh.Scene | trimesh.Trimesh,
    output_path: Path,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Export an internal Z-up scene as a standards-compliant Y-up GLB.

    The input is copied and is never mutated.  The returned report records both
    the internal Z-up bounds and the glTF-native Y-up bounds so axis mistakes
    remain visible in run artifacts.
    """

    if isinstance(scene, trimesh.Trimesh):
        source_scene = trimesh.Scene(scene)
    elif isinstance(scene, trimesh.Scene):
        source_scene = scene
    else:
        raise TypeError(f"scene must be trimesh.Scene or trimesh.Trimesh, got {type(scene)!r}")

    output_path = Path(output_path)
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"Output GLB already exists: {output_path}")

    internal_bounds = _bounds_list(source_scene)
    export_scene = source_scene.copy()
    export_scene.apply_transform(z_up_to_gltf_y_up_matrix())
    gltf_bounds = _bounds_list(export_scene)

    payload = export_scene.export(file_type="glb")
    if not isinstance(payload, (bytes, bytearray)):
        raise RuntimeError(f"trimesh returned unexpected GLB payload type: {type(payload)!r}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(bytes(payload))

    return {
        "schema": GLTF_AXIS_SCHEMA,
        "ok": True,
        "output_glb": str(output_path),
        "output_bytes": output_path.stat().st_size,
        "internal_coordinate_system": "right_handed_z_up",
        "gltf_coordinate_system": "right_handed_y_up",
        "boundary_rotation_degrees_x": -90.0,
        "internal_bounds_z_up_m": internal_bounds,
        "encoded_bounds_y_up_m": gltf_bounds,
    }


def convert_z_up_glb(
    input_path: Path,
    output_path: Path,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Convert a GLB that was incorrectly encoded directly from Z-up data."""

    input_path = Path(input_path)
    output_path = Path(output_path)
    if not input_path.is_file():
        raise FileNotFoundError(f"Missing input GLB: {input_path}")
    if input_path.resolve() == output_path.resolve():
        raise ValueError("Refusing in-place axis conversion; choose a different output path")
    loaded = trimesh.load(input_path, force="scene")
    if not isinstance(loaded, trimesh.Scene) or not loaded.geometry:
        raise ValueError(f"Input GLB contains no scene geometry: {input_path}")
    report = export_z_up_scene_glb(loaded, output_path, overwrite=overwrite)
    report["input_glb"] = str(input_path)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert an incorrectly direct-exported Z-up GLB to glTF Y-up."
    )
    parser.add_argument("--input-glb", required=True, type=Path)
    parser.add_argument("--output-glb", required=True, type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = convert_z_up_glb(args.input_glb, args.output_glb, overwrite=args.force)
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
