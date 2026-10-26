"""Conservative query radii for a declared discrete rigid-geometry forecast.

These radii cover all supplied configurations. They do not certify continuous
physics between samples or compensate for an inaccurate stopping forecast.
"""
import numpy as np


def surface_displacement(centers,rotations,radii):
    centers=np.asarray(centers);rotations=np.asarray(rotations);radii=np.asarray(radii)
    if centers.ndim!=3 or centers.shape[2]!=3 or rotations.shape!=centers.shape[:2]+(3,3) or radii.shape!=(centers.shape[1],):raise ValueError('forecast_shapes')
    if not all(np.isfinite(x).all() for x in [centers,rotations,radii]) or np.any(radii<0):raise ValueError('forecast_finite_radii')
    trace=np.einsum('gij,tgij->tg',rotations[0],rotations)
    cosine=np.clip((trace-1)/2,-1,1)
    rotation_bound=np.sqrt(np.maximum(0.,2-2*cosine))*radii
    translation=np.linalg.norm(centers-centers[0],axis=2)
    return np.max(translation+rotation_bound,axis=0)


def pair_horizons(pairs,minimum_distance,original_detection,surface_motion):
    pairs=np.asarray(pairs,dtype=int)
    return np.maximum(original_detection,minimum_distance+surface_motion[pairs[:,0]]+surface_motion[pairs[:,1]]+1e-8)
