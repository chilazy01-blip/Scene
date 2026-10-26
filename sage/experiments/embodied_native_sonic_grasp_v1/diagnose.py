"""Reconstruct recorded finger PD/ranges and actual grip geometry; no integration."""
import argparse
from pathlib import Path
import numpy as np
from sage.experiments.embodied_native_walk_motion_v2.engine import hand_ids
from sage.experiments.embodied_native_sonic_transport_v1.restore import load_after
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding


def run(root,parent):
    import mujoco
    p=read_bound_json(parent/'PROTOCOL.json');t=read_bound_json(parent/'version_04_ordered/full/TRACE.json');case=read_bound_json(parent/'CASE_V4.json');scene=read_bound_json(Path(p['scene']['path']))
    model=load_model(scene['model']['path']);model.opt.timestep=.005;data=mujoco.MjData(model);h=hand_ids(model);right=np.array(['right_' in n for n in h['names']]);hr=np.flatnonzero(right)
    lo,hi=model.actuator_ctrlrange[h['actuators']].T
    stats=[];phases={}
    for stage in ['insert','close','lift']:
        rows=[s for r in t['records'] for s in r['substeps'] if s['stage']==stage]
        wanted=np.array([s['hand_target_rad'] for s in rows]);q=np.array([s['full_qpos_before'] for s in rows])[:,h['qpos']];v=np.array([s['full_qvel_before'] for s in rows])[:,h['dofs']]
        torque=h['kp']*(wanted-q)-h['kd']*v;ctrl=np.array([s['all_ctrl'] for s in rows])[:,h['actuators']]
        np.testing.assert_array_equal(ctrl,np.clip(torque,lo,hi))
        phases[stage]=dict(steps=len(rows),finger_torque_reconstruction_error=0.,joints={})
        for j in hr:
            phases[stage]['joints'][h['names'][j]]=dict(peak_abs_requested_nm=float(np.max(np.abs(torque[:,j]))),peak_abs_applied_nm=float(np.max(np.abs(ctrl[:,j]))),original_native_range_nm=[float(lo[j]),float(hi[j])],saturated_steps=int(np.sum((torque[:,j]<=lo[j])|(torque[:,j]>=hi[j]))),final_target_rad=float(wanted[-1,j]),final_actual_rad=float(q[-1,j]),peak_abs_position_error_rad=float(np.max(np.abs(wanted[:,j]-q[:,j]))))
    indices={name:next(i for i,r in enumerate(t['records']) if r['stage']==name) for name in ['insert','close','lift']}
    indices['final']=len(t['records'])-1
    for label,i in indices.items():
        s=t['records'][i]['substeps'][-1];load_after(mujoco,model,data,s);b=model.body('right_wrist_yaw_link').id
        stats.append(dict(label=label,tick=t['records'][i]['tick'],time_s=data.time,wrist_world_m=data.xpos[b].tolist(),wrist_rotation=data.xmat[b].reshape(3,3).tolist(),object_world_m=s['object_m'],object_local_m=s['object_local_m'],forces=s['forces'],actual_hand_qpos=data.qpos[h['qpos']].tolist(),finger_targets=s['hand_target_rad']))
    safe_save(root/'FINGER_DIAGNOSIS.json',dict(schema='native-sonic29-finger-diagnosis/v1',new_physics_steps=0,phases=phases,key_states=stats,old_nominal_grasp_local_m=case['grasp_local_xyz_m'],
        actual_finger_torque_is_clipped_original_PD=True,any_finger_saturation=any(j['saturated_steps'] for a in phases.values() for j in a['joints'].values()),
        baseline_report=_file_binding(parent/'version_04_ordered/full/REPORT.json'),baseline_trace=_file_binding(parent/'version_04_ordered/full/TRACE.json'),model=_file_binding(Path(scene['model']['path'])),implementation=_file_binding(Path(__file__))))
    print(dict(new_physics_steps=0,any_finger_saturation=any(j['saturated_steps'] for a in phases.values() for j in a['joints'].values()),key_states=stats),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);ap.add_argument('--parent',type=Path,required=True);a=ap.parse_args();run(a.root,a.parent)
