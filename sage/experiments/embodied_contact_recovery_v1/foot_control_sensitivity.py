"""Zero-integration motor-to-foot/base response at C3's first bad landing."""
import numpy as np
import h5py
import mujoco
from scipy.optimize import minimize
from .work import E,c,finish

folder=E/'jobs/C_development_03/episode';m=mujoco.MjModel.from_binary_path(str(folder/'MODEL.mjb'));d=mujoco.MjData(m)
foot=m.geom('g8_col').id;body=int(m.geom_bodyid[foot]);ground=m.geom('ground').id
aids=np.array([m.actuator(side+'_'+name+'_joint').id for side in ['left','right'] for name in ['hip_pitch','hip_roll','hip_yaw','knee','ankle_pitch','ankle_roll']])
with h5py.File(folder/'TRACE.h5','r') as f:
 contacts=f['contacts/rows'][:];pairs=contacts[[{int(row[1]),int(row[2])}=={foot,ground} for row in contacts]]
 first=int(pairs[pairs[:,3]<-.01][0,0]);present=set(map(int,pairs[pairs[:,3]<=0,0]));impact=first
 while impact-1 in present:impact-=1
 samples=sorted(set([*range(max(0,impact-80),first+81,8),impact,first]));series=[];response=[]
 for k in samples:
  mujoco.mj_setState(m,d,f['substep/integration_before'][k],mujoco.mjtState.mjSTATE_INTEGRATION);d.ctrl[:]=f['substep/ctrl'][k];mujoco.mj_forward(m,d)
  exact=float(np.max(abs(d.qacc-f['substep/qacc'][k])));assert exact<1e-9
  point=d.geom_xpos[foot].copy();jp=np.zeros((3,m.nv));jr=np.zeros_like(jp);mujoco.mj_jac(m,d,jp,jr,point,body)
  height=float(point[2]-m.geom_size[foot,0]);vz=float(jp[2]@d.qvel);force=0.
  for i,ct in enumerate(d.contact):
   if {ct.geom1,ct.geom2}=={foot,ground}:
    local=np.zeros(6);mujoco.mj_contactForce(m,d,i,local);force+=float(local[0])
  series.append({'row':k,'time':float(d.time),'toe_bottom_z_m':height,'toe_vertical_velocity_mps':vz,'toe_normal_force_N':force,'base_height_m':float(d.qpos[2]),'base_vertical_velocity_mps':float(d.qvel[2]),'ctrl_Nm':d.ctrl[aids].tolist(),'source_qacc_error':exact})
 for k in sorted(set([max(0,impact-16),max(0,impact-4),impact,first])):
  mujoco.mj_setState(m,d,f['substep/integration_before'][k],mujoco.mjtState.mjSTATE_INTEGRATION);baseline=f['substep/ctrl'][k];d.ctrl[:]=baseline;mujoco.mj_forward(m,d)
  jp=np.zeros((3,m.nv));jr=np.zeros_like(jp);mujoco.mj_jac(m,d,jp,jr,d.geom_xpos[foot],body)
  def metric():return np.r_[jp[2]@d.qacc,d.qacc[:3]]
  y0=metric();G=np.zeros((4,len(aids)))
  for j,a in enumerate(aids):
   plus=baseline.copy();minus=baseline.copy();plus[a]+=.5;minus[a]-=.5
   d.ctrl[:]=plus;mujoco.mj_forward(m,d);yp=metric()
   d.ctrl[:]=minus;mujoco.mj_forward(m,d);ym=metric();G[:,j]=yp-ym
  low=np.maximum(-8.,m.actuator_ctrlrange[aids,0]-baseline[aids]);high=np.minimum(8.,m.actuator_ctrlrange[aids,1]-baseline[aids])
  # Ten m/s2 is a diagnostic response request, not an acceptance threshold.
  desired=10.;cons=lambda x:np.r_[G[0]@x-desired,.5-G[1:]@x,.5+G[1:]@x]
  opt=minimize(lambda x:float(x@x),np.zeros(len(aids)),method='SLSQP',bounds=list(zip(low,high)),constraints=[{'type':'ineq','fun':cons}],options={'maxiter':100,'ftol':1e-9})
  d.ctrl[:]=baseline;d.ctrl[aids]+=opt.x;mujoco.mj_forward(m,d);actual=metric()-y0
  response.append({'row':k,'time':float(d.time),'motor_names':[m.actuator(a).name for a in aids],
                   'central_response_matrix':G.tolist(),'finite_query_Nm':.5,'requested_relative_toe_acceleration_increase_mps2':desired,
                   'linearized_candidate_feasible':bool(opt.success and min(cons(opt.x))>=-1e-6),'delta_torque_Nm':opt.x.tolist(),
                   'predicted_toe_and_base_acceleration_changes_mps2':(G@opt.x).tolist(),'actual_same_state_toe_and_base_acceleration_changes_mps2':actual.tolist(),
                   'linearization_error_mps2':(actual-G@opt.x).tolist(),'optimizer_message':str(opt.message)})
report={'physics_steps':0,'policy_calls':0,'source':str(folder),'first_over10mm_row':first,'preceding_contiguous_contact_start_row':impact,
        'toe_geom':m.geom(foot).name,'series':series,'control_response':response,
        'scope':'Repeated mj_forward at identical saved states with bounded motor commands; no state integration. Cartesian acceleration DIFFERENCES are valid; baseline J*qacc omits Jdot*qvel and is not claimed as full point acceleration.',
        'dynamic_admission':False,'production_accepted':False}
c.write(E/'C3_FOOT_CONTROL_SENSITIVITY.json',report);finish(report)
