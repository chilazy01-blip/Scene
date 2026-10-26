"""Zero-step workspace screen for braking after required real transport is achieved."""
import argparse,os,resource
from pathlib import Path
import numpy as np
from .protocol import read_bound_json,safe_save,_file_binding
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_native_object_transport_v1.kinematics_r3 import IK

def run(root):
    import mujoco
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    episode=root/'attempt_24/full';r=read_bound_json(episode/'REPORT.json');t=read_bound_json(episode/'TRACE.json');case=read_bound_json(Path(r['case']['path']));N=next(i for i,a in enumerate(t['records']) if a['stage']=='carry');origin=np.array(t['events'][next(i for i,e in enumerate(t['events']) if e.get('stage')=='carry')]['root_m']);states=dict(left='unknown',right='unknown');cycles=dict(left=0,right=0);selected=None
    for i in range(N,len(t['records'])):
        s=t['records'][i]['substeps'][-1]
        for side,foot in s['feet'].items():
            if foot['ground_force_n']>2:
                if states[side]=='swing':cycles[side]+=1
                states[side]='stance'
            elif foot['ground_force_n']<=1 and foot['clearance_m']>=.015 and states[side]=='stance':states[side]='swing'
        if s['root_m'][0]-origin[0]>=.25 and all(cycles[z]>=1 for z in states):selected=(i,s);break
    assert selected is not None
    tick,s=selected;model=load_model(r['model']['path']);solver=IK(mujoco,model);graspR=np.asarray(case['loaded_grasp_rotation']);goal=np.asarray(case['target_object_xyz_m'])-graspR@np.asarray(s['object_local_m']);q=np.asarray(s['full_qpos_after']);rows=[]
    for predicted_braking_advance in (0.,.05,.10,.15,.20):
        query=q.copy();query[0]+=predicted_braking_advance
        fit=solver.solve(query,goal,graspR,max_evaluations=150)
        rows.append(dict(predicted_forward_braking_advance_m=predicted_braking_advance,query_root_x_m=float(query[0]),fit=fit,workspace_eligible=fit['position_error_m']<.01 and fit['orientation_error_rad']<.05))
    safe_save(root/'EARLY_STOP_REACHABILITY.json',dict(new_physics_steps=0,report=_file_binding(episode/'REPORT.json'),trace=r['trace'],selected_tick=tick,actual_root=s['root_m'],real_forward_carry_m=s['root_m'][0]-origin[0],foot_cycles=cycles,target_object_original_m=case['target_object_xyz_m'],wrist_placement_goal_world_m=goal.tolist(),queries=rows,implementation=_file_binding(Path(__file__)),limitation='Private FK/arm workspace queries only; offsets are hypothetical forward braking progress, not injected physical states or verified braking outcomes. Same original world placement goal and task gates.'))
    print(dict(selected_tick=tick,queries=[dict(advance=x['predicted_forward_braking_advance_m'],eligible=x['workspace_eligible'],position_error=x['fit']['position_error_m']) for x in rows]),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);run(ap.parse_args().root)
