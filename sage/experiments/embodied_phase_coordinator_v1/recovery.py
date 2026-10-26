"""Fixed bounded recovery previews using empirical coupled FB1 body poses.

These are geometry hypotheses, not simulated controller rollouts. Each candidate
keeps the actual object fixed and includes the entire base/body transition. The
runtime coordinator only emits commands after a caller checks saved geometry.
"""
import numpy as np
import mujoco
from scipy.spatial.transform import Rotation
from sage.experiments.embodied_collision_expert_v2.planner_interior import ArmPlanner, collision_roles

CANDIDATES = (('hold',0.,0.,0.), ('forward',.04,0.,0.), ('backward',-.04,0.,0.),
              ('left',0.,.04,0.), ('right',0.,-.04,0.), ('lower',0.,0.,-.04),
              ('higher',0.,0.,.04))
TICKS = 125


class BodyLibrary:
    def __init__(self, trace, heights, lower_qpos):
        self.trace = trace
        self.lower_qpos = lower_qpos
        self.ids = {}
        for height in np.linspace(.64,.74,101):
            ids = np.where(abs(heights-height) <= .0051)[0]
            self.ids[round(height,3)] = dict(
                low=int(ids[np.argmin(trace[ids,2])]), high=int(ids[np.argmax(trace[ids,2])]),
                nominal=int(ids[np.argmin(abs(trace[ids,2]-np.median(trace[ids,2])))]))

    def at(self, height, mode='nominal'):
        return self.trace[self.ids[round(float(height),3)][mode]]

    def shift(self, q, old_height, new_height, mode='nominal'):
        before,after = self.at(old_height,mode),self.at(new_height,mode)
        result = q.copy()
        result[2] += after[2]-before[2]
        result[self.lower_qpos] += after[self.lower_qpos]-before[self.lower_qpos]
        current = Rotation.from_quat(q[[4,5,6,3]])
        a,b = [Rotation.from_quat(x[[4,5,6,3]]) for x in [before,after]]
        result[3:7] = (current*a.inv()*b).as_quat()[[3,0,1,2]]
        return result


def preview(context, library, qpos, reference, centers, rotations, hand,
            grasp, height, heading, candidate, mode='nominal'):
    name,dx,dy,dh = candidate
    target_height = height+dh
    if not .64-1e-12 <= target_height <= .74+1e-12:
        return dict(name=name,passed=False,reason='height_domain',ticks=0), [], [], []
    target_height = float(np.clip(target_height,.64,.74))
    turn = Rotation.from_euler('z',heading).as_matrix()[:2,:2]
    shift = turn@np.array([dx,dy])
    planner = ArmPlanner(context)
    residual = qpos[context.qpos]-reference
    ref = reference.copy()
    states,refs,rows = [],[],[]
    d = mujoco.MjData(context.m)
    for tick in range(TICKS):
        fraction = min(1.,tick/99)
        fraction = fraction*fraction*(3-2*fraction)
        command_height = height+fraction*(target_height-height)
        q = library.shift(qpos,height,command_height,mode)
        q[:2] += shift*fraction
        q[context.qpos[planner.arm]] = ref[planner.arm]+residual[planner.arm]
        q[context.qpos[context.hand]] = ref[context.hand]+residual[context.hand]
        try:
            ref,meta = planner.step(q,ref,centers,rotations,hand,grasp)
        except (ValueError,RuntimeError) as exc:
            rows.append(dict(tick=tick,reason=str(exc),bad=True))
            break
        q[context.qpos[planner.arm]] = ref[planner.arm]+residual[planner.arm]
        q[context.qpos[context.hand]] = ref[context.hand]+residual[context.hand]
        d.qpos[:] = q
        bad,_ = collision_roles(context,d,grasp)
        excess = max(float(np.max(context.lower-q[context.qpos])),
                     float(np.max(q[context.qpos]-context.upper)))
        if excess > .03:
            bad.append(dict(joint_limit_excess=excess))
        states.append(q.copy());refs.append(ref.copy())
        rows.append(dict(tick=tick,errors=meta['position_errors_m'],bad=bad,
                         height_command=command_height))
        if bad:
            break
    complete = len(states) == TICKS and len(rows) == TICKS
    endpoint = max(max(r['errors']) for r in rows[-25:]) if complete else None
    passed = complete and not any(r['bad'] for r in rows) and endpoint <= .006
    return dict(name=name,passed=passed,ticks=len(states),qp_solves=planner.solves,
                endpoint_error_m=endpoint,first_bad=next((r for r in rows if r['bad']),None),
                target_xy=(qpos[:2]+shift).tolist(),height_command=target_height,
                root_height=float(library.shift(qpos,height,target_height,mode)[2])),states,refs,rows
