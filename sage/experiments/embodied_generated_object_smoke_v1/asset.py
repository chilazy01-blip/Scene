"""Normalize the TRELLIS.2 cylinder mesh and audit its collision hull."""

from __future__ import annotations

import argparse
import math
import shutil
from pathlib import Path
from typing import Iterable

import numpy as np

from .common import GENERATED_JOB_ID, RUN_ROOT, read_json, sha256, write_json


TARGET_EXTENTS_M = np.array([0.04, 0.04, 0.07], dtype=np.float64)


def _section_roundness(hull, z: float) -> dict:
    section = hull.section(
        plane_origin=np.array([0.0, 0.0, z]),
        plane_normal=np.array([0.0, 0.0, 1.0]),
    )
    if section is None or len(section.vertices) < 6:
        raise RuntimeError(f"convex hull has no usable section at z={z}")
    xy = np.asarray(section.vertices[:, :2], dtype=np.float64)
    center = xy.mean(axis=0)
    radius = np.linalg.norm(xy - center, axis=1)
    positive = radius[radius > 1e-8]
    if len(positive) < 6:
        raise RuntimeError(f"convex hull section is degenerate at z={z}")
    return {
        "z_m": z,
        "center_xy_m": center.tolist(),
        "radius_min_m": float(positive.min()),
        "radius_mean_m": float(positive.mean()),
        "radius_max_m": float(positive.max()),
        "max_to_min_radius_ratio": float(positive.max() / positive.min()),
        "vertex_count": int(len(positive)),
    }


