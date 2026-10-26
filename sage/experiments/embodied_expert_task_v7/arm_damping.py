"""Bounded dissipative actuator correction, applied once per5ms physics sample."""
import numpy as np
class ArmDamping:
    def __init__(self,model,mapping,groups,plan):
        self.pin=np.asarray(groups['left_arm']+groups['right_arm']);self.dofs=mapping[self.pin]-1;self.act=[]
        for qid in mapping[self.pin]:
            joint=int(np.flatnonzero(model.jnt_qposadr==qid)[0]);ids=np.flatnonzero(model.actuator_trnid[:,0]==joint);assert len(ids)==1;self.act.append(int(ids[0]))
        self.act=np.asarray(self.act);assert np.all(model.actuator_gear[self.act,0]==1.) and np.all(model.actuator_ctrllimited[self.act]);self.bounds=model.actuator_ctrlrange[self.act].copy();self.limit=plan['maximum_extra_effort_fraction']*np.minimum(-self.bounds[:,0],self.bounds[:,1]);self.gain=float(plan['extra_joint_damping_Nms_per_rad']);assert self.gain>=0 and np.all(self.limit>0)
    def apply(self,native_ctrl,qvel):
        native=np.asarray(native_ctrl);assert np.isfinite(native).all();assert np.all(native[self.act]>=self.bounds[:,0]-1e-9) and np.all(native[self.act]<=self.bounds[:,1]+1e-9)
        v=np.asarray(qvel)[self.dofs];delta=np.clip(-self.gain*v,-self.limit,self.limit);out=native.copy();out[self.act]=np.clip(native[self.act]+delta,self.bounds[:,0],self.bounds[:,1]);delta=out[self.act]-native[self.act];power=float(delta@v);assert power<=1e-9
        return out,dict(added_torque=delta.tolist(),sampled_added_mechanical_power_W=power,max_added_torque_Nm=float(np.max(np.abs(delta))))
