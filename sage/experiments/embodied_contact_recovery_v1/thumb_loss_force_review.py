"""Read exact thumb force decay preceding measured contact loss."""
import sys
from pathlib import Path
import numpy as np,h5py,mujoco
from .work import E,c,finish

def main(config):
 cfg=c.read(config);folder=Path(cfg['source_episode']);m=mujoco.MjModel.from_binary_path(str(folder/'MODEL.mjb'));obj=m.body('red_block').id
 with h5py.File(folder/'TRACE.h5','r') as f:
  n=len(f['substep/qpos']);normal=np.zeros(n);pen=np.zeros(n);rows=f['contacts/rows'][:]
  for x in rows:
   gs=list(map(int,x[1:3]));bs=[int(m.geom_bodyid[g]) for g in gs]
   if obj in bs and any(m.body(b).name.startswith('right_hand_thumb') for b in bs):
    i=int(x[0]);normal[i]+=max(0,float(x[7]));pen[i]=max(pen[i],-float(x[3]))
  indices=list(range(0,n,200))+list(range(max(0,n-200),n,8));samples=[{'row':i,'thumb_normal_N':float(normal[i]),'thumb_penetration_m':float(pen[i]),'thumb_governor':f['finger_governor/control'][i,:3].tolist()} for i in sorted(set(indices))]
 report={'new_physics_steps':0,'normal_min_N':float(normal.min()),'threshold_first_rows':{str(t):int(np.flatnonzero(normal<t)[0]) if np.any(normal<t) else None for t in [.1,.08,.06,.04,.02]},'samples':samples,'production_accepted':False};c.write(E/cfg['output'],report);finish(report)
if __name__=='__main__':main(sys.argv[1])
