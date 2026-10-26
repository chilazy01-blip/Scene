"""Use native margin contacts to enforce clearance without raw GJK-distance guesses.

Only the dedicated geometry model is inflated. The physical model is untouched.
Native collision masks, exclusions and parent filtering remain effective.
"""
import copy
import numpy as np
import mujoco
from sage.experiments.embodied_expert_task_v1.quality import names_and_roles


def allowed(roles):
    pair=set(roles)
    return pair in ({'foot','floor'},{'hand','object'}) or not bool(pair&{'robot','hand','foot'})


class ClearanceGuard:
    def __init__(self, model, gap=0.0002, hand_penetration=0.005):
        if gap<=0:raise ValueError('positive_clearance_required')
        self.model=copy.copy(model)
        self.model.geom_margin[:]=np.maximum(self.model.geom_margin,gap+1e-6)
        self.model.pair_margin[:]=np.maximum(self.model.pair_margin,gap+1e-6)
        self.data=mujoco.MjData(self.model)
        self.gap=float(gap);self.hand_penetration=float(hand_penetration)
        box={mujoco.mj_id2name(model,mujoco.mjtObj.mjOBJ_GEOM,g) for g in range(model.ngeom)
             if (mujoco.mj_id2name(model,mujoco.mjtObj.mjOBJ_GEOM,g) or '').startswith('box_')}
        self.names,self.roles=names_and_roles(model,box)

    def check(self,qpos):
        d=self.data;d.qpos[:]=qpos;d.qvel[:]=0
        mujoco.mj_fwdPosition(self.model,d)
        violations=[];minimum=float('inf')
        for c in d.contact[:d.ncon]:
            a,b=int(c.geom1),int(c.geom2);pair={self.roles[a],self.roles[b]};distance=float(c.dist)
            if not allowed(pair):
                minimum=min(minimum,distance)
                limit=self.gap
            elif pair=={'hand','object'}:limit=-self.hand_penetration
            else:continue
            if distance<limit-1e-9:
                violations.append(dict(geoms=[self.names[a],self.names[b]],distance=distance,minimum=limit))
        return dict(passed=not violations,violations=violations,
                    minimum_reported_forbidden_distance=None if not np.isfinite(minimum) else minimum,
                    gap=self.gap,method='native_collision_with_margin_on_separate_model')

    def check_path(self, actual_q, target_by_pin, qmap, indices, samples=9):
        bad=[]
        for fraction in np.linspace(0.,1.,samples):
            q=np.asarray(actual_q).copy();ids=np.asarray(qmap)[indices]
            q[ids]=(1-fraction)*q[ids]+fraction*np.asarray(target_by_pin)[indices]
            result=self.check(q)
            if not result['passed']:bad.append(dict(fraction=float(fraction),violations=result['violations']))
        return dict(passed=not bad,violations=bad,samples=samples,scope='geometry_only_not_dynamic_safety')
