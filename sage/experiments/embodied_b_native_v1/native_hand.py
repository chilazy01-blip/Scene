"""Explicit native MJCF position targets to existing hand motor torques.

This adapter is separate from the qualified zero-only standing adapter.
Validation precedes all writes. No simulator step or state-pose mutation here.
"""
import numpy as np
import mujoco

class NativeHand:
 def __init__(self,model,names,source_rows):
  self.m=model;self.names=list(names);self.rows=[]
  for name in names:
   j=model.joint(name).id;a=model.actuator(name).id;s=next(r for r in source_rows if r['name']==name)
   assert model.jnt_type[j]==mujoco.mjtJoint.mjJNT_HINGE and model.jnt_limited[j]
   assert int(model.actuator_trnid[a,0])==j and model.actuator_gear[a,0]==1
   assert s['group']=='hand' and a==s['actuator'] and j==s['joint']
   lo,hi=map(float,model.jnt_range[j]);assert lo<=0<=hi and lo<hi
   self.rows.append(dict(name=name,joint=j,actuator=a,qpos=int(model.jnt_qposadr[j]),dof=int(model.jnt_dofadr[j]),lower=lo,upper=hi,kp=s['kp'],kd=s['kd'],effort=s['effort'],native_effort=model.jnt_actfrcrange[j].tolist()))
  assert len(self.rows)==14 and len({r['actuator'] for r in self.rows})==14
  for key in ['qpos','dof','actuator','lower','upper','kp','kd','effort']:setattr(self,key,np.array([r[key] for r in self.rows]))
 def validate(self,values,*,names,units,coordinate_frame):
  if list(names)!=self.names:raise ValueError('native_joint_order_required')
  if units!='rad' or coordinate_frame!='native_mjcf_joint':raise ValueError('native_radians_required')
  q=np.asarray(values,dtype=float)
  if q.shape!=(14,) or not np.isfinite(q).all():raise ValueError('invalid_shape_or_nonfinite')
  if np.any(q<self.lower) or np.any(q>self.upper):raise ValueError('outside_native_joint_range')
  return q.copy()
 def command(self,data,values,**metadata):
  target=self.validate(values,**metadata)
  raw=self.kp*(target-data.qpos[self.qpos])-self.kd*data.qvel[self.dof]
  torque=np.clip(raw,-self.effort,self.effort)
  data.ctrl[self.actuator]=torque
  return target,raw,torque
