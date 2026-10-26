"""Private full-body reference IK to reach lower cup-body grasps; zero integration."""
import argparse,itertools,os,resource
from pathlib import Path
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation
from sage.experiments.embodied_native_object_transport_v1.kinematics_r3 import IK
from sage.experiments.embodied_native_walk_motion_v2.engine import hand_ids
from sage.experiments.embodied_carry_v1.grasp import RIGHT_CLOSED
from sage.experiments.embodied_native_sonic_loaded_grasp_v1.quality import contacts,required_preload
from sage.experiments.embodied_native_object_transport_v1.metrics import contact_pair
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding

def run(root,source):
    import mujoco
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    r=read_bound_json(source/'REPORT.json');t=read_bound_json(source/'TRACE.json');m=load_model(r['model']['path']);d=mujoco.MjData(m);q=np.array(t['records'][-1]['substeps'][-1]['full_qpos_after']);d.qpos[:]=q;mujoco.mj_kinematics(m,d);feet=[m.body(side+'_ankle_roll_link').id for side in ['left','right']];goals=[(d.xpos[b].copy(),d.xmat[b].reshape(3,3).copy()) for b in feet]
    legnames=[side+'_'+joint+'_joint' for side in ['left','right'] for joint in ['hip_pitch','hip_roll','hip_yaw','knee','ankle_pitch','ankle_roll']];lq=np.array([m.joint(n).qposadr[0] for n in legnames]);bounds=np.array([m.joint(n).range for n in legnames]).T;virtual=q.copy();shift=np.array([0,-.025,-.03]);virtual[:3]+=shift
    def residual(x):
        d.qpos[:]=virtual;d.qpos[lq]=x;mujoco.mj_kinematics(m,d);return np.concatenate([np.r_[10*(d.xpos[b]-p),Rotation.from_matrix(R.T@d.xmat[b].reshape(3,3)).as_rotvec()] for b,(p,R) in zip(feet,goals)])
    fit=least_squares(residual,q[lq],bounds=(bounds[0]+1e-5,bounds[1]-1e-5),max_nfev=150,ftol=1e-10,xtol=1e-10,gtol=1e-10);virtual[lq]=fit.x;legerr=residual(fit.x);assert np.max(np.abs(legerr))<.002
    ik=IK(mujoco,m);h=hand_ids(m);payload=int(m.joint('payload_free').qposadr[0]);pos=virtual[payload:payload+3];results=[]
    for x,z,roll in itertools.product([.15,.17],[-.015,0.],[-20.,0.,20.]):
        R=Rotation.from_euler('x',roll,degrees=True).as_matrix();offset=np.array([x,.05,z]);f=ik.solve(virtual,pos-R@offset,R,max_evaluations=250)
        for closure in [.2,.3,.4]:
            row=dict(offset_local_m=offset.tolist(),offset_world_m=(R@offset).tolist(),rotation=R.tolist(),roll_deg=roll,closure=closure,ik=f)
            if f['position_error_m']>.005 or f['orientation_error_rad']>.03:row.update(eligible=False,reason='arm unreachable even after posture reference');results.append(row);continue
            d.qpos[:]=virtual;d.qpos[ik.qids]=f['angles_rad'];d.qpos[h['qpos']]=[RIGHT_CLOSED.get(n,0)*closure for n in h['names']];mujoco.mj_forward(m,d);cs,info=contacts(mujoco,m,d,True);bad=[]
            for c in d.contact:
                pair=contact_pair(m,c);names=[a['name'] for a in pair]
                if c.dist<0 and any('right_hand_' in a['body'] for a in pair) and any(n.startswith('scene_collision_') for n in names):bad.append(dict(pair=pair,distance_m=float(c.dist)))
            depth=max([-c['distance_m'] for c in cs],default=0);pre=required_preload(cs,info['weight_n'],np.array(info['com_m']));groups=sorted(set(c['role'] for c in cs));vertical=max([abs(c['normal_vertical']) for c in cs if c['role']=='index'],default=1.)
            row.update(contacts=cs,groups=groups,preload=pre,max_virtual_penetration_m=depth,bad_contacts=bad,index_max_vertical_normal=vertical,eligible=bool(not bad and depth<=.008 and len(groups)==3 and pre['feasible']));results.append(row)
        print(dict(checked=len(results),offset=offset.tolist(),roll=roll),flush=True)
    ranked=sorted([a for a in results if a['eligible']],key=lambda a:(a['index_max_vertical_normal']>.5,a['preload']['total_normal_n'],a['max_virtual_penetration_m']))
    safe_save(root/'POSTURE_GEOMETRY_SCREEN.json',dict(new_physics_steps=0,candidate_wrist_poses=12,shape_checks=len(results),virtual_pelvis_translation_m=shift.tolist(),leg_joint_names=legnames,leg_reference_rad=fit.x.tolist(),leg_reference_initial_rad=q[lq].tolist(),foot_pose_residual=legerr.tolist(),candidates=results,ranked=ranked,selected=ranked[0] if ranked else None,source_report=_file_binding(source/'REPORT.json'),source_trace=_file_binding(source/'TRACE.json'),implementation=_file_binding(Path(__file__)),limitation='Private planning data only; virtual pelvis translation is not a simulator state update. A chosen reference must be sent through SONIC29 lowerbody/head/wrist inputs and physically validated; static force/geometry does not prove grasp.'))
    print(dict(qualified=len(ranked),top=[{k:a[k] for k in ['offset_local_m','roll_deg','closure','max_virtual_penetration_m','index_max_vertical_normal','preload']} for a in ranked[:3]]),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--source',type=Path,required=True);a=p.parse_args();run(a.root,a.source)