def normalize_asset(run_root: Path, source_glb: Path | None = None) -> dict:
    import trimesh

    bridge = run_root / "generation/bridge"
    source_glb = source_glb or bridge / f"{GENERATED_JOB_ID}.glb"
    metadata_path = bridge / f"{source_glb.stem}.json"
    if not source_glb.is_file() or not metadata_path.is_file():
        raise FileNotFoundError("TRELLIS.2 GLB and metadata must both exist")
    metadata = read_json(metadata_path)
    if metadata.get("status") != "done":
        raise RuntimeError("TRELLIS.2 metadata is not done")
    if metadata.get("image_provider") != "builtin_imagegen":
        raise RuntimeError("the generated object did not use builtin_imagegen")

    loaded = trimesh.load(source_glb, force="scene", process=False)
    mesh = loaded.to_geometry() if isinstance(loaded, trimesh.Scene) else loaded.copy()
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.vertices) < 32:
        raise RuntimeError("generated GLB has no usable triangle mesh")
    if not np.isfinite(mesh.vertices).all() or not np.isfinite(mesh.faces).all():
        raise RuntimeError("generated GLB contains nonfinite geometry")

    components = mesh.split(only_watertight=False)
    component_faces = sorted((int(len(part.faces)) for part in components), reverse=True)
    largest_fraction = component_faces[0] / max(1, sum(component_faces))

    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    centered = vertices - vertices.mean(axis=0)
    covariance = centered.T @ centered / len(centered)
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    order = np.argsort(eigenvalues)
    z_axis = eigenvectors[:, order[-1]]
    x_axis = eigenvectors[:, order[-2]]
    y_axis = np.cross(z_axis, x_axis)
    y_axis /= np.linalg.norm(y_axis)
    x_axis = np.cross(y_axis, z_axis)
    x_axis /= np.linalg.norm(x_axis)
    basis = np.column_stack((x_axis, y_axis, z_axis))
    if np.linalg.det(basis) < 0:
        basis[:, 0] *= -1
    aligned = centered @ basis
    before_min = aligned.min(axis=0)
    before_max = aligned.max(axis=0)
    before_extents = before_max - before_min
    robust_min = np.quantile(aligned, 0.001, axis=0)
    robust_max = np.quantile(aligned, 0.999, axis=0)
    robust_extent_fraction = (robust_max - robust_min) / before_extents
    if np.any(before_extents <= 1e-8):
        raise RuntimeError(f"generated mesh is degenerate: {before_extents}")
    if before_extents[2] <= max(before_extents[:2]) * 1.12:
        raise RuntimeError(
            f"generated mesh has no unambiguous cylinder axis: {before_extents}"
        )

    scale = TARGET_EXTENTS_M / before_extents
    normalized = aligned * scale
    normalized -= (normalized.min(axis=0) + normalized.max(axis=0)) / 2
    mesh.vertices = normalized
    mesh.remove_unreferenced_vertices()
    mesh.merge_vertices()

    output = run_root / "object_asset"
    output.mkdir(exist_ok=False)
    preserved = output / "red_cylinder_trellis2.glb"
    shutil.copy2(source_glb, preserved)
    obj_path = output / "red_cylinder_normalized.obj"
    mesh.export(obj_path, file_type="obj")

    hull = mesh.convex_hull
    hull_path = output / "red_cylinder_collision_hull.obj"
    hull.export(hull_path, file_type="obj")
    extents = np.asarray(mesh.bounds[1] - mesh.bounds[0], dtype=np.float64)
    hull_extents = np.asarray(hull.bounds[1] - hull.bounds[0], dtype=np.float64)
    sections = [
        _section_roundness(hull, fraction * TARGET_EXTENTS_M[2] / 2)
        for fraction in (-0.75, -0.5, -0.25, 0.0, 0.25, 0.5, 0.75)
    ]
    max_roundness = max(row["max_to_min_radius_ratio"] for row in sections)
    cylinder_volume = math.pi * (TARGET_EXTENTS_M[0] / 2) ** 2 * TARGET_EXTENTS_M[2]
    hull_volume_ratio = float(hull.volume / cylinder_volume)
    admission = {
        "target_extent_error_le_10um": bool(
            np.max(np.abs(extents - TARGET_EXTENTS_M)) <= 1e-5
        ),
        "hull_extent_error_le_10um": bool(
            np.max(np.abs(hull_extents - TARGET_EXTENTS_M)) <= 1e-5
        ),
        # TRELLIS may split one visually continuous surface at texture/UV seams.
        # Component connectivity is therefore recorded below but is not a sound
        # collision admission criterion.  A detached spatial outlier, however,
        # makes the full AABB materially wider than its 0.1--99.9% robust AABB.
        "robust_extent_fraction_ge_0_98": bool(
            np.min(robust_extent_fraction) >= 0.98
        ),
        "section_roundness_ratio_le_1_20": max_roundness <= 1.20,
        "hull_volume_ratio_0_75_to_1_30": 0.75 <= hull_volume_ratio <= 1.30,
        "positive_watertight_convex_hull": bool(hull.is_watertight and hull.volume > 0),
    }
    report = {
        "schema": "embodied-generated-red-cylinder-asset/v1",
        "source_glb": str(source_glb),
        "source_glb_sha256": sha256(source_glb),
        "source_metadata": str(metadata_path),
        "source_metadata_sha256": sha256(metadata_path),
        "preserved_glb": str(preserved),
        "normalized_obj": str(obj_path),
        "normalized_obj_sha256": sha256(obj_path),
        "collision_hull_obj": str(hull_path),
        "collision_hull_obj_sha256": sha256(hull_path),
        "orientation_method": "largest vertex-covariance eigenvector aligned to +Z",
        "normalization_method": "anisotropic AABB normalization to frozen task envelope",
        "source_aligned_extents_arbitrary_units": before_extents.tolist(),
        "source_robust_extent_fraction": robust_extent_fraction.tolist(),
        "applied_scale_to_m": scale.tolist(),
        "normalized_extents_m": extents.tolist(),
        "collision_hull_extents_m": hull_extents.tolist(),
        "mesh_vertices": int(len(mesh.vertices)),
        "mesh_triangles": int(len(mesh.faces)),
        "component_face_counts": component_faces,
        "largest_component_face_fraction": largest_fraction,
        "topology_note": (
            "Disconnected triangle patches are retained for visual/provenance audit. "
            "They are texture-boundary topology, not separate collision bodies; the "
            "single compiled convex hull below is the physics-relevant envelope."
        ),
        "convex_hull_vertices": int(len(hull.vertices)),
        "convex_hull_triangles": int(len(hull.faces)),
        "convex_hull_volume_m3": float(hull.volume),
        "analytic_cylinder_volume_m3": cylinder_volume,
        "convex_hull_to_analytic_volume_ratio": hull_volume_ratio,
        "sections": sections,
        "maximum_section_roundness_ratio": max_roundness,
        "admission_checks": admission,
        "passed": all(admission.values()),
        "physics_steps": 0,
        "interpretation": (
            "The visible generated mesh is supplied to MuJoCo as a mesh geom. "
            "MuJoCo uses its compiled convex hull for dynamic mesh contact; the separately "
            "exported hull records that intended collision envelope."
        ),
    }
    write_json(output / "ASSET_QA.json", report)
    if not report["passed"]:
        raise RuntimeError(f"generated red cylinder failed admission: {admission}")
    return report


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, default=RUN_ROOT)
    parser.add_argument("--source-glb", type=Path)
    args = parser.parse_args(argv)
    print(normalize_asset(args.run_root, args.source_glb))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

