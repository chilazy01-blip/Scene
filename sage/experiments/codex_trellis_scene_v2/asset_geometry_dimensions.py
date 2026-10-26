"""Measure canonical source proportions without treating metadata as geometry."""
from __future__ import annotations

import math
import numpy as np

AXES = ('width', 'length', 'height')


def canonical_vertices(gltf_points, entry, extra_yaw=0.):
    points = np.asarray(gltf_points, dtype=float) @ np.array([[1,0,0],[0,0,-1],[0,1,0]],float).T
    axis = int(entry.get('asset_axis_to_z',2)); sign = float(entry.get('asset_axis_to_z_sign',1))
    if axis == 0:
        points = points @ np.array([[0,0,-sign],[0,1,0],[sign,0,0]],float).T
    elif axis == 1:
        points = points @ np.array([[1,0,0],[0,0,-sign],[0,sign,0]],float).T
    angle = math.radians(float(entry.get('asset_local_yaw_offset_degrees',0))+extra_yaw)
    rotation=np.array([[math.cos(angle),-math.sin(angle),0],[math.sin(angle),math.cos(angle),0],[0,0,1]])
    points=points @ rotation.T
    if not np.isfinite(points).all() or len(points)==0:
        raise ValueError('Source vertices must be finite and nonempty')
    return points


def infer_proportion_preserving_dimensions(gltf_points, entry, *, fit_inferred_envelope=False):
    """Propose a physical scale and a horizontal axis correspondence.

    The longest declared dimension supplies one retained physical prior. The
    optional quarter-turn is a proposal requiring source-view review, never
    an automatic certificate of semantic orientation or measured real size.
    """
    declared=np.array([entry['dimensions'][axis] for axis in AXES],float)
    candidates=[]
    for angle in (0.,90.):
        extents=np.ptp(canonical_vertices(gltf_points,entry,angle),axis=0)
        if np.any(extents<=0):raise ValueError('Degenerate canonical source dimensions')
        scales=declared/extents
        candidates.append(dict(extra_yaw=angle,extents=extents,anisotropy=float(scales.max()/scales.min())))
    best=min(candidates,key=lambda c:(c['anisotropy'],c['extra_yaw']))
    primary=int(np.argmin(declared/best['extents'])) if fit_inferred_envelope else int(np.argmax(declared))
    factor=float(declared[primary]/best['extents'][primary])
    return dict(dimensions=dict(zip(AXES,(best['extents']*factor).tolist())),
                asset_local_yaw_offset_degrees=(float(entry.get('asset_local_yaw_offset_degrees',0))+best['extra_yaw'])%360,
                raw_extents=best['extents'].tolist(),uniform_scale=factor,physical_prior_axis=AXES[primary],
                physical_prior_m=float(declared[primary]),previous_declared_dimensions=dict(entry['dimensions']),
                axis_correspondence_candidates=[dict(extra_yaw=c['extra_yaw'],anisotropy=c['anisotropy']) for c in candidates],
                physical_prior_rule='fit_inferred_envelope' if fit_inferred_envelope else 'longest_declared_axis',
                semantic_orientation_review_required=bool(best['extra_yaw']),measured_real_world=False)
