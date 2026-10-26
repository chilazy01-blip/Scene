"""Read saved contact, navigation commands and geometry at a carry failure."""
import sys
from pathlib import Path
import numpy as np,h5py,mujoco
from .work import E,c,finish


def main(config_path):
    cfg=c.read(config_path);folder=Path(cfg['source_episode']);m=mujoco.MjModel.from_binary_path(str(folder/'MODEL.mjb'));d=mujoco.MjData(m)
    with h5py.File(folder/'TRACE.h5','r') as f:
        contacts=f['contacts/rows'][:];worst=contacts[np.argmin(contacts[:,3])];k=int(worst[0]);t=f['substep/time_before'][:]
        rows=f['velocity_transition/physics_row'][:].astype(int);requested=f['velocity_transition/requested'][:];issued=f['velocity_transition/issued'][:]
        samples=[]
        for i in sorted(set([0,min(len(t)-1,800),max(0,k-160),max(0,k-80),max(0,k-16),k])):
            mujoco.mj_setState(m,d,f['substep/integration_before'][i],mujoco.mjtState.mjSTATE_INTEGRATION);mujoco.mj_forward(m,d)
            pi=max(0,int(np.searchsorted(rows,i,side='right')-1));geom=[]
            for g in map(int,worst[1:3]):
                J=np.zeros((3,m.nv));mujoco.mj_jac(m,d,J,None,d.geom_xpos[g],int(m.geom_bodyid[g]))
                geom.append({'name':m.geom(g).name,'body':m.body(int(m.geom_bodyid[g])).name,'xyz':d.geom_xpos[g].tolist(),'velocity':(J@d.qvel).tolist()})
            samples.append({'row':i,'time':float(t[i]),'base_xy':d.qpos[:2].tolist(),'requested':requested[pi].tolist(),'issued':issued[pi].tolist(),'selected_geoms':geom})
        stop=np.flatnonzero(np.linalg.norm(requested,axis=1)<1e-12)
        stop_after_walk=[int(rows[x]) for x in stop if rows[x]>800]
        report={'source_trace_sha256':c.sha(folder/'TRACE.h5'),'physics_steps_read':len(t),'new_physics_steps':0,'peak_row':k,'peak_time':float(t[k]),'peak_penetration_m':float(-worst[3]),'peak_pair':[m.geom(int(g)).name for g in worst[1:3]],'peak_force_N':worst[7:10].tolist(),'samples':samples,'first_zero_request_after_clearance_row':min(stop_after_walk) if stop_after_walk else None,'final_requested':requested[-1].tolist(),'final_issued':issued[-1].tolist(),'production_accepted':False}
    c.write(E/cfg['output'],report);finish(report)


if __name__=='__main__':main(sys.argv[1])
