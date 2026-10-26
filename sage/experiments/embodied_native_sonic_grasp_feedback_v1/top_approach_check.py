"""Private FK for the newly rotated approach, zero integrated physics steps."""
import argparse,resource,os
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from .posture_screen import IK,contacts,contact_pair,load_model,safe_save,read_bound_json,_file_binding
from sage.experiments.embodied_native_object_transport_v1.task_v3 import smooth

def run(root):
    import mujoco
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    screen=read_bound_json(root/'AXIS_TOP_REFERENCE_CHECK_R2.json');c=min([x for x in screen['candidates'] if x['eligible']],key=lambda x:x['maximum_vertical_normal']);source=Path('/data/wsj/main/scene_runs/codex_trellis_v2/embodied_native_sonic_transport_20261022_v1/version_04/full');r=read_bound_json(source/'REPORT.json');t=read_bound_json(source/'TRACE.json');model=load_model(r['model']['path']);d=mujoco.MjData(model);q=np.array(t['records'][-1]['substeps'][-1]['full_qpos_after']);d.qpos[:]=q;mujoco.mj_forward(model,d);w=model.body('right_wrist_yaw_link').id;origin=d.xpos[w].copy();R0=d.xmat[w].reshape(3,3).copy();R=np.array(c['rotation']);goal=np.array(c['wrist_goal_m'])+[0,0,.10];delta=Rotation.from_matrix(R0.T@R).as_rotvec();ik=IK(mujoco,model);seed=q.copy();rows=[]
    for f in smooth(np.linspace(0,1,25)):
        pos=origin*(1-f)+goal*f;rot=R0@Rotation.from_rotvec(delta*f).as_matrix();fit=ik.solve(seed,pos,rot,max_evaluations=180);seed[ik.qids]=fit['angles_rad'];d.qpos[:]=seed;mujoco.mj_forward(model,d);cs,info=contacts(mujoco,model,d,True);bad=[]
        for contact in d.contact:
            pair=contact_pair(model,contact)
            if contact.dist<0 and any('right_hand_' in a['body'] for a in pair) and any(a['name'].startswith('scene_collision_') for a in pair):bad.append(dict(pair=pair,distance_m=float(contact.dist)))
        depth=max([-x['distance_m'] for x in cs],default=0.);rows.append(dict(fraction=float(f),ik_position_error_m=fit['position_error_m'],ik_orientation_error_rad=fit['orientation_error_rad'],open_cup_depth_m=depth,bad=bad,passed=bool(fit['position_error_m']<=.01 and fit['orientation_error_rad']<=.05 and depth<=.001 and not bad)))
    result=dict(passed=all(x['passed'] for x in rows),new_physics_steps=0,rows=rows,screen=_file_binding(root/'AXIS_TOP_REFERENCE_CHECK_R2.json'),implementation=_file_binding(Path(__file__)),source_trace=_file_binding(source/'TRACE.json'),limitation='Private reference geometry only; actual SONIC tracking and physical contact remain unverified.');safe_save(root/'TOP_APPROACH_CHECK.json',result);print(dict(passed=result['passed'],bad=[x for x in rows if not x['passed']]),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);run(p.parse_args().root)
