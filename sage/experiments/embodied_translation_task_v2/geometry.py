"""Fixed two-footprint contact region; no outcome-dependent placement."""
import numpy as np


def translation_region(start_xy, goal_xy, extents_xy, pitch, extra):
    def lattice(value):
        nearest=np.rint(value)
        return np.where(abs(value-nearest)<1e-10,nearest,value)
    low = np.floor(lattice((np.minimum(start_xy, goal_xy)-np.asarray(extents_xy)/2-extra)/pitch))*pitch
    high = np.ceil(lattice((np.maximum(start_xy, goal_xy)+np.asarray(extents_xy)/2+extra)/pitch))*pitch
    return np.array([low, high]), np.rint((high-low)/pitch).astype(int)


def world_ray_height(origin,local_origin_z,support_pose,centers,sizes):
    """Intersect the actual world ray, without expanding shared box faces."""
    pose=np.asarray(support_pose);centers=np.asarray(centers);sizes=np.asarray(sizes)
    world_centers=centers@pose[:3,:3].T+pose[:3,3]
    relative=(np.asarray(origin)-world_centers)@pose[:3,:3]
    direction=np.array([0.,0.,-1.])@pose[:3,:3]
    if not np.allclose(direction,[0.,0.,-1.],atol=1e-12,rtol=0):raise ValueError('support_not_z_aligned')
    inside=np.all(abs(relative[:,:2])<=sizes[:,:2],axis=1)
    distances=relative[:,2]-sizes[:,2]
    valid=inside & (distances>=0.)
    return float(local_origin_z-np.min(distances[valid])) if valid.any() else np.nan
