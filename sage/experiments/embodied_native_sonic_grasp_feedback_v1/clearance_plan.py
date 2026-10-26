"""Diagnose failed clearance and check a taller lift on private native geometry."""
import argparse, os, resource
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from .posture_screen import load_model, IK, contact_pair
from .protocol import read_bound_json, safe_save, _file_binding

def run(root):
    import mujoco
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    episode=root/'attempt_11/full';r=read_bound_json(episode/'REPORT.json');t=read_bound_json(episode/'TRACE.json');case=read_bound_json(Path(r['case']['path']))
    assert r['stop_reason']=='loaded_hover_unstable' and r['load_probe_passed']
    hover=[x for x in t['records'] if x['stage']=='loaded_hover'];bottom=np.array([x['substeps'][-1]['object_bottom_m'] for x in hover]);required=case['support_top_m']+.025
    qevents=[e for e in r['events'] if e.get('kind')=='actual_wrench_quality' and e.get('stage')=='loaded_hover']
    diagnosis=dict(actual_hover_ticks=len(hover),minimum_actual_bottom_m=float(bottom.min()),maximum_actual_bottom_m=float(bottom.max()),required_actual_bottom_m=required,ticks_below_required=int(sum(bottom<=required)),actual_quality_failed_ticks=[e['tick'] for e in qevents if not e['quality']['qualified']],all_hover_samples_no_desk_support=all(not x['substeps'][-1]['desk_supported'] for x in hover),original_slip_stop_not_triggered=r['max_held_slip_m']<=.015,reference_change='Increase probe-origin lift goal from50mm to75mm, duration60 to98ticks so the quintic peak speed does not increase. Leave original measured clearance25mm, 1s continuous hover, slip/capacity/force and whole-task acceptance unchanged.',limitation='Clearance is established with the original acceptance metric; this plan does not claim that height is the only remaining stability limitation.')
    m=load_model(r['model']['path']);d=mujoco.MjData(m);s=t['records'][1213]['substeps'][-1];q0=np.array(s['full_qpos_after']);d.qpos[:]=q0;mujoco.mj_forward(m,d);w=m.body('right_wrist_yaw_link').id;pid=m.body('payload').id;pa=int(m.joint('payload_free').qposadr[0]);W=d.xpos[w].copy();WR=d.xmat[w].reshape(3,3).copy();OP=d.xpos[pid].copy();OR=d.xmat[pid].reshape(3,3).copy();local=WR.T@(OP-W);rel=WR.T@OR
    event=next(e for e in r['events'] if e.get('kind')=='cartesian_path' and e['tick']==1214);origin=np.array(event['origin']);goal=np.array(event['goal'])+[0,0,.025];R=np.array(event['rotation']);ik=IK(mujoco,m);seed=q0.copy();rows=[]
    for f in np.linspace(0,1,21):
        p=origin+(goal-origin)*f;fit=ik.solve(seed,p,R,max_evaluations=180);seed[ik.qids]=fit['angles_rad'];d.qpos[:]=seed;mujoco.mj_kinematics(m,d);actualp=d.xpos[w].copy();actualR=d.xmat[w].reshape(3,3).copy();d.qpos[pa:pa+3]=actualp+actualR@local;xyzw=Rotation.from_matrix(actualR@rel).as_quat();d.qpos[pa+3:pa+7]=xyzw[[3,0,1,2]];mujoco.mj_forward(m,d);bad=[]
        for c in d.contact:
            pair=contact_pair(m,c)
            if c.dist<0 and any(a['body'].startswith('right_hand_') or a['body']=='right_wrist_yaw_link' for a in pair) and any(a['name'].startswith('scene_collision_') for a in pair):bad.append(dict(pair=pair,distance_m=float(c.dist)))
        rows.append(dict(fraction=float(f),position_error_m=fit['position_error_m'],orientation_error_rad=fit['orientation_error_rad'],hand_scene_contacts=bad,passed=fit['position_error_m']<.005 and fit['orientation_error_rad']<.03 and not bad))
    result=dict(passed=all(x['passed'] for x in rows),new_physics_steps=0,diagnosis=diagnosis,goal_m=goal.tolist(),duration_ticks=98,old_peak_speed_m_s=1.875*.04/1.2,new_peak_speed_m_s=1.875*.065/1.96,private_native_ik_rows=rows,report=_file_binding(episode/'REPORT.json'),trace=r['trace'],implementation=_file_binding(Path(__file__)),limitation='Private kinematic query only. Virtual carried-payload positions are never injected into actual dynamics; original engine/model/native controls and all task gates unchanged. Does not prove dynamic grasp success.')
    assert result['new_peak_speed_m_s']<=result['old_peak_speed_m_s'];safe_save(root/'CLEARANCE_LIFT_PLAN.json',result);print(dict(passed=result['passed'],diagnosis=diagnosis,bad=[x for x in rows if not x['passed']]),flush=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);run(ap.parse_args().root)
