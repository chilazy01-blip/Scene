"""Declared finite private FK screen: 18 poses, 54 shapes, zero mj_step."""
import argparse,itertools,os,resource
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from .quality import contacts,required_preload
from sage.experiments.embodied_native_sonic_grasp_v1.geometry_probe import IK,hand_ids,RIGHT_CLOSED,contact_pair,load_model,read_bound_json,safe_save,_file_binding

def run(root,parent):
    import mujoco
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    p=read_bound_json(parent/'PROTOCOL.json');scene=read_bound_json(Path(p['scene']['path']));t=read_bound_json(parent/'version_04/full/TRACE.json')
    model=load_model(scene['model']['path']);model.opt.timestep=.005;d=mujoco.MjData(model);ik=IK(mujoco,model);h=hand_ids(model)
    q=np.array(t['records'][-1]['substeps'][-1]['full_qpos_after']);d.qpos[:]=q;mujoco.mj_forward(model,d);payload=int(model.joint('payload_free').qposadr[0]);pos=q[payload:payload+3].copy();results=[]
    for roll,y,z in itertools.product([-20.,0.,20.],[.05,.07],[-.01,0.,.01]):
        R=Rotation.from_euler('x',roll,degrees=True).as_matrix();offset=np.array([.15,y,z]);fit=ik.solve(q,pos-R@offset,R,max_evaluations=120)
        for closure in [.25,.35,.45]:
            row=dict(roll_deg=roll,rotation=R.tolist(),offset_local_m=offset.tolist(),offset_world_m=(R@offset).tolist(),closure=closure,ik=fit)
            if fit['position_error_m']>.005 or fit['orientation_error_rad']>.03:row.update(eligible=False,reason='unreachable');results.append(row);continue
            d.qpos[:]=q;d.qpos[ik.qids]=fit['angles_rad'];d.qpos[h['qpos']]=[RIGHT_CLOSED.get(n,0)*closure for n in h['names']];mujoco.mj_forward(model,d)
            rows,info=contacts(mujoco,model,d,True);bad=[]
            for c in d.contact:
                pair=contact_pair(model,c);names=[x['name'] for x in pair];bodies=[x['body'] for x in pair]
                if c.dist<0 and any('right_hand_' in b for b in bodies) and any(n.startswith('scene_collision_') for n in names):bad.append(dict(pair=pair,distance_m=float(c.dist)))
            depth=max([-c['distance_m'] for c in rows],default=0.);preload=required_preload(rows,info['weight_n'],np.array(info['com_m']))
            row.update(contacts=rows,groups=sorted(set(c['role'] for c in rows)),max_virtual_penetration_m=depth,bad_contacts=bad,preload=preload,eligible=bool(not bad and depth<=.01 and preload['feasible']))
            row['downward_index_normal']=max([-c['normal_vertical'] for c in rows if c['role']=='index'],default=0.)
            results.append(row)
        print(dict(checked=len(results),pose=[roll,y,z]),flush=True)
    ranked=sorted([r for r in results if r['eligible']],key=lambda r:(r['downward_index_normal']>.3,r['preload']['total_normal_n'],r['max_virtual_penetration_m']))
    safe_save(root/'GEOMETRY_SCREEN.json',dict(new_physics_steps=0,pose_count=18,shape_count=len(results),candidates=results,selected=ranked[0] if ranked else None,ranked=ranked,source_trace=_file_binding(parent/'version_04/full/TRACE.json'),limitation='private FK geometry and optimistic 1.5-weight wrench feasibility only; not actual grasp or load proof'))
    print(dict(qualified=len(ranked),top=[{k:r[k] for k in ['roll_deg','offset_local_m','closure','preload','downward_index_normal']} for r in ranked[:5]]),flush=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);ap.add_argument('--parent',type=Path,required=True);a=ap.parse_args();run(a.root,a.parent)
