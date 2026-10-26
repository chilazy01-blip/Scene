"""Signed-distance displacement constraints for the pinned MuJoCo 3.3.2.

mj_geomDistance native CCD sorts by geom type and returns witnesses in that
order. Querying in type order avoids assigning a witness to the wrong body.
For penetration, witness displacement must be divided by signed distance.
Source: google-deepmind/mujoco, tag 3.3.2, engine_support.c:1296-1340.
Original Mink and MuJoCo files remain untouched.
"""
import numpy as np
import mujoco
import mink
from mink.limits import Constraint
from mink.limits.collision_avoidance_limit import Contact


class SignedDistanceLimit(mink.CollisionAvoidanceLimit):
    def _compute_contact_with_minimum_distance(self,data,a,b):
        a,b=sorted([a,b],key=lambda g:(int(self.model.geom_type[g]),g))
        witness=np.zeros(6)
        distance=mujoco.mj_geomDistance(self.model,data,a,b,self.collision_detection_distance,witness)
        if distance>=self.collision_detection_distance:distance=self.collision_detection_distance;witness[:]=0
        return Contact(distance,witness,a,b,self.collision_detection_distance)

    def distance_jacobian(self,data,contact):
        delta=contact.fromto[3:]-contact.fromto[:3]
        length=np.linalg.norm(delta)
        if length>1e-10:
            normal=delta/length*(1. if contact.dist>=0 else -1.)
        else:
            # Exact touching is degenerate in witness form; use the native
            # collision normal with the same ordered geometry identities.
            mujoco.mj_collision(self.model,data)
            matches=[c for c in data.contact
                     if {int(c.geom1),int(c.geom2)}=={contact.geom1,contact.geom2}]
            if not matches:raise ValueError(f'degenerate_distance_normal:{contact.geom1},{contact.geom2}:{contact.dist}:{contact.fromto.tolist()}')
            c=min(matches,key=lambda c:c.dist)
            normal=c.frame[:3]*(1. if int(c.geom1)==contact.geom1 else -1.)
        jp1=np.zeros((3,self.model.nv));jp2=np.zeros_like(jp1)
        mujoco.mj_jac(self.model,data,jp1,None,contact.fromto[:3],int(self.model.geom_bodyid[contact.geom1]))
        mujoco.mj_jac(self.model,data,jp2,None,contact.fromto[3:],int(self.model.geom_bodyid[contact.geom2]))
        return normal@(jp2-jp1)

    def compute_qp_inequalities(self,configuration,dt):
        # build_ik's decision variable is delta q; distances and h are in metres.
        del dt
        G=[];h=[]
        for a,b in self.geom_id_pairs:
            contact=self._compute_contact_with_minimum_distance(configuration.data,a,b)
            if contact.inactive:continue
            G.append(-self.distance_jacobian(configuration.data,contact))
            h.append(self.gain*max(0.,contact.dist-self.minimum_distance_from_collisions))
        if not h:return Constraint()
        return Constraint(G=np.asarray(G),h=np.asarray(h))
