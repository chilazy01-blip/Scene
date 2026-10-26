"""Direct native-mesh contact planning, using a copied distance-query model only."""
import argparse,copy,os,resource,time
from pathlib import Path
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation
from .posture_screen import IK,hand_ids,RIGHT_CLOSED,contacts,required_preload,contact_pair,load_model,safe_save,read_bound_json,_file_binding
from sage.experiments.embodied_carry_v1.grasp import group

DISTAL=('right_hand_thumb_2_link','right_hand_index_1_link','right_hand_middle_1_link')
ROLES=('thumb','index','middle')
class MeshDistanceQuery:
    def __init__(self,mj,physical):
        self.mj=mj;self.model=copy.copy(physical);self.data=mj.MjData(self.model);m=self.model
        self.hand_geoms=[g for g in range(m.ngeom) if (m.body(int(m.geom_bodyid[g])).name.startswith('right_hand_') or m.body(int(m.geom_bodyid[g])).name=='right_wrist_yaw_link') and (m.geom_contype[g] or m.geom_conaffinity[g])]
        self.non_distal=[g for g in self.hand_geoms if m.body(int(m.geom_bodyid[g])).name not in DISTAL]
        for g in self.hand_geoms:m.geom_margin[g]=.015
        self.calls=0
    def inspect(self,q):
        self.calls+=1;d=self.data;m=self.model;d.qpos[:]=q;self.mj.mj_fwdPosition(m,d);minimum={g:.015 for g in self.hand_geoms};roles={g:dict(distance=.015,normal_z=0.) for g in ROLES};scene=.015
        for c in d.contact:
            pair=contact_pair(m,c);names=[a['name'] for a in pair]
            if 'payload_surface' in names:
                side=names.index('payload_surface');other=pair[1-side];gid=int(c.geom[1-side])
                if gid in minimum:minimum[gid]=min(minimum[gid],float(c.dist))
                if other['body'] in DISTAL:
                    role=group(other['body'])
                    if c.dist<roles[role]['distance']:roles[role]=dict(distance=float(c.dist),normal_z=float((1 if side==1 else -1)*c.frame[2]))
            elif any(x['body'].startswith('right_hand_') or x['body']=='right_wrist_yaw_link' for x in pair) and any(x['name'].startswith('scene_collision_') for x in pair):scene=min(scene,float(c.dist))
        return roles,minimum,scene

def right_indices(model,h):return np.array([i for i,n in enumerate(h['names']) if n in RIGHT_CLOSED])
def mesh_points(m,d,g):
    mid=int(m.geom_dataid[g]);v=m.mesh_vert[m.mesh_vertadr[mid]:m.mesh_vertadr[mid]+m.mesh_vertnum[mid]]
    return v@d.geom_xmat[g].reshape(3,3).T+d.geom_xpos[g]

