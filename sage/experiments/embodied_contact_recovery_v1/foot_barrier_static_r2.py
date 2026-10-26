"""Scratch validation of an all-sole-point acceleration barrier candidate."""
import numpy as np
import h5py
import mujoco
from scipy.optimize import minimize
from .work import E,c,finish

folder=E/'jobs/C_development_03/episode';m=mujoco.MjModel.from_binary_path(str(folder/'MODEL.mjb'));d=mujoco.MjData(m)
aids=np.array([m.actuator(side+'_'+name+'_joint').id for side in ['left','right'] for name in ['hip_pitch','hip_roll','hip_yaw','knee','ankle_pitch','ankle_roll']])
bodies=[m.body(side+'_ankle_roll_link').id for side in ['left','right']]
geoms=[g for g in range(m.ngeom) if int(m.geom_bodyid[g]) in bodies and m.geom_type[g]==mujoco.mjtGeom.mjGEOM_SPHERE and m.geom_contype[g]]
assert len(geoms)==8
omega=20.;penetration_guard=.006;results=[]
with h5py.File(folder/'TRACE.h5','r') as f:
 for row in [6831,6839,6847,6851,6855,6860]:
  mujoco.mj_setState(m,d,f['substep/integration_before'][row],mujoco.mjtState.mjSTATE_INTEGRATION);baseline=f['substep/ctrl'][row];d.ctrl[:]=baseline;mujoco.mj_forward(m,d)
  jacobians=[];bias=[];height=[];speed=[]
  for g in geoms:
   jp=np.zeros((3,m.nv));jr=np.zeros_like(jp);dj=np.zeros_like(jp);dr=np.zeros_like(jp);body=int(m.geom_bodyid[g]);point=d.geom_xpos[g].copy()
   mujoco.mj_jac(m,d,jp,jr,point,body);mujoco.mj_jacDot(m,d,dj,dr,point,body)
   jacobians.append(jp[2].copy());bias.append(float(dj[2]@d.qvel));height.append(float(point[2]-m.geom_size[g,0]));speed.append(float(jp[2]@d.qvel))
  J=np.asarray(jacobians);bias=np.asarray(bias);height=np.asarray(height);speed=np.asarray(speed)
  metric=lambda:np.r_[J@d.qacc+bias,d.qacc[:6]]
  nominal=metric();G=np.zeros((len(geoms)+6,len(aids)))
  for j,a in enumerate(aids):
   d.ctrl[:]=baseline;d.ctrl[a]+=.5;mujoco.mj_forward(m,d);plus=metric()
   d.ctrl[:]=baseline;d.ctrl[a]-=.5;mujoco.mj_forward(m,d);minus=metric();G[:,j]=plus-minus
  active=height<.08
  initial_barrier=nominal[:8]+2*omega*speed+omega**2*(height+penetration_guard)
  base_limit=np.array([.5,.5,.5,2.,2.,2.])
  def constraints(delta):
   d.ctrl[:]=baseline;d.ctrl[aids]+=delta;mujoco.mj_forward(m,d);value=metric()
   barrier=value[:8]+2*omega*speed+omega**2*(height+penetration_guard);change=value[8:]-nominal[8:]
   return np.r_[barrier[active],base_limit-change,base_limit+change]
  low=np.maximum(-8.,m.actuator_ctrlrange[aids,0]-baseline[aids]);high=np.minimum(8.,m.actuator_ctrlrange[aids,1]-baseline[aids])
  result=minimize(lambda x:float(x@x),np.zeros(len(aids)),method='SLSQP',bounds=list(zip(low,high)),constraints=[{'type':'ineq','fun':constraints}],options={'maxiter':120,'ftol':1e-9,'eps':1e-4})
  feasible=bool(result.success and np.min(constraints(result.x))>=-1e-6)
  d.ctrl[:]=baseline;d.ctrl[aids]+=result.x;mujoco.mj_forward(m,d);actual=metric()
  actual_barrier=actual[:8]+2*omega*speed+omega**2*(height+penetration_guard)
  results.append({'row':row,'time':float(d.time),'foot_geom_names':[m.geom(g).name for g in geoms],
                  'height_m':height.tolist(),'vertical_speed_mps':speed.tolist(),'baseline_point_acceleration_mps2':nominal[:8].tolist(),
                  'baseline_barrier':initial_barrier.tolist(),'delta_torque_Nm':result.x.tolist(),'nonlinear_candidate_feasible':feasible,
                  'predicted_min_barrier':float(min(initial_barrier[active]+G[:8][active]@result.x)),
                  'actual_min_barrier':float(min(actual_barrier[active])),
                  'actual_base_acceleration_change':(actual[8:]-nominal[8:]).tolist(),
                  'actual_all_barriers_satisfied':bool(np.all(actual_barrier[active]>=-1e-6)),
                  'actual_base_change_within_requested_limits':bool(np.all(abs(actual[8:]-nominal[8:])<=base_limit+1e-6)),
                  'optimizer_message':str(result.message)})
report={'physics_steps':0,'policy_calls':0,'source':str(folder),'candidate_design':{'omega_per_s':omega,'penetration_guard_m':penetration_guard,'max_motor_delta_Nm':8.,'base_linear_accel_change_limit_mps2':.5,'base_angular_accel_change_limit_rps2':2.},
        'cases':results,'scope':'Nonlinear same-state contact-solver constrained optimization, with exact mj_jacDot acceleration term and all8sole spheres. Design constants are controller candidates, not weakened quality thresholds or dynamic guarantees.',
        'dynamic_admission':False,'production_accepted':False}
c.write(E/'C3_FOOT_BARRIER_NONLINEAR_STATIC.json',report);finish(report)
