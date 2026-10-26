"""Derive wrist pose from native fingertip tripod plane and cup cross-section."""
import argparse,itertools,os,resource
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from sage.experiments.embodied_native_sonic_grasp_feedback_v1.posture_screen import IK,hand_ids,RIGHT_CLOSED,contacts,required_preload,contact_pair,load_model,safe_save,read_bound_json,_file_binding

def run(root,source):
    import mujoco
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    geometry=read_bound_json(root/'NATIVE_HAND_FRAME.json');tip=next(x for x in geometry['rows'] if x['closure']==.3);p=np.array([tip['fingertips_wrist_m'][g] for g in ['thumb','index','middle']]);n=np.array(tip['tip_plane_normal_wrist']);A=np.array([2*(p[1]-p[0]),2*(p[2]-p[0]),n]);b=np.array([p[1]@p[1]-p[0]@p[0],p[2]@p[2]-p[0]@p[0],n@p[0]]);center=np.linalg.solve(A,b);fwd=center-n*(n@center);fwd/=np.linalg.norm(fwd);local=np.column_stack([fwd,np.cross(n,fwd),n]);world=np.diag([1.,-1.,-1.]);R0=world@local.T
    r=read_bound_json(source/'REPORT.json');t=read_bound_json(source/'TRACE.json');m=load_model(r['model']['path']);d=mujoco.MjData(m);q=np.array(t['records'][-1]['substeps'][-1]['full_qpos_after']);ik=IK(mujoco,m);h=hand_ids(m);payload=int(m.joint('payload_free').qposadr[0]);pos=q[payload:payload+3];results=[]
    def inspect(qrobot,closure):
        d.qpos[:]=qrobot;d.qpos[h['qpos']]=[RIGHT_CLOSED.get(name,0)*closure for name in h['names']];mujoco.mj_forward(m,d);cs,info=contacts(mujoco,m,d,True);bad=[]
        for c in d.contact:
            pair=contact_pair(m,c);names=[a['name'] for a in pair]
            if c.dist<0 and any('right_hand_' in a['body'] for a in pair) and any(x.startswith('scene_collision_') for x in names):bad.append(dict(pair=pair,distance_m=float(c.dist)))
        return cs,info,bad
    for yaw,height in itertools.product([-30.,0.,30.],[0.,.015]):
        R=Rotation.from_euler('z',yaw,degrees=True).as_matrix()@R0;goal=pos-R@center+[0,0,height];fit=ik.solve(q,goal,R,max_evaluations=350);base=dict(yaw_deg=yaw,grasp_plane_height_relative_com_m=height,rotation=R.tolist(),offset_local_m=center.tolist(),offset_world_m=(R@center-np.array([0,0,height])).tolist(),wrist_goal_m=goal.tolist(),ik=fit)
        if fit['position_error_m']>.005 or fit['orientation_error_rad']>.03:results.append(dict(**base,eligible=False,reason='unreachable'));continue
        pathbad=[];seed=q.copy()
        for dz in np.linspace(.14,0,10):
            f=ik.solve(seed,goal+[0,0,dz],R,max_evaluations=180);seed[ik.qids]=f['angles_rad'];cs,info,bad=inspect(seed,0.)
            if f['position_error_m']>.01 or f['orientation_error_rad']>.05 or bad or max([-c['distance_m'] for c in cs],default=0)>.001:pathbad.append(dict(z_offset_m=float(dz),ik=f,hand_scene_contacts=bad,max_open_hand_cup_depth_m=max([-c['distance_m'] for c in cs],default=0.)))
        for closure in [.25,.30,.35,.40]:
            sq=q.copy();sq[ik.qids]=fit['angles_rad'];cs,info,bad=inspect(sq,closure);pre=required_preload(cs,info['weight_n'],np.array(info['com_m']));depth=max([-c['distance_m'] for c in cs],default=0.);groups=sorted(set(c['role'] for c in cs));vertical=max([abs(c['normal_vertical']) for c in cs],default=1.)
            results.append(dict(**base,closure=closure,contacts=cs,groups=groups,preload=pre,max_virtual_penetration_m=depth,bad_contacts=bad,open_vertical_path_bad=pathbad,maximum_vertical_normal=vertical,eligible=bool(not bad and not pathbad and depth<=.008 and len(groups)==3 and pre['feasible'])))
        print(dict(yaw=yaw,height=height,checked=len(results),open_path_bad=len(pathbad)),flush=True)
    ranked=sorted([x for x in results if x['eligible']],key=lambda a:(a['maximum_vertical_normal']>.5,a['preload']['total_normal_n'],a['max_virtual_penetration_m']))
    safe_save(root/'TOP_GRASP_SCREEN.json',dict(new_physics_steps=0,tripod_circle_center_wrist_m=center.tolist(),tripod_radius_m=float(np.linalg.norm(p[0]-center)),native_tip_plane_normal=n.tolist(),derived_wrist_rotation=R0.tolist(),candidates=results,ranked=ranked,selected=ranked[0] if ranked else None,source_trace=_file_binding(source/'TRACE.json'),hand_frame=_file_binding(root/'NATIVE_HAND_FRAME.json'),implementation=_file_binding(Path(__file__)),limitation='Private FK and open vertical approach checks, not real grasp proof. Plane alignment is a geometry-derived alternative to the old vertical contact-height distribution; no physical state edit or friction change.'))
    print(dict(qualified=len(ranked),tripod_center=center.tolist(),radius=float(np.linalg.norm(p[0]-center)),top=[{k:a[k] for k in ['yaw_deg','grasp_plane_height_relative_com_m','closure','max_virtual_penetration_m','maximum_vertical_normal','preload']} for a in ranked[:3]]),flush=True)
if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--root',type=Path,required=True);a.add_argument('--source',type=Path,required=True);p=a.parse_args();run(p.root,p.source)
