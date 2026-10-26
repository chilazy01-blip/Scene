"""Conservative sphere rejection for native primitive geometry pairs.

Only finite spheres, capsules, ellipsoids, cylinders and boxes are culled.
Unknown types (including planes and meshes) always reach the original native
signed-distance query. The retained pairs keep their original order.
"""
import numpy as np
import mujoco

class ConservativePairs:
    def __init__(self,base):
        self.base=base;self.pairs=np.asarray(base.geom_id_pairs,dtype=np.int64).reshape(-1,2)
        model=base.model;size=np.asarray(model.geom_size);kind=np.asarray(model.geom_type);radius=np.full(model.ngeom,np.inf)
        for geom_type,values in [(mujoco.mjtGeom.mjGEOM_SPHERE,size[:,0]),(mujoco.mjtGeom.mjGEOM_CAPSULE,size[:,0]+size[:,1]),(mujoco.mjtGeom.mjGEOM_ELLIPSOID,np.max(size,axis=1)),(mujoco.mjtGeom.mjGEOM_CYLINDER,np.hypot(size[:,0],size[:,1])),(mujoco.mjtGeom.mjGEOM_BOX,np.linalg.norm(size,axis=1))]:
            use=(kind==geom_type)&np.isfinite(values)&(values>=0);radius[use]=values[use]
        self.radius=radius;self.requests=0;self.native_queries=0
    def select(self,data):
        pairs=self.pairs;self.requests+=len(pairs)
        if not len(pairs):return pairs
        a=data.geom_xpos[pairs[:,0]];b=data.geom_xpos[pairs[:,1]];distance=np.linalg.norm(a-b,axis=1)
        magnitude=np.maximum(1.,np.maximum(np.max(abs(a),axis=1),np.max(abs(b),axis=1)))
        padding=1e-9+64*np.finfo(float).eps*magnitude
        bound=self.radius[pairs[:,0]]+self.radius[pairs[:,1]]+max(0.,self.base.collision_detection_distance)+padding
        keep=~np.isfinite(distance)|~np.isfinite(bound)|(distance<=bound)
        self.native_queries+=int(np.count_nonzero(keep));return pairs[keep]
