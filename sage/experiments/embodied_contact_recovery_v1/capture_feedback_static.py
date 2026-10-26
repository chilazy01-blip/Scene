"""Check measured missing-digit retargeting on actual settled D2 acquisition states."""
import os,sys
from pathlib import Path
from types import SimpleNamespace
import numpy as np,h5py,mujoco
from .work import E,R,c,finish
from .capture_geometry_feedback import retarget
from .planned_tripod_r2 import GROUPS,PlannedFingerServo,contact_geometry

def main():
 folder=E/'jobs/D_development_02/episode';m=mujoco.MjModel.from_binary_path(str(folder/'MODEL.mjb'));d=mujoco.MjData(m);obj=m.body('red_block').id;plan=c.read(folder.parent/'D_MEASURED_TRIPOD_PLAN.json');original=np.array(plan['finger_target_rad']);servo=PlannedFingerServo(m)
 records=[]
 with h5py.File(folder/'TRACE.h5','r') as f:
  observations=f['tripod/observation'][:];rows=observations[observations[:,1]==1,0].astype(int);rows=np.unique(np.r_[rows[::max(1,len(rows)//5)],len(f['substep/qpos'])-1])
  for row in rows:
   mujoco.mj_setState(m,d,f['substep/integration_after'][row],mujoco.mjtState.mjSTATE_INTEGRATION);mujoco.mj_forward(m,d);before=d.qpos.copy();runner=SimpleNamespace(model=m,data=d,cyl_bid=obj);desired,result=retarget(runner,original);assert np.array_equal(before,d.qpos)
   keep=[i for digit,ids in GROUPS.items() if digit not in result['missing_digits'] for i in ids];assert np.array_equal(desired[keep],original[keep])
   records.append({'row':int(row),'time_s':float(d.time),'before':contact_geometry(m,d,obj),'plan':result,'target_change_rad':(desired-original).tolist(),'retained_contacted_digit_targets_exact':True})
 assert records and all(r['plan']['valid'] for r in records)
 report={'passed':True,'physics_steps':0,'policy_calls':0,'source_trace_sha256':c.sha(folder/'TRACE.h5'),'cases':records,'capture_deadline_seconds_unchanged':6.5,'stable_three_digit_seconds_unchanged':.2,'maximum_capture_replans':2,'preload_rad_unchanged':.03,'plant_unchanged':True,'dynamic_qualification':False,'production_accepted':False}
 c.write(E/'D_CAPTURE_GEOMETRY_FEEDBACK_STATIC.json',report);finish(report)

if __name__=='__main__':main()
