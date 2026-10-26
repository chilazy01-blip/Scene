"""Three seconds remaining after alignment; original six-second phase cap unchanged."""
import numpy as np
import mujoco
from scipy.spatial.transform import Rotation
from sage.experiments.embodied_collision_expert_v2.planner_interior import ArmPlanner,collision_roles

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
    for tick in range(150):
        fraction = min(1.,tick/100)
        fraction = fraction if dh else fraction*fraction*(3-2*fraction)
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
    complete = len(states) == 150 and len(rows) == 150
    endpoint = max(max(r['errors']) for r in rows[-25:]) if complete else None
    passed = complete and not any(r['bad'] for r in rows) and endpoint <= .006
    return dict(name=name,passed=passed,ticks=len(states),qp_solves=planner.solves,
                endpoint_error_m=endpoint,first_bad=next((r for r in rows if r['bad']),None),
                target_xy=(qpos[:2]+shift).tolist(),height_command=target_height,
                root_height=float(library.shift(qpos,height,target_height,mode)[2])),states,refs,rows
