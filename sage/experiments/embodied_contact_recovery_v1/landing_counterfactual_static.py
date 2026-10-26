"""Saved-state motor damping direction check without a single integration step."""
import sys
from pathlib import Path
import numpy as np,h5py,mujoco
from .work import E,c,finish
from .landing import damp_landing

def main(config):
 cfg=c.read(config);folder=Path(cfg['source_episode']);m=mujoco.MjModel.from_binary_path(str(folder/'MODEL.mjb'));d=mujoco.MjData(m);samples=[];baseline_error=0.;torque_max=0.
 with h5py.File(folder/'TRACE.h5','r') as f:
  n=len(f['substep/qpos']);contacts=f['contacts/rows'][:];peak=int(contacts[np.argmin(contacts[:,3]),0]);rows=sorted(set([*range(max(0,peak-200),min(n,peak+1),4),peak]))
  for row in rows:
   state=f['substep/integration_before'][row];command=f['substep/ctrl'][row];mujoco.mj_setState(m,d,state,mujoco.mjtState.mjSTATE_INTEGRATION);d.ctrl[:]=command;mujoco.mj_forward(m,d);base_acc=d.qacc.copy();baseline_error=max(baseline_error,float(np.max(abs(d.actuator_force-f['substep/actuator_force'][row]))))
   measures=[]
   for side in ['left','right']:
    body=m.body(side+'_ankle_roll_link').id;geoms=[g for g in range(m.ngeom) if m.geom_bodyid[g]==body and m.geom_type[g]==mujoco.mjtGeom.mjGEOM_SPHERE and (m.geom_contype[g] or m.geom_conaffinity[g])];g=min(geoms,key=lambda x:d.geom_xpos[x,2]-m.geom_size[x,0]);jp=np.zeros((3,m.nv));jr=np.zeros_like(jp);mujoco.mj_jac(m,d,jp,jr,d.geom_xpos[g],body);measures.append((side,float(d.geom_xpos[g,2]-m.geom_size[g,0]),float(jp[2]@d.qvel),jp[2].copy()))
   corrections=damp_landing(m,d,80.);delta=d.ctrl-command;torque_max=max(torque_max,float(np.max(abs(delta))));mujoco.mj_forward(m,d)
   samples.append({'row':row,'actual_command_restored':True,'legs':[{'side':side,'sole_height_m':height,'vertical_velocity_mps':vz,'projected_vertical_acceleration_delta_mps2':float(jz@(d.qacc-base_acc))} for side,height,vz,jz in measures],'max_motor_torque_delta_Nm':float(np.max(abs(delta))),'applied':corrections})
 incoming=[z for x in samples for z in x['legs'] if z['sole_height_m']<.025 and z['vertical_velocity_mps']<-.2];helped=sum(z['projected_vertical_acceleration_delta_mps2']>0 for z in incoming)
 report={'passed':bool(baseline_error<1e-7 and incoming and helped==len(incoming) and torque_max<=8.+1e-12),'source_trace_sha256':c.sha(folder/'TRACE.h5'),'source_peak_row':peak,'samples':samples,'baseline_actual_actuator_force_max_error_Nm':baseline_error,'incoming_foot_samples':len(incoming),'incoming_samples_with_upward_acceleration_change':helped,'max_added_leg_motor_torque_Nm':torque_max,'new_physics_steps':0,'plant_changed':False,'scope':'Instantaneous retained-motor response on saved states; does not establish a stable counterfactual rollout or whole-task numerical convergence.','production_accepted':False};c.write(E/cfg['output'],report);finish(report)
if __name__=='__main__':main(sys.argv[1])
