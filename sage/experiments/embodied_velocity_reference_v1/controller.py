"""Original Panda gains and actuator limits, with analytical desired velocity."""
import numpy as np
from sage.experiments.embodied_simdata_v0.controller import PandaController


def cubic_reference(start,end,elapsed,duration):
    if not (np.isfinite(duration) and duration>0 and np.isfinite(elapsed) and 0<=elapsed<=duration):
        raise ValueError('invalid_reference_time')
    start=np.asarray(start,dtype=float);end=np.asarray(end,dtype=float)
    if start.shape!=end.shape or not np.isfinite(start).all() or not np.isfinite(end).all():raise ValueError('invalid_reference_endpoints')
    u=elapsed/duration;delta=end-start
    return start+delta*(u*u*(3-2*u)),delta*(6*u*(1-u)/duration)


def cubic_step(start,end,step,count,dt):
    if not (isinstance(step,int) and isinstance(count,int) and count>0 and 0<=step<=count and dt>0):raise ValueError('invalid_reference_step')
    start=np.asarray(start);end=np.asarray(end);u=step/count;delta=end-start
    return start+delta*(u*u*(3-2*u)),delta*(6*u*(1-u)/(count*dt))


class VelocityReferenceController(PandaController):
    def action(self,q,grip,qdot_ref):
        q=np.asarray(q,dtype=float);velocity=np.asarray(qdot_ref,dtype=float)
        if q.shape!=(7,) or velocity.shape!=(7,) or not np.isfinite(q).all() or not np.isfinite(velocity).all():raise ValueError('seven_finite_joint_references_required')
        force=self.kp*(q-self.d.qpos[self.qi])+self.kd*(velocity-self.d.qvel[self.vi])+self.d.qfrc_bias[self.vi]
        self.d.ctrl[self.ai]=np.clip(force,self.m.actuator_ctrlrange[self.ai,0],self.m.actuator_ctrlrange[self.ai,1])
        self.d.ctrl[self.fi]=[grip,-grip]
        return force.copy()
