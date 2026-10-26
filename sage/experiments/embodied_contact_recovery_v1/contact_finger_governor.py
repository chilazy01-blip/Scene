"""Encoder-based friction compensation until measured object contact, then bounded preload."""
import numpy as np

class ContactFingerGovernor:
 def __init__(self,model,free_speed=.20,contact_preload=.03):
  self.aids=np.array([a for a in range(model.nu) if model.actuator(a).name.startswith('right_hand')])
  j=model.actuator_trnid[self.aids,0];self.qa=model.jnt_qposadr[j];self.va=model.jnt_dofadr[j]
  self.digits=[model.actuator(a).name.split('_')[2] for a in self.aids]
  self.obj=model.body('red_block').id;self.latched=set();self.free_speed=free_speed;self.cap=contact_preload
  self.kp=model.actuator_gainprm[self.aids,0].copy()
 def apply(self,m,d):
  contacts=set()
  for c in d.contact:
   bodies=[int(m.geom_bodyid[g]) for g in (c.geom1,c.geom2)]
   if self.obj not in bodies:continue
   for b in bodies:
    name=m.body(b).name
    if name.startswith('right_hand') and c.dist<=0:
     contacts.add(name.split('_')[2])
  self.latched.update(contacts)
  records=[]
  for k,(a,qa,va,digit) in enumerate(zip(self.aids,self.qa,self.va,self.digits)):
   q=float(d.qpos[qa]);v=float(d.qvel[va]);raw=float(d.ctrl[a]);sgn=float(np.sign(raw-q))
   if digit in self.latched:
    delta=float(np.clip(raw-q,-self.cap,self.cap));mode=1
   else:
    # Solve the retained position-actuator equation for a bounded free-motion
    # speed, including the measured plant's Coulomb loss and gravity bias.
    resistance=m.dof_frictionloss[va]+(m.dof_damping[va]-m.actuator_biasprm[a,2])*self.free_speed
    delta=(sgn*resistance+d.qfrc_bias[va])/self.kp[k]
    delta=sgn*min(abs(raw-q),max(0.,sgn*delta));mode=0
   target=np.clip(q+delta,*m.actuator_ctrlrange[a]);d.ctrl[a]=target
   records.append([a,mode,q,v,raw,float(target),float(digit in contacts)])
  return np.asarray(records)
