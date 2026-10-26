"""Check the actual native-mesh open approach to a selected mesh grasp reference."""
import argparse,os,resource
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from .posture_screen import IK,hand_ids,contact_pair,load_model,safe_save,read_bound_json,_file_binding
from sage.experiments.embodied_native_object_transport_v1.task_v3 import smooth

def run(root):
    import mujoco
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    plan=read_bound_json(root/'NATIVE_MESH_GRASP_PLAN.json');c=plan['selected'];assert c is not None
    source=Path('/data/wsj/main/scene_runs/codex_trellis_v2/embodied_native_sonic_transport_20261022_v1/version_04/full');r=read_bound_json(source/'REPORT.json');t=read_bound_json(source/'TRACE.json');m=load_model(r['model']['path']);d=mujoco.MjData(m);q0=np.array(t['records'][-1]['substeps'][-1]['full_qpos_after']);d.qpos[:]=q0;mujoco.mj_forward(m,d);w=m.body('right_wrist_yaw_link').id;origin=d.xpos[w].copy();R0=d.xmat[w].reshape(3,3).copy();R=np.array(c['rotation']);goal=np.array(c['wrist_goal_m']);above=goal+[0,0,.10];delta=Rotation.from_matrix(R0.T@R).as_rotvec();ik=IK(mujoco,m);h=hand_ids(m);seed=q0.copy();out=[]
    stages=[('rotate_and_approach',[(origin*(1-f)+above*f,R0@Rotation.from_rotvec(delta*f).as_matrix()) for f in smooth(np.linspace(0,1,25))]),('vertical_open_descent',[(goal+[0,0,z],R) for z in np.linspace(.10,0,20)])]
    for stage,poses in stages:
        for index,(pos,rot) in enumerate(poses):
            fit=ik.solve(seed,pos,rot,max_evaluations=160);seed[ik.qids]=fit['angles_rad']
            for handstate in ['recorded_open','zero_target_open']:
                d.qpos[:]=seed
                if handstate=='zero_target_open':d.qpos[h['qpos']]=0.
                mujoco.mj_forward(m,d);cup=[];scene=[]
                for contact in d.contact:
                    pair=contact_pair(m,contact);names=[a['name'] for a in pair];hand=any(a['body'].startswith('right_hand_') or a['body']=='right_wrist_yaw_link' for a in pair)
                    if not hand:continue
                    if 'payload_surface' in names and contact.dist<0:cup.append(float(contact.dist))
                    if any(n.startswith('scene_collision_') for n in names) and contact.dist<0:scene.append(dict(pair=pair,distance_m=float(contact.dist)))
                depth=max([-v for v in cup],default=0.);out.append(dict(stage=stage,index=index,open_hand_state=handstate,position_error_m=fit['position_error_m'],orientation_error_rad=fit['orientation_error_rad'],max_cup_depth_m=depth,scene=scene,passed=bool(fit['position_error_m']<=.01 and fit['orientation_error_rad']<=.05 and depth<=.001 and not scene)))
    result=dict(passed=all(x['passed'] for x in out),new_physics_steps=0,rows=out,grasp_plan=_file_binding(root/'NATIVE_MESH_GRASP_PLAN.json'),source_trace=_file_binding(source/'TRACE.json'),implementation=_file_binding(Path(__file__)),limitation='Private full native-mesh geometry checks at fixed recorded body posture and two open finger states; does not establish actual SONIC tracking or grasp success. No actual model/physical parameter changes.');safe_save(root/'NATIVE_MESH_PATH_CHECK.json',result);print(dict(passed=result['passed'],bad=[x for x in out if not x['passed']]),flush=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);run(ap.parse_args().root)
