"""Exact primitive recognition, never bounding-box replacement of arbitrary meshes."""

from itertools import product
import numpy as np


def exact_axis_aligned_box(vertices, faces, tolerance=1e-8):
    vertices = np.asarray(vertices, dtype=float)
    faces = np.asarray(faces, dtype=int)
    low, high = vertices.min(axis=0), vertices.max(axis=0)
    extents = high - low
    if np.any(extents <= 0):
        raise ValueError("degenerate box")
    corners = np.array(list(product(*zip(low, high))))
    nearest = np.linalg.norm(vertices[:, None, :] - corners[None, :, :], axis=2).min(
        axis=1
    )
    if float(nearest.max()) > tolerance:
        raise ValueError("mesh vertices not exact box corners")
    if len(np.unique(vertices, axis=0)) != 8:
        raise ValueError("not exactly eight unique corners")
    tri = vertices[faces]
    normals = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    areas = np.linalg.norm(normals, axis=1) / 2
    # Every triangle must lie on exactly one boundary plane; each face area equals its rectangle.
    face_areas = []
    assigned = np.zeros(len(faces), dtype=int)
    for axis in range(3):
        for bound in (low[axis], high[axis]):
            mask = np.all(np.abs(tri[:, :, axis] - bound) <= tolerance, axis=1)
            assigned += mask
            actual = float(areas[mask].sum())
            expected = float(np.prod(np.delete(extents, axis)))
            if abs(actual - expected) > max(tolerance, expected * 1e-10):
                raise ValueError("box face area mismatch")
            face_areas.append(actual)
    if not np.all(assigned == 1):
        raise ValueError("triangle not uniquely on a box face")
    # The source floor is a closed 12-triangle cuboid, not an arbitrary surface with equal total area.
    if len(faces) != 12:
        raise ValueError("expected source cuboid triangulation")
    unique, inverse = np.unique(vertices, axis=0, return_inverse=True)
    edges = np.sort(
        np.concatenate(
            [
                inverse[faces][:, [0, 1]],
                inverse[faces][:, [1, 2]],
                inverse[faces][:, [2, 0]],
            ]
        ),
        axis=1,
    )
    _, counts = np.unique(edges, axis=0, return_counts=True)
    if not np.all(counts == 2):
        raise ValueError("source box not a closed two-manifold")
    return {
        "center": ((low + high) / 2).tolist(),
        "half_size": (extents / 2).tolist(),
        "bounds": [low.tolist(), high.tolist()],
        "surface_area_m2": float(areas.sum()),
        "face_areas_m2": face_areas,
        "maximum_corner_error_m": float(nearest.max()),
        "same_solid_as_source": True,
        "approximation": False,
        "tolerance_m": tolerance,
    }
