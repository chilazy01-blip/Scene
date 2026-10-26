"""Metric RGB-D geometry; integer pixel indices denote pixel centers."""
import numpy as np


def intrinsics_from_frustum(width, height, near, bottom, top, center=0.0):
    if width <= 0 or height <= 0 or not (near > 0 and top > bottom):
        raise ValueError('invalid perspective frustum')
    scale = height / (top - bottom)
    return np.array([[near * scale, 0., (width - 1) / 2 - center * scale],
                     [0., near * scale, top * scale - .5], [0., 0., 1.]])


def align_depth_to_rgb(depth_m, depth_k, depth_pose, rgb_k, rgb_pose, rgb_shape):
    """Project depth into RGB with nearest-pixel z buffering; holes stay invalid.

    Poses map optical (+x right, +y down, +z forward) coordinates to world.
    Returns metric optical depth, validity mask, and source depth pixel indices.
    No interpolation or completion is applied to unobserved pixels.
    """
    depth = np.asarray(depth_m)
    dk, rk = np.asarray(depth_k), np.asarray(rgb_k)
    dp, rp = np.asarray(depth_pose), np.asarray(rgb_pose)
    if depth.ndim != 2 or dk.shape != (3, 3) or rk.shape != (3, 3):
        raise ValueError('invalid camera shape')
    if np.any(depth < 0) or len(rgb_shape) != 2 or min(rgb_shape) <= 0:
        raise ValueError('invalid metric depth or output shape')
    if dp.shape != (4, 4) or rp.shape != (4, 4):
        raise ValueError('invalid camera pose')
    if not all(np.isfinite(x).all() for x in [depth, dk, rk, dp, rp]):
        raise ValueError('nonfinite camera input')
    if min(dk[0, 0], dk[1, 1], rk[0, 0], rk[1, 1]) <= 0:
        raise ValueError('invalid focal length')
    if any(not np.allclose(p[:3, :3].T @ p[:3, :3], np.eye(3), atol=1e-6)
           or not np.isclose(np.linalg.det(p[:3, :3]), 1., atol=1e-6)
           or not np.allclose(p[3], [0, 0, 0, 1]) for p in [dp, rp]):
        raise ValueError('pose must be rigid optical-to-world transform')
    y, x = np.nonzero(depth > 0)
    z = depth[y, x].astype(np.float64)
    xyz = np.column_stack(((x-dk[0, 2])*z/dk[0, 0], (y-dk[1, 2])*z/dk[1, 1], z))
    points = (xyz @ dp[:3, :3].T + dp[:3, 3] - rp[:3, 3]) @ rp[:3, :3]
    front = points[:, 2] > 0
    points, x, y = points[front], x[front], y[front]
    u = np.rint(rk[0, 0]*points[:, 0]/points[:, 2]+rk[0, 2]).astype(np.int64)
    v = np.rint(rk[1, 1]*points[:, 1]/points[:, 2]+rk[1, 2]).astype(np.int64)
    h, w = rgb_shape
    inside = (u >= 0) & (u < w) & (v >= 0) & (v < h)
    u, v, z, source = u[inside], v[inside], points[inside, 2], y[inside]*depth.shape[1]+x[inside]
    # Stable near-to-far ordering makes equal-depth ties reproducible.
    order = np.argsort(z, kind='stable')
    flat = v[order]*w+u[order]
    _, first = np.unique(flat, return_index=True)
    chosen = order[first]
    out = np.zeros((h, w), np.float32)
    indices = np.full((h, w), -1, np.int64)
    out[v[chosen], u[chosen]] = z[chosen]
    indices[v[chosen], u[chosen]] = source[chosen]
    return out, indices >= 0, indices
