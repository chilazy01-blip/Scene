"""Native MuJoCo 3.3.2 bounding-sphere rejection, including mesh geoms.

The same center/radius contract is used by mj_filterSphere in the pinned
engine_collision_driver.c (tag 3.3.2, lines 118-133). Extra floating-point
padding is conservative. Non-positive, invalid or unbounded radii are retained.
https://github.com/google-deepmind/mujoco/blob/3.3.2/src/engine/engine_collision_driver.c
"""
import numpy as np
import mujoco

class ConservativePairs:
    def __init__(self,base):
        if mujoco.__version__!='3.3.2':raise ValueError('native_bounding_contract_version_changed')
        self.base=base;self.pairs=np.asarray(base.geom_id_pairs,dtype=np.int64).reshape(-1,2)
        raw=np.asarray(base.model.geom_rbound,float);self.radius=np.where(np.isfinite(raw)&(raw>0),raw,np.inf)
        self.requests=0;self.native_queries=0
    def select(self,data):
        pairs=self.pairs;self.requests+=len(pairs)
        if not len(pairs):return pairs
        a=data.geom_xpos[pairs[:,0]];b=data.geom_xpos[pairs[:,1]];distance=np.linalg.norm(a-b,axis=1)
        magnitude=np.maximum(1.,np.maximum(np.max(abs(a),axis=1),np.max(abs(b),axis=1)))
        padding=1e-9+64*np.finfo(float).eps*magnitude
        bound=self.radius[pairs[:,0]]+self.radius[pairs[:,1]]+max(0.,self.base.collision_detection_distance)+padding
        keep=~np.isfinite(distance)|~np.isfinite(bound)|(distance<=bound)
        self.native_queries+=int(np.count_nonzero(keep));return pairs[keep]
