"""Exact floor conversion cannot become a general furniture bounding-box fallback."""

import numpy as np
import pytest
import trimesh
from .geometry import exact_axis_aligned_box


def test_exact_floor_cuboid_is_same_solid():
    mesh = trimesh.creation.box(extents=[4.8, 4, 0.05])
    mesh.apply_translation([2.4, 2, -0.025])
    r = exact_axis_aligned_box(mesh.vertices, mesh.faces)
    assert r["same_solid_as_source"] and not r["approximation"]
    np.testing.assert_allclose(r["bounds"], [[0, 0, -0.05], [4.8, 4, 0]], atol=1e-12)
    assert r["maximum_corner_error_m"] == 0


def test_missing_box_face_rejected():
    mesh = trimesh.creation.box()
    with pytest.raises(ValueError):
        exact_axis_aligned_box(mesh.vertices, mesh.faces[:-1])


def test_nonbox_vertex_cannot_be_hidden_by_aabb():
    mesh = trimesh.creation.box()
    vertices = mesh.vertices.copy()
    vertices[0] = [0, 0, 0]
    with pytest.raises(ValueError):
        exact_axis_aligned_box(vertices, mesh.faces)


def test_degenerate_floor_rejected():
    mesh = trimesh.creation.box()
    vertices = mesh.vertices.copy()
    vertices[:, 2] = 0
    with pytest.raises(ValueError):
        exact_axis_aligned_box(vertices, mesh.faces)


def test_repeated_triangle_not_accepted_as_closed_box():
    mesh = trimesh.creation.box()
    faces = mesh.faces.copy()
    faces[0] = faces[1]
    with pytest.raises(ValueError):
        exact_axis_aligned_box(mesh.vertices, faces)
