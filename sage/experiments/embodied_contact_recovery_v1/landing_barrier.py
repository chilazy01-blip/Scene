"""Minimal existing-motor correction before a measured swing-foot impact.

Finite acceleration sensitivity includes current support constraints. No model,
state, external wrench, policy parameter or integration timestep is changed.
"""
import numpy as np
import mujoco
from scipy.optimize import minimize

class LandingBarrier:
 def __init__(self,m):
  self.m=m
  self.aids=np.array([m.actuator(s+'_'+j+'_joint').id for s in ['left','right'] for j in ['hip_pitch','hip_roll','hip_yaw','knee','ankle_pitch','ankle_roll']])
  self.feet=[]
  for side in ['left','right']:
   bid=m.body(side+'_ankle_roll_link').id
   gs=[g for g in range(m.ngeom) if m.geom_bodyid[g]==bid and m.geom_type[g]==mujoco.mjtGeom.mjGEOM_SPHERE and m.geom_contype[g]]
   self.feet.append((bid,gs))
  self.calls=0;self.changed=0;self.max_delta=0.;self.infeasible=0
 def apply(self,d):
  m=self.m;self.calls+=1
  # Position and velocity are already forwarded by the retained actuator adapter.
  pending=[]
  for bid,gs in self.feet:
   g=min(gs,key=lambda i:d.geom_xpos[i,2]-m.geom_size[i,0])
   point=d.geom_xpos[g].copy();h=float(point[2]-m.geom_size[g,0])
   if h>=.065:continue
   jp=np.zeros((3,m.nv));jr=np.zeros_like(jp);mujoco.mj_jac(m,d,jp,jr,point,bid)
   v=float(jp[2]@d.qvel)
   if v>=-.10:continue
   jd=np.zeros_like(jp);jrd=np.zeros_like(jp);mujoco.mj_jacDot(m,d,jd,jrd,point,bid)
   desired=float(min(35.,-60*v-900*(h+.002)))
   pending.append((h,v,jp[2],float(jd[2]@d.qvel),desired))
  if not pending:return []
  control=d.ctrl.copy();warm=d.qacc_warmstart.copy()
  mujoco.mj_forward(m,d);baseline=d.qacc.copy()
  constraints=[p for p in pending if p[4]-(p[2]@baseline+p[3])>.1]
  if not constraints:return []
  response=np.zeros((m.nv,len(self.aids)))
  for j,a in enumerate(self.aids):
   d.ctrl[:]=control;d.ctrl[a]+=.1;d.qacc_warmstart[:]=warm
   mujoco.mj_forward(m,d);response[:,j]=(d.qacc-baseline)/.1
  d.ctrl[:]=control;d.qacc_warmstart[:]=warm
  A=np.array([p[2]@response for p in constraints]);b=np.array([p[4]-(p[2]@baseline+p[3]) for p in constraints])
  # Penalize torso acceleration changes as well as motor correction effort.
  weights=np.array([.5,.5,1.,.5,.5,.5])
  H=np.eye(len(self.aids))+(response[:6].T*weights)@response[:6]
  lo=np.maximum(-15.,m.actuator_ctrlrange[self.aids,0]-control[self.aids])
  hi=np.minimum(15.,m.actuator_ctrlrange[self.aids,1]-control[self.aids])
  result=minimize(lambda x:.5*x@H@x,np.zeros(len(self.aids)),jac=lambda x:H@x,
                  method='SLSQP',bounds=list(zip(lo,hi)),constraints=[{'type':'ineq','fun':lambda x:A@x-b,'jac':lambda x:A}],
                  options={'ftol':1e-8,'maxiter':30})
  if result.success and np.min(A@result.x-b)>=-1e-5:
   delta=result.x;self.changed+=1;self.max_delta=max(self.max_delta,float(np.max(abs(delta))))
   d.ctrl[self.aids]=control[self.aids]+delta
  else:
   delta=np.zeros(len(self.aids));self.infeasible+=1
  d.qacc_warmstart[:]=warm;mujoco.mj_forward(m,d)
  return [[p[0],p[1],p[4],float(p[2]@baseline+p[3]),float(p[2]@d.qacc+p[3]),float(result.success),float(np.max(abs(delta)))] for p in constraints]
 def report(self):return {'calls':self.calls,'changed':self.changed,'infeasible':self.infeasible,'max_delta_Nm':self.max_delta}
