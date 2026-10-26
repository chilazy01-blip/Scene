"""Measured leg-to-shelf clearance on a separate query state."""
import numpy as np,mujoco
class Clearance:
    def __init__(self,m,c):
        self.m=m;self.d=mujoco.MjData(m);self.names=c['names'];self.segment=np.zeros(6)
        self.legs=[g for g in range(m.ngeom) if (m.geom_contype[g] or m.geom_conaffinity[g]) and any(x in (mujoco.mj_id2name(m,mujoco.mjtObj.mjOBJ_BODY,int(m.geom_bodyid[g])) or '') for x in ['hip','knee','ankle'])]
        self.shelf=[g for g,n in enumerate(c['names']) if n.startswith('shelf_cabinet') and (m.geom_contype[g] or m.geom_conaffinity[g])]
    def sample(self,live):
        self.d.qpos[:]=live.qpos;mujoco.mj_kinematics(self.m,self.d);best=.3;pair=None
        for a in self.legs:
            for b in self.shelf:
                dist=mujoco.mj_geomDistance(self.m,self.d,a,b,.3,self.segment)
                if dist<best:best=float(dist);pair=[self.names[a],self.names[b]]
        return best,pair