def run(root):
    import mujoco
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    correction=read_bound_json(root/'NATIVE_MESH_GEOMETRY_CORRECTION.json');assert correction['actual_model_unchanged']
    source=Path('/data/wsj/main/scene_runs/codex_trellis_v2/embodied_native_sonic_transport_20261022_v1/version_04/full');r=read_bound_json(source/'REPORT.json');trace=read_bound_json(source/'TRACE.json');m=load_model(r['model']['path']);original_margin=m.geom_margin.copy();d=mujoco.MjData(m);q0=np.array(trace['records'][-1]['substeps'][-1]['full_qpos_after']);h=hand_ids(m);ix=right_indices(m,h);fq=h['qpos'][ix];names=[h['names'][i] for i in ix];closed=np.array([RIGHT_CLOSED[n] for n in names]);w=m.body('right_wrist_yaw_link').id;ik=IK(mujoco,m);query=MeshDistanceQuery(mujoco,m);profile=read_bound_json(root/'CUP_AXIS_GEOMETRY.json');section=profile['wall_sections'][1];dst=[next(g for g in range(m.ngeom) if m.body(int(m.geom_bodyid[g])).name==b and (m.geom_contype[g] or m.geom_conaffinity[g])) for b in DISTAL];assert all(m.geom_type[g]==mujoco.mjtGeom.mjGEOM_MESH for g in dst)
    seeds=[]
    for curled in [False,True]:
        fingers=closed*.3
        if curled:
            for i,n in enumerate(names):
                if 'index_0' in n or 'middle_0' in n:fingers[i]=.20
                if 'index_1' in n or 'middle_1' in n:fingers[i]=.65
        seedq=q0.copy();seedq[fq]=fingers;d.qpos[:]=seedq;mujoco.mj_fwdPosition(m,d);W=d.xmat[w].reshape(3,3);clouds=[(mesh_points(m,d,g)-d.xpos[w])@W for g in dst];centers=np.array([v.mean(axis=0) for v in clouds]);a=np.linalg.svd(clouds[1]-centers[1],full_matrices=False)[2][0]
        if a@centers[1]<0:a=-a
        u=(centers[1]+centers[2])/2-centers[0];u-=a*(a@u);u/=np.linalg.norm(u);R=np.diag([1.,-1.,-1.])@np.column_stack([u,np.cross(a,u),a]).T;R=Rotation.from_euler('z',20,degrees=True).as_matrix()@R;wp=centers@R.T;pp=wp[:,:2];center=np.linalg.solve(2*(pp[1:]-pp[0]),np.sum(pp[1:]**2,axis=1)-pp[0]@pp[0]);goal=np.r_[np.array(section['center_xy_m'])-center,section['z_m']-np.mean(wp[1:,2])];fit=ik.solve(q0,goal,R,max_evaluations=350);seeds.append(dict(curled=curled,goal=goal,rotation=R,ik=fit,fingers=fingers))
    results=[]
    def native_check(q):
        d.qpos[:]=q;mujoco.mj_forward(m,d);cs,info=contacts(mujoco,m,d,True);bad=[];non_distal=[]
        for c in d.contact:
            pair=contact_pair(m,c);ns=[a['name'] for a in pair]
            if 'payload_surface' in ns:
                other=pair[1-ns.index('payload_surface')]
                if (other['body'].startswith('right_hand_') or other['body']=='right_wrist_yaw_link') and other['body'] not in DISTAL and c.dist<0:non_distal.append(dict(body=other['body'],distance_m=float(c.dist)))
            if c.dist<0 and any(a['body'].startswith('right_hand_') or a['body']=='right_wrist_yaw_link' for a in pair) and any(n.startswith('scene_collision_') for n in ns):bad.append(dict(pair=pair,distance_m=float(c.dist)))
        pre=required_preload(cs,info['weight_n'],np.array(info['com_m']));depth=max([-a['distance_m'] for a in cs],default=0.);groups=sorted(set(a['role'] for a in cs));return dict(contacts=cs,groups=groups,max_depth_m=depth,non_distal=non_distal,bad=bad,preload=pre)
    for seed in seeds:
        if seed['ik']['position_error_m']>.01 or seed['ik']['orientation_error_rad']>.05:results.append(dict(curled_seed=seed['curled'],eligible=False,reason='initial reference IK',initial_ik=seed['ik']));continue
        initial=np.r_[seed['ik']['angles_rad'],seed['fingers']];lo=np.r_[np.maximum(ik.lower,initial[:7]-.6),np.minimum(0,closed*.45)];hi=np.r_[np.minimum(ik.upper,initial[:7]+.6),np.maximum(0,closed*.45)];initial=np.clip(initial,lo+1e-7,hi-1e-7);goal=seed['goal'];R=seed['rotation'];last_print=[0]
        def residual(x):
            q=q0.copy();q[ik.qids]=x[:7];q[fq]=x[7:];roles,minimum,scene=query.inspect(q);qd=query.data
            err=[(roles[g]['distance']+.0002)/.001 for g in ROLES];err.extend(max(.002-minimum[g],0)/.001 for g in query.non_distal);err.extend([max(.003-scene,0)/.001]);err.extend(max(abs(roles[g]['normal_z'])-.10,0)/.1 for g in ['index','middle']);err.extend(.2*(qd.xpos[w]-goal)/.03);err.extend(.2*Rotation.from_matrix(R.T@qd.xmat[w].reshape(3,3)).as_rotvec()/.3);err.extend(.015*(x-initial)/np.r_[np.full(7,.6),np.full(7,.3)])
            if query.calls-last_print[0]>=100:last_print[0]=query.calls;print(dict(seed=seed['curled'],queries=query.calls,native_mesh_gap_m={g:roles[g]['distance'] for g in ROLES},largest_residual=float(np.max(np.abs(err)))),flush=True)
            return np.array(err)
        started=time.monotonic();fit=least_squares(residual,initial,bounds=(lo+1e-8,hi-1e-8),max_nfev=200,diff_step=1e-4,ftol=1e-6,xtol=1e-7,gtol=1e-6);q=q0.copy();q[ik.qids]=fit.x[:7];q[fq]=fit.x[7:];native=native_check(q);goal_actual=d.xpos[w].copy();rotation=d.xmat[w].reshape(3,3).copy();maxvert=max([abs(c['normal_vertical']) for c in native['contacts'] if c['role'] in ['index','middle']],default=1.);path=[]
        for alpha in np.linspace(0,1,21):
            z=q.copy();z[fq]=fit.x[7:]*alpha;check=native_check(z)
            if check['max_depth_m']>.001 or check['bad'] or check['non_distal']:path.append(dict(fraction=float(alpha),max_depth_m=check['max_depth_m'],non_distal=check['non_distal'],bad=check['bad']))
        eligible=bool(len(native['groups'])==3 and native['max_depth_m']<=.001 and not native['bad'] and not native['non_distal'] and native['preload']['feasible'] and maxvert<=.3 and not path)
        row=dict(curled_seed=seed['curled'],eligible=eligible,mesh_query_calls=query.calls,optimizer_evaluations=int(fit.nfev),optimizer_cost=float(fit.cost),wall_s=time.monotonic()-started,wrist_goal_m=goal_actual.tolist(),rotation=rotation.tolist(),offset_world_m=(np.array(trace['records'][-1]['substeps'][-1]['object_m'])-goal_actual).tolist(),arm_angles_rad=fit.x[:7].tolist(),finger_joint_names=names,finger_angles_rad=fit.x[7:].tolist(),maximum_index_middle_abs_vertical_normal=maxvert,actual_native_geometry=native,closed_finger_path_bad=path)
        results.append(row);print({k:row[k] for k in ['curled_seed','eligible','optimizer_cost','wall_s','finger_angles_rad','maximum_index_middle_abs_vertical_normal']},native=dict(groups=native['groups'],depth=native['max_depth_m'],non_distal=native['non_distal'],preload=native['preload']),path_bad=len(path),flush=True)
    assert np.array_equal(m.geom_margin,original_margin);selected=next((x for x in results if x['eligible']),None)
    safe_save(root/'NATIVE_MESH_GRASP_PLAN.json',dict(new_physics_steps=0,results=results,selected=selected,geometry_correction=_file_binding(root/'NATIVE_MESH_GEOMETRY_CORRECTION.json'),source_report=_file_binding(source/'REPORT.json'),source_trace=_file_binding(source/'TRACE.json'),implementation=_file_binding(Path(__file__)),private_query_model_only='A copied model expands right-hand contact search margin to15mm for signed geometric distances; it is never integrated or passed to actual control. Final validation uses original unmodified model and actual native meshes/flex.',actual_model_unchanged=True,limitation='Private native-mesh reference planning only. Neither static contact feasibility nor collision-clear finger closure establishes dynamic grasp or transfer. Open approach path still requires separate checking.'))
    print(dict(finished=True,eligible=sum(x['eligible'] for x in results),query_calls=query.calls),flush=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);run(ap.parse_args().root)
