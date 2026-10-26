"""Fit native mug axis and native hand aperture before full-link grasp screening."""
import argparse,itertools,os,resource
from pathlib import Path
import numpy as np
from scipy.optimize import brentq
from scipy.spatial.transform import Rotation
from sage.experiments.embodied_native_sonic_grasp_feedback_v1.posture_screen import IK,hand_ids,RIGHT_CLOSED,contacts,required_preload,contact_pair,load_model,safe_save,read_bound_json,_file_binding

def run(root,source):
    import mujoco
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    profile=read_bound_json(root/'CUP_AXIS_GEOMETRY.json');mid=profile['wall_sections'][1];r=read_bound_json(source/'REPORT.json');t=read_bound_json(source/'TRACE.json');m=load_model(r['model']['path']);d=mujoco.MjData(m);q=np.array(t['records'][-1]['substeps'][-1]['full_qpos_after']);h=hand_ids(m);w=m.body('right_wrist_yaw_link').id;pid=m.body('payload').id;d.qpos[:]=q;mujoco.mj_forward(m,d);fid=mujoco.mj_name2id(m,mujoco.mjtObj.mjOBJ_FLEX,'payload_surface');vs=np.array(d.flexvert_xpos[m.flex_vertadr[fid]:m.flex_vertadr[fid]+m.flex_vertnum[fid]]);slice=vs[np.abs(vs[:,2]-mid['z_m'])<.003];axis=np.array(mid['center_xy_m']);rad=np.linalg.norm(slice[:,:2]-axis,axis=1);ring=rad[np.abs(rad-mid['radius_m'])<.01];outer=float(np.quantile(ring,.85));radius_geom=[]
    def tripod(closure):
        d.qpos[:]=q;d.qpos[h['qpos']]=[RIGHT_CLOSED.get(n,0)*closure for n in h['names']];mujoco.mj_kinematics(m,d);R=d.xmat[w].reshape(3,3);pts=[]
        for link in ['right_hand_thumb_2_link','right_hand_index_1_link','right_hand_middle_1_link']:
            bid=m.body(link).id;geoms=[i for i in range(m.ngeom) if m.geom_bodyid[i]==bid and (m.geom_contype[i] or m.geom_conaffinity[i])];assert geoms;i=geoms[0];c=R.T@(d.geom_xpos[i]-d.xpos[w]);a=R.T@d.geom_xmat[i].reshape(3,3)[:,2];ends=[c+a*m.geom_size[i,1],c-a*m.geom_size[i,1]];pts.append(max(ends,key=np.linalg.norm));radius_geom.append(float(m.geom_size[i,0]))
        p=np.array(pts);n=np.cross(p[1]-p[0],p[2]-p[0]);n/=np.linalg.norm(n);A=np.array([2*(p[1]-p[0]),2*(p[2]-p[0]),n]);b=np.r_[p[1]@p[1]-p[0]@p[0],p[2]@p[2]-p[0]@p[0],n@p[0]];center=np.linalg.solve(A,b);return center,n,float(np.linalg.norm(p[0]-center))
    tripod(.3);pad=float(np.median(radius_geom));target_radius=outer+pad;bounds=[tripod(c)[2] for c in [0.,.5]];assert min(bounds)<=target_radius<=max(bounds),(outer,pad,bounds)
    nominal=brentq(lambda c:tripod(c)[2]-target_radius,0,.5,xtol=1e-7);center,n,radius=tripod(nominal);fwd=center-n*(n@center);fwd/=np.linalg.norm(fwd);R0=np.diag([1.,-1.,-1.])@np.column_stack([fwd,np.cross(n,fwd),n]).T;pos=q[int(m.joint('payload_free').qposadr[0]):][:3];axisoffset=np.r_[axis-pos[:2],0.];ik=IK(mujoco,m);results=[]
    def inspect(seed,closure):
        d.qpos[:]=seed;d.qpos[h['qpos']]=[RIGHT_CLOSED.get(n,0)*closure for n in h['names']];mujoco.mj_forward(m,d);cs,info=contacts(mujoco,m,d,True);bad=[]
        for c in d.contact:
            pair=contact_pair(m,c);names=[x['name'] for x in pair]
            if c.dist<0 and any('right_hand_' in a['body'] for a in pair) and any(x.startswith('scene_collision_') for x in names):bad.append(dict(pair=pair,distance_m=float(c.dist)))
        return cs,info,bad
    for yaw,height in itertools.product([-20.,0.,20.],[.005,.020]):
        R=Rotation.from_euler('z',yaw,degrees=True).as_matrix()@R0;goal=pos+axisoffset-R@center+[0,0,height];fit=ik.solve(q,goal,R,max_evaluations=350);base=dict(yaw_deg=yaw,height_m=height,rotation=R.tolist(),offset_world_m=(pos-goal).tolist(),wrist_goal_m=goal.tolist(),ik=fit)
        if fit['position_error_m']>.005 or fit['orientation_error_rad']>.03:results.append(dict(**base,eligible=False,reason='unreachable'));continue
        pathbad=[];seed=q.copy()
        for dz in np.linspace(.14,0,10):
            f=ik.solve(seed,goal+[0,0,dz],R,max_evaluations=150);seed[ik.qids]=f['angles_rad'];cs,info,bad=inspect(seed,0.)
            if f['position_error_m']>.01 or f['orientation_error_rad']>.05 or bad or max([-x['distance_m'] for x in cs],default=0.)>.001:pathbad.append(dict(z_offset_m=float(dz),ik=f,max_open_cup_depth_m=max([-x['distance_m'] for x in cs],default=0.),scene_contacts=bad))
        for closure in [max(0,nominal-.02),nominal,min(.5,nominal+.02)]:
            seed=q.copy();seed[ik.qids]=fit['angles_rad'];cs,info,bad=inspect(seed,closure);depth=max([-x['distance_m'] for x in cs],default=0.);pre=required_preload(cs,info['weight_n'],np.array(info['com_m']));groups=sorted(set(x['role'] for x in cs));vertical=max([abs(x['normal_vertical']) for x in cs],default=1.);results.append(dict(**base,closure=closure,contacts=cs,groups=groups,max_virtual_penetration_m=depth,maximum_vertical_normal=vertical,preload=pre,bad_contacts=bad,open_vertical_path_bad=pathbad,eligible=bool(not bad and not pathbad and depth<=.008 and len(groups)==3 and pre['feasible'])))
        print(dict(yaw=yaw,height=height,pathbad=len(pathbad),checked=len(results)),flush=True)
    ranked=sorted([x for x in results if x['eligible']],key=lambda a:(a['maximum_vertical_normal']>.5,a['preload']['total_normal_n'],a['max_virtual_penetration_m']))
    safe_save(root/'AXIS_TOP_GRASP_SCREEN.json',dict(new_physics_steps=0,estimated_cup_outer_radius_m=outer,native_distal_capsule_radius_m=pad,matched_tripod_radius_m=radius,nominal_closure=nominal,axis_offset_world_m=axisoffset.tolist(),candidates=results,ranked=ranked,selected=ranked[0] if ranked else None,cup_profile=_file_binding(root/'CUP_AXIS_GEOMETRY.json'),source_trace=_file_binding(source/'TRACE.json'),implementation=_file_binding(Path(__file__)),limitation='Mesh-axis and aperture-derived finite private reference screen; geometry/LP eligibility is not real contact stability. No physical model/COM/root edits.'))
    print(dict(qualified=len(ranked),outer=outer,pad=pad,nominal=nominal,axisoffset=axisoffset.tolist(),top=[{k:a[k] for k in ['yaw_deg','height_m','closure','max_virtual_penetration_m','maximum_vertical_normal','preload']} for a in ranked[:3]]),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--source',type=Path,required=True);a=p.parse_args();run(a.root,a.source)
