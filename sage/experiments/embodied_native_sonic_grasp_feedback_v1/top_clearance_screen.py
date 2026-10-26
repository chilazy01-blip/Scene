"""Whole-finger clearance correction to the kinematically derived top grasp."""
import argparse,itertools,os,resource
from pathlib import Path
import numpy as np
from sage.experiments.embodied_native_sonic_grasp_feedback_v1.posture_screen import IK,hand_ids,RIGHT_CLOSED,contacts,required_preload,contact_pair,load_model,safe_save,read_bound_json,_file_binding

def run(root,source):
    import mujoco
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    old=read_bound_json(root/'TOP_GRASP_SCREEN.json');R=np.array(old['derived_wrist_rotation']);center=np.array(old['tripod_circle_center_wrist_m']);r=read_bound_json(source/'REPORT.json');t=read_bound_json(source/'TRACE.json');m=load_model(r['model']['path']);d=mujoco.MjData(m);q=np.array(t['records'][-1]['substeps'][-1]['full_qpos_after']);ik=IK(mujoco,m);h=hand_ids(m);payload=int(m.joint('payload_free').qposadr[0]);pos=q[payload:payload+3];results=[]
    def inspect(qrobot,thumb,fingers):
        d.qpos[:]=qrobot;d.qpos[h['qpos']]=[RIGHT_CLOSED.get(n,0)*(thumb if 'thumb' in n else fingers) for n in h['names']];mujoco.mj_forward(m,d);cs,info=contacts(mujoco,m,d,True);bad=[]
        for c in d.contact:
            pair=contact_pair(m,c);names=[a['name'] for a in pair]
            if c.dist<0 and any('right_hand_' in a['body'] for a in pair) and any(n.startswith('scene_collision_') for n in names):bad.append(dict(pair=pair,distance_m=float(c.dist)))
        return cs,info,bad
    for shift in [.010,.020]:
        goal=pos-R@center+[shift,0,.015];fit=ik.solve(q,goal,R,max_evaluations=350);pathbad=[];seed=q.copy()
        if fit['position_error_m']>.005 or fit['orientation_error_rad']>.03:results.append(dict(shift_m=shift,ik=fit,eligible=False,reason='unreachable'));continue
        for dz in np.linspace(.14,0,10):
            f=ik.solve(seed,goal+[0,0,dz],R,max_evaluations=180);seed[ik.qids]=f['angles_rad'];cs,info,bad=inspect(seed,0.,0.)
            if f['position_error_m']>.01 or f['orientation_error_rad']>.05 or bad or max([-c['distance_m'] for c in cs],default=0.)>.001:pathbad.append(dict(z_offset=dz,max_open_cup_depth_m=max([-c['distance_m'] for c in cs],default=0.),bad_scene=bad,ik=f))
        for thumb,fingers in itertools.product([.15,.20,.25],[.25,.30,.35]):
            seed=q.copy();seed[ik.qids]=fit['angles_rad'];cs,info,bad=inspect(seed,thumb,fingers);depth=max([-c['distance_m'] for c in cs],default=0.);pre=required_preload(cs,info['weight_n'],np.array(info['com_m']));groups=sorted(set(c['role'] for c in cs));vertical=max([abs(c['normal_vertical']) for c in cs],default=1.)
            results.append(dict(shift_m=shift,thumb_closure=thumb,index_middle_closure=fingers,rotation=R.tolist(),wrist_goal_m=goal.tolist(),offset_world_m=(pos-goal).tolist(),ik=fit,contacts=cs,groups=groups,max_virtual_penetration_m=depth,maximum_vertical_normal=vertical,preload=pre,bad_contacts=bad,open_vertical_path_bad=pathbad,eligible=bool(not bad and not pathbad and depth<=.008 and len(groups)==3 and pre['feasible'])))
        print(dict(shift=shift,candidates=len(results),pathbad=len(pathbad)),flush=True)
    ranked=sorted([a for a in results if a['eligible']],key=lambda a:(a['maximum_vertical_normal']>.5,a['preload']['total_normal_n'],a['max_virtual_penetration_m']))
    safe_save(root/'TOP_CLEARANCE_SCREEN.json',dict(new_physics_steps=0,candidates=results,ranked=ranked,selected=ranked[0] if ranked else None,geometry_cause=_file_binding(root/'TOP_GRASP_SCREEN.json'),source_trace=_file_binding(source/'TRACE.json'),implementation=_file_binding(Path(__file__)),limitation='Fixed derived orientation; two wrist translations and independent thumb versus other fingers to avoid proximal links crossing rim. Private FK/path/load screen only, not an executed grasp.'))
    print(dict(qualified=len(ranked),top=[{k:a[k] for k in ['shift_m','thumb_closure','index_middle_closure','max_virtual_penetration_m','maximum_vertical_normal','preload']} for a in ranked[:3]]),flush=True)
if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--root',type=Path,required=True);a.add_argument('--source',type=Path,required=True);p=a.parse_args();run(p.root,p.source)
