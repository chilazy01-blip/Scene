"""Preserve signed clearance deficit in the existing collision inequalities.

Clamping a negative margin to zero only prevents additional arm-induced
penetration. It cannot restore margin lost to measured body motion or hand
updates. A negative h here asks for actual separation; if the reference
velocity/acceleration bounds cannot supply it, the QP remains infeasible.
"""
import numpy as np
from mink.limits import Constraint
from sage.experiments.embodied_reference_governor_v2.task_planner import ReferenceBoundedArmPlanner as Base
from sage.experiments.embodied_reference_governor_v1.governor import ReferenceRejected

class RestoringDistanceLimit:
    def __init__(self,base):self.base=base
    def compute_qp_inequalities(self,configuration,dt):
        del dt
        base=self.base;G=[];h=[]
        for a,b in base.geom_id_pairs:
            contact=base._compute_contact_with_minimum_distance(configuration.data,a,b)
            if contact.inactive:continue
            G.append(-base.distance_jacobian(configuration.data,contact))
            h.append(base.gain*(contact.dist-base.minimum_distance_from_collisions))
        return Constraint(G=np.asarray(G),h=np.asarray(h)) if h else Constraint()

class ReferenceBoundedArmPlanner(Base):
    def __init__(self,context,governor):
        super().__init__(context,governor)
        self.collision_limit=RestoringDistanceLimit(self.collision_limit)
        self.planner.support_limit=RestoringDistanceLimit(self.planner.support_limit)
        self.planner.object_limits={key:RestoringDistanceLimit(value) for key,value in self.planner.object_limits.items()}
        self.planner.grasp_limit=RestoringDistanceLimit(self.planner.grasp_limit)
    def snapshot(self):
        return dict(super().snapshot(),collision_law='signed_restoring_v3')
    def restore(self,state):
        if state.get('collision_law')!='signed_restoring_v3':raise ReferenceRejected('collision_law_checkpoint')
        super().restore({k:v for k,v in state.items() if k!='collision_law'})
