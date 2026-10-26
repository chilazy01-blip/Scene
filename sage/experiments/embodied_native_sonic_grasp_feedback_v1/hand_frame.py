"""Diagnose native Dex3 fingertip plane in wrist coordinates, zero physics."""
import argparse,os,resource
from pathlib import Path
import numpy as np
from sage.experiments.embodied_native_walk_motion_v2.engine import hand_ids
from sage.experiments.embodied_carry_v1.grasp import RIGHT_CLOSED
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding

def run(root):
    import mujoco
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    r=read_bound_json(root/'attempt_01/full/REPORT.json');m=load_model(r['model']['path']);d=mujoco.MjData(m);t=read_bound_json(root/'prefix/TRACE.json');d.qpos[:]=t['records'][-1]['substeps'][-1]['full_qpos_after'];h=hand_ids(m);w=m.body('right_wrist_yaw_link').id;rows=[]
    for closure in [0.,.2,.3,.4]:
        d.qpos[h['qpos']]=[RIGHT_CLOSED.get(n,0)*closure for n in h['names']];mujoco.mj_forward(m,d);R=d.xmat[w].reshape(3,3);geoms=[];tips={}
        for i in range(m.ngeom):
            b=m.geom_bodyid[i];name=m.body(int(b)).name
            if not name.startswith('right_hand_') or not (m.geom_contype[i] or m.geom_conaffinity[i]):continue
            center=R.T@(d.geom_xpos[i]-d.xpos[w]);axis=R.T@d.geom_xmat[i].reshape(3,3)[:,2];geoms.append(dict(name=m.geom(i).name,body=name,type=int(m.geom_type[i]),size=m.geom_size[i].tolist(),center_local_m=center.tolist(),axis_local=axis.tolist()))
            for role,link in [('thumb','right_hand_thumb_2_link'),('index','right_hand_index_1_link'),('middle','right_hand_middle_1_link')]:
                if name==link:
                    endpoints=[center+axis*m.geom_size[i,1],center-axis*m.geom_size[i,1]];tips[role]=max(endpoints,key=lambda a:np.linalg.norm(a)).tolist()
        p=np.array([tips[x] for x in ['thumb','index','middle']]);normal=np.cross(p[1]-p[0],p[2]-p[0]);normal/=np.linalg.norm(normal)
        rows.append(dict(closure=closure,collision_geoms=geoms,fingertips_wrist_m=tips,tip_plane_normal_wrist=normal.tolist()));print(dict(closure=closure,tips=tips,normal=normal.tolist()),flush=True)
    safe_save(root/'NATIVE_HAND_FRAME.json',dict(new_physics_steps=0,rows=rows,model=r['model'],implementation=_file_binding(Path(__file__)),limitation='Native capsule endpoint geometry in wrist coordinates; no real grasp or selected orientation claim.'))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);run(p.parse_args().root)
