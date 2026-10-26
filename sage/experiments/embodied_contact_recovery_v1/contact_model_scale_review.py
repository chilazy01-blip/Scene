"""Read numerical-contact scales from the frozen plant and actual saved impacts."""
import sys
from pathlib import Path
import numpy as np,h5py,mujoco
from .work import E,c,finish

def main(config):
 cfg=c.read(config);results=[]
 for source in cfg['source_episodes']:
  folder=Path(source);m=mujoco.MjModel.from_binary_path(str(folder/'MODEL.mjb'));d=mujoco.MjData(m)
  with h5py.File(folder/'TRACE.h5','r') as f:
   rows=f['contacts/rows'][:];peak=int(rows[np.argmin(rows[:,3]),0]);mujoco.mj_setState(m,d,f['substep/integration_before'][peak],mujoco.mjtState.mjSTATE_INTEGRATION);mujoco.mj_forward(m,d)
  refsafety=not bool(m.opt.disableflags & int(mujoco.mjtDisableBit.mjDSBL_REFSAFE));contacts=[]
  for ct in d.contact:
   if ct.dist>0:continue
   names=[m.geom(int(g)).name for g in [ct.geom1,ct.geom2]];solref=ct.solref.copy();scales=[]
   for factor in [1,2,4]:
    dt=m.opt.timestep/factor;effective=max(float(solref[0]),2*dt) if refsafety and solref[0]>0 else float(solref[0]);scales.append({'timestep':dt,'positive_timeconst_effective_candidate':effective,'reference_safety_clamp_active':bool(refsafety and 0<solref[0]<2*dt)})
   contacts.append({'geoms':names,'distance_m':float(ct.dist),'condim':int(ct.dim),'friction':ct.friction.tolist(),'solref':solref.tolist(),'solimp':ct.solimp.tolist(),'reference_scales':scales})
  results.append({'source':source,'model_sha256':c.sha(folder/'MODEL.mjb'),'peak_row':peak,'option':{'timestep':m.opt.timestep,'integrator':int(m.opt.integrator),'solver':int(m.opt.solver),'cone':int(m.opt.cone),'iterations':m.opt.iterations,'ls_iterations':m.opt.ls_iterations,'noslip_iterations':m.opt.noslip_iterations,'tolerance':m.opt.tolerance,'impratio':m.opt.impratio,'disableflags':int(m.opt.disableflags),'reference_safety_enabled':refsafety},'contacts':contacts})
 report={'complete':True,'new_physics_steps':0,'sources':results,'plant_parameters_changed':False,'scope':'Read frozen solver/contact parameters at actual worst states; effective positive-timeconst expression is an interpretation to verify against primary MuJoCo documentation, not a new simulation result.','production_accepted':False};c.write(E/cfg['output'],report);finish(report)
if __name__=='__main__':main(sys.argv[1])
