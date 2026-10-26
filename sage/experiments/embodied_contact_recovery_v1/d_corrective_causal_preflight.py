"""Reproduce the actual source corrective route on a saved D state, no integration."""
import os,sys
from pathlib import Path
from types import SimpleNamespace
import numpy as np,h5py,mujoco
from .work import E,R,c,finish

def main():
 work=Path(os.environ['CONTINUOUS_JOB_DIR']);os.environ.update(NP_ROOT=str(R),NP_JOB=str(work));sys.path.insert(0,str(R/'tools'));sys.path.insert(0,str(R/'branches/A/source'))
 from .target_adapter_r4 import install
 install('A','gain_translation',work/'static_interface')
 from ik import pipeline as p
 from .d_corrective_navigation import install as corrective
 from .safe_approach_r3 import hand_bounds
 folder=E/'jobs/D_development_01/episode';m=mujoco.MjModel.from_binary_path(str(folder/'MODEL.mjb'));d=mujoco.MjData(m)
 with h5py.File(folder/'TRACE.h5','r') as f:
  policy=f['policy/walker_onnx'];rows=policy['physics_row'][:];obs=policy['input'][next(iter(policy['input']))][:].reshape(len(rows),-1);indices=np.flatnonzero((obs[:,-3]<-.05)&(rows>4000));assert len(indices);row=int(rows[indices[0]])
  initial=f['substep/integration_before'][row];mujoco.mj_setState(m,d,initial,mujoco.mjtState.mjSTATE_INTEGRATION);contacts=f['contacts/rows'][:];bad=contacts[contacts[:,3]<-.01][0]
 mujoco.mj_forward(m,d);here=d.qpos[:2].copy();yaw=float(p.ep.base_yaw(d));goal=p.offset_to_base(d.xpos[m.body('red_block').id,:2],yaw,.32,-.24);lo,_=hand_bounds(m,d)
 events=[];dummy=SimpleNamespace(n=row,append=lambda key,value:None);sys.modules['instrument']=SimpleNamespace(ACTIVE_TRACE=dummy)
 def walk(runner,point,**kw):
  events.append({'start':d.qpos[:2].tolist(),'goal':np.asarray(point).tolist(),'yaw':kw.get('goal_yaw')});d.qpos[:2]=point;d.time+=1.;return 0.
 p.ep.walk_to=walk;runner=SimpleNamespace(model=m,data=d,ctrl=SimpleNamespace());original=p.corrective_leg;original(runner,goal,yaw);before=list(events);events.clear()
 mujoco.mj_setState(m,d,initial,mujoco.mjtState.mjSTATE_INTEGRATION);mujoco.mj_forward(m,d);config=c.read(E/'cases/D_development_01.json');corrective(p,config);after_result=p.corrective_leg(runner,goal,yaw);after=list(events)
 assert len(before)==2 and len(after)==1;assert np.linalg.norm(np.asarray(before[0]['goal'])-goal)>.3;assert np.max(abs(np.asarray(after[0]['goal'])-goal))==0.
 report={'passed':True,'physics_steps':0,'policy_calls':0,'source_trace_sha256':c.sha(folder/'TRACE.h5'),'source_row':row,'first_negative_command':obs[indices[0],-3:].tolist(),'start_base_xy':here.tolist(),'measured_target_xy':np.asarray(goal).tolist(),'hand_lower_z_m':float(lo[2]),'original_actual_source_calls':before,'new_actual_installed_calls':after,'new_result':after_result,'first_over_limit':{'row':int(bad[0]),'geoms':[m.geom(int(bad[i])).name for i in [1,2]],'depth_m':float(-bad[3])},'scope':'Source corrective_leg forces retreat before a nearby stance correction; replacement makes a single measured goal call under unchanged clearance/velocity bounds. Fixture state writes are static only. New full-task behavior remains experimental.','production_accepted':False}
 c.write(E/'D_CORRECTIVE_NAVIGATION_CAUSAL_PREFLIGHT.json',report);finish(report)

if __name__=='__main__':main()
