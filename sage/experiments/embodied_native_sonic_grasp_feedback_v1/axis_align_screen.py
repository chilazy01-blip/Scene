"""Derive a grasp from vertical distal-capsule axes, rather than fingertip plane."""
import argparse,os,resource
from pathlib import Path
import numpy as np
from scipy.optimize import brentq
from scipy.spatial.transform import Rotation
from .posture_screen import IK,hand_ids,RIGHT_CLOSED,contacts,required_preload,contact_pair,load_model,safe_save,read_bound_json,_file_binding

def run(root):
    import mujoco
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    source=Path('/data/wsj/main/scene_runs/codex_trellis_v2/embodied_native_sonic_transport_20261022_v1/version_04/full');r=read_bound_json(source/'REPORT.json');t=read_bound_json(source/'TRACE.json');m=load_model(r['model']['path']);d=mujoco.MjData(m);q=np.array(t['records'][-1]['substeps'][-1]['full_qpos_after']);h=hand_ids(m);w=m.body('right_wrist_yaw_link').id;pid=m.body('payload').id;axis=read_bound_json(root/'CUP_AXIS_GEOMETRY.json')['wall_sections'][1];outer=read_bound_json(root/'AXIS_TOP_REFERENCE_CHECK_R2.json')['estimated_cup_outer_radius_m'];distal=[]
    for link in ['right_hand_thumb_2_link','right_hand_index_1_link','right_hand_middle_1_link']:
        bid=m.body(link).id;distal.append(next(i for i in range(m.ngeom) if m.geom_bodyid[i]==bid and (m.geom_contype[i] or m.geom_conaffinity[i])))
    def geometry(c,thumb):
        d.qpos[:]=q;d.qpos[h['qpos']]=[RIGHT_CLOSED.get(n,0)*(thumb if 'thumb' in n else c) for n in h['names']];mujoco.mj_kinematics(m,d);W=d.xmat[w].reshape(3,3);points=np.array([W.T@(d.geom_xpos[g]-d.xpos[w]) for g in distal]);g=distal[1];a=W.T@d.geom_xmat[g].reshape(3,3)[:,2];ends=[points[1]-a*m.geom_size[g,1],points[1]+a*m.geom_size[g,1]]
        if np.linalg.norm(ends[1])<np.linalg.norm(ends[0]):a=-a
        u=(points[1]+points[2])/2-points[0];u-=a*(a@u);u/=np.linalg.norm(u);B=np.column_stack([u,np.cross(a,u),a]);D=np.diag([1.,-1.,-1.]);R=D@B.T;wp=points@R.T;p=wp[:,:2];center=np.linalg.solve(2*(p[1:]-p[0]),np.sum(p[1:]**2,axis=1)-p[0]@p[0]);radius=np.linalg.norm(p[0]-center);return R,wp,center,radius
    ik=IK(mujoco,m);results=[];pad=float(np.median(m.geom_size[distal,0]));target=outer+pad
    for thumb in [.20,.30,.40]:
        grid=np.linspace(.02,.49,25);vals=[]
        for c in grid:
            try:vals.append(geometry(c,thumb)[3]-target)
            except np.linalg.LinAlgError:vals.append(float('nan'))
        roots=[]
        for a,b,fa,fb in zip(grid[:-1],grid[1:],vals[:-1],vals[1:]):
            if np.isfinite([fa,fb]).all() and fa*fb<=0:
                c=brentq(lambda x:geometry(x,thumb)[3]-target,a,b);R,wp,center,radius=geometry(c,thumb)
                if abs(radius-target)<1e-5:roots.append(c)
        if not roots:results.append(dict(thumb_closure=thumb,eligible=False,reason='no matching horizontal capsule circle',radius_residual_bounds=vals));continue
        for c in roots:
            R,wp,center,radius=geometry(c,thumb);yaw=Rotation.from_euler('z',20,degrees=True).as_matrix();R=yaw@R;centerworld=yaw@np.r_[center,0.];wp=wp@yaw.T;goal=np.r_[np.array(axis['center_xy_m'])-centerworld[:2],axis['z_m']-np.mean(wp[1:,2])];fit=ik.solve(q,goal,R,max_evaluations=350);row=dict(index_middle_closure=c,thumb_closure=thumb,rotation=R.tolist(),wrist_goal_m=goal.tolist(),offset_world_m=(np.array(t['records'][-1]['substeps'][-1]['object_m'])-goal).tolist(),ik=fit,capsule_center_heights_m=(goal[2]+wp[:,2]).tolist(),radius_m=radius)
            if fit['position_error_m']>.005 or fit['orientation_error_rad']>.03:results.append(dict(**row,eligible=False,reason='reference IK'));continue
            d.qpos[:]=q;d.qpos[ik.qids]=fit['angles_rad'];d.qpos[h['qpos']]=[RIGHT_CLOSED.get(n,0)*(thumb if 'thumb' in n else c) for n in h['names']];mujoco.mj_forward(m,d);cs,info=contacts(mujoco,m,d,True);bad=[]
            for contact in d.contact:
                pair=contact_pair(m,contact)
                if contact.dist<0 and any('right_hand_' in a['body'] for a in pair) and any(a['name'].startswith('scene_collision_') for a in pair):bad.append(dict(pair=pair,distance_m=float(contact.dist)))
            depth=max([-a['distance_m'] for a in cs],default=0.);groups=sorted(set(x['role'] for x in cs));pre=required_preload(cs,info['weight_n'],np.array(info['com_m']));row.update(contacts=cs,max_virtual_depth_m=depth,groups=groups,bad=bad,preload=pre,eligible=bool(len(groups)==3 and depth<=.001 and not bad and pre['feasible']));results.append(row)
        print(dict(thumb=thumb,roots=roots,checked=len(results)),flush=True)
    safe_save(root/'AXIS_ALIGNED_GRASP_SCREEN.json',dict(new_physics_steps=0,source_report=_file_binding(source/'REPORT.json'),source_trace=_file_binding(source/'TRACE.json'),implementation=_file_binding(Path(__file__)),geometry='Align parallel index/middle distal capsule axes with world down. Match capsule-center projected circle to actual cup body radius at mid-height; finite three thumb postures with1D aperture root solving, then native whole-hand FK/contact/IK/1.5weight wrench check. Reject virtual depth above1mm.',results=results,selected=next((x for x in results if x['eligible']),None),limitation='Private reference planning only, not an executed physical state or proof of stability. Original native model/limits unchanged.'))
    print([{k:x.get(k) for k in ['thumb_closure','index_middle_closure','eligible','reason','max_virtual_depth_m','groups','capsule_center_heights_m','preload']} for x in results],flush=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);run(ap.parse_args().root)
