"""Recover the existing task waypoint from an observed base error.

Unlike the seven local feasibility probes, the goal is the original waypoint,
not a sampled offset from the measured pose. Error limits retain the complete
previous x/y/yaw development envelope. Every intermediate geometry is checked.
The smooth geometric sweep is not evidence of native walking/velocity tracking.
"""
import numpy as np
import mujoco
from scipy.spatial.transform import Rotation
from sage.experiments.embodied_collision_expert_v2.planner_interior import ArmPlanner, collision_roles

TICKS = 150  # 2.5 s bounded translation/rotation followed by 0.5 s at the goal.


def align(context, qpos, reference, centers, rotations, hand, grasp, target_xy, target_yaw):
    yaw = Rotation.from_quat(qpos[[4,5,6,3]]).as_euler('xyz')[2]
    dyaw = float(np.arctan2(np.sin(target_yaw-yaw),np.cos(target_yaw-yaw)))
    delta = np.asarray(target_xy)-qpos[:2]
    # Original measured domain, not a reduced uncertainty subset.
    if abs(delta[0]) > .04+1e-9 or abs(delta[1]) > .08+1e-9 or abs(dyaw) > .04+1e-9:
        return dict(passed=False,reason='outside_original_base_envelope',ticks=0,qp_solves=0),[],[],[]
    planner = ArmPlanner(context)
    residual = qpos[context.qpos]-reference
    ref = reference.copy()
    states,refs,rows = [],[],[]
    d = mujoco.MjData(context.m)
    for tick in range(TICKS):
        f = min(1.,tick/124)
        f = f*f*(3-2*f)
        q = qpos.copy()
        q[:2] += f*delta
        rot = Rotation.from_euler('z',f*dyaw)*Rotation.from_quat(qpos[[4,5,6,3]])
        q[3:7] = rot.as_quat()[[3,0,1,2]]
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
        excess = max(float(np.max(context.lower-q[context.qpos])),float(np.max(q[context.qpos]-context.upper)))
        if excess > .03:
            bad.append(dict(joint_limit_excess=excess))
        states.append(q.copy());refs.append(ref.copy())
        rows.append(dict(tick=tick,errors=meta['position_errors_m'],bad=bad))
        if bad:
            break
    complete = len(states) == TICKS and len(rows) == TICKS
    endpoint = max(max(r['errors']) for r in rows[-25:]) if complete else None
    return dict(passed=complete and not any(r['bad'] for r in rows) and endpoint <= .006,
                ticks=len(states),qp_solves=planner.solves,endpoint_error_m=endpoint,
                first_bad=next((r for r in rows if r['bad']),None),
                target_xy=list(target_xy),target_yaw=float(target_yaw),
                physical_admitted=False),states,refs,rows
