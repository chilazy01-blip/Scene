"""Shared tight evaluated-geometry bounds for Blender import and render tools."""
from __future__ import annotations
import bpy
import numpy as np
from mathutils import Matrix, Vector
TARGET_TYPES = {"MESH", "CURVE", "SURFACE", "META", "FONT"}

def mesh_bbox_world(
    objects: list[bpy.types.Object], frame: Matrix | None = None,
) -> tuple[Vector, Vector]:
    """Tight bounds of evaluated vertices, optionally in a specified frame.

    Rotating the eight corners of a local AABB overestimates sparse, diagonal
    geometry. Evaluating the actual surface also includes modifiers and curves.
    Mesh arrays are released one object at a time to bound temporary memory.
    """
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    lower, upper = np.full(3, np.inf), np.full(3, -np.inf)
    count = 0
    for obj in objects:
        if obj.type not in TARGET_TYPES:
            continue
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        try:
            if mesh is None or not len(mesh.vertices):
                continue
            points = np.empty(len(mesh.vertices) * 3, dtype=np.float64)
            mesh.vertices.foreach_get("co", points)
            points = points.reshape((-1, 3))
            matrix = evaluated.matrix_world
            if frame is not None:
                matrix = frame @ matrix
            transform = np.asarray(matrix, dtype=np.float64)
            points = points @ transform[:3, :3].T + transform[:3, 3]
            if not np.isfinite(points).all():
                raise ValueError(f"Non-finite evaluated vertices in {obj.name}")
            lower = np.minimum(lower, points.min(axis=0))
            upper = np.maximum(upper, points.max(axis=0))
            count += len(points)
        finally:
            evaluated.to_mesh_clear()
    if not count:
        raise RuntimeError("Imported asset has no renderable geometry.")
    return Vector(lower), Vector(upper)
