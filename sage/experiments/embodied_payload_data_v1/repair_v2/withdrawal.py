"""Plan and track an entire-hand retreat from the actual released posture."""
import numpy as np
import mujoco

from ..geometry import Arms
from .progress import CoordinatedPath, ControlRejected, MotionLimits, validate_ik


def plan_withdrawal(query, released_q, open_fingers, check_deadline=lambda:None, *, phase="withdraw"):
    if phase not in {"release","withdraw"}:
        raise ValueError("invalid_retreat_phase")
    m,c=query.m,query.c
    qmap=query.qmap
    arms=Arms(m,c)
    armids=np.array(c["inspection"]["groups"]["left_arm"]+c["inspection"]["groups"]["right_arm"])
    fingers=np.array(c["inspection"]["groups"]["left_hand"]+c["inspection"]["groups"]["right_hand"])
    if np.asarray(open_fingers).shape != fingers.shape or not np.isfinite(open_fingers).all():
        raise ValueError("invalid_open_fingers")
    poses=arms.poses(released_q)
    directions={}
    for side,(pos,_) in poses.items():
        vector=pos-released_q[50:53];vector[2]=0.
        if np.linalg.norm(vector)<1e-6:raise ControlRejected("undefined_retreat_direction")
        directions[side]=vector/np.linalg.norm(vector)
    candidates=[]
    for distance,rise in ((.04,.02),(.06,.02),(.04,.04),(.06,.04)):
        states=[np.array(released_q,copy=True)];errors=[];failure=None
        for fraction in np.linspace(0.,1.,9)[1:]:
            check_deadline()
            targets={s:(pos+directions[s]*distance*fraction+np.array([0.,0.,rise*fraction]),rot)
                     for s,(pos,rot) in poses.items()}
            q,e=arms.solve(states[-1],targets,iterations=32)
            q[qmap[fingers]]=released_q[qmap[fingers]]*(1-fraction)+np.asarray(open_fingers)*fraction
            query.set(q)
            jp=np.zeros((3,m.nv));jr=jp.copy()
            for side,ids in arms.ids.items():
                mujoco.mj_jacBody(m,query.d,jp,jr,arms.body[side])
                e[side]["condition"]=float(np.linalg.cond(np.vstack([jp[:,qmap[ids]-1],jr[:,qmap[ids]-1]*.3])))
            try:validate_ik(e)
            except ControlRejected as exc:failure=str(exc);break
            sweep=query.sweep([states[-1],q],phase,margin=.005)
            if not sweep["passed"]:failure=sweep;break
            states.append(q);errors.append(e)
        if failure is None:
            query.set(states[-1]);final=query.clearance("withdraw",margin=.005)
            residual_contacts=[ct for ct in query.d.contact if {query.roles[ct.geom1],query.roles[ct.geom2]}=={"hand","object"} and ct.dist<=1e-5]
            if not final["passed"] or residual_contacts:
                failure=dict(reason="hands_not_geometrically_released",contacts=len(residual_contacts),clearance=final)
        candidates.append(dict(passed=failure is None,distance=distance,rise=rise,failure=failure,phase=phase,
                               states=[q.tolist() for q in states],ik=errors))
        if failure is None:
            return dict(passed=True,states=candidates[-1]["states"],candidates=candidates,physical_validated=False)
    return dict(passed=False,candidates=candidates,physical_validated=False)


class Withdraw:
    """Drop-in goal interface, with geometry and actual tracking on every command."""
    def __init__(self, query, robot, actual, planned_states, limits=MotionLimits()):
        states=np.asarray(planned_states)
        self.query=query
        self.upper=np.asarray(robot.get_joint_group_indices("upper_body"))
        self.indices=query.qmap[self.upper]
        if states.ndim!=2 or states.shape[1]!=query.m.nq or np.max(np.abs(states[0]-actual.qpos))>1e-8:
            raise ControlRejected("withdrawal_must_start_at_actual_state")
        self.path=CoordinatedPath(states[:,self.indices],limits)

    def target(self, actual):
        query=self.query
        def safe(previous,command,stop):
            configs=[]
            for value in (actual.qpos[self.indices],previous,command,stop):
                q=actual.qpos.copy();q[self.indices]=value;configs.append(q)
            return query.sweep(configs,"withdraw",margin=.003)["passed"]
        command,meta=self.path.step(actual.qpos[self.indices],safe)
        return np.asarray(command),dict(meta,controller="measured_whole_upper_body_progress_v2")
