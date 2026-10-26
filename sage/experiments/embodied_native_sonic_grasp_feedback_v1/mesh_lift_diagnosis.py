"""Measured wrist/hand limits and actual load quality in the failed mesh-grasp lift."""
import argparse,os,resource
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from .posture_screen import load_model,hand_ids
from .protocol import read_bound_json,safe_save,_file_binding

def run(episode):
    import mujoco
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    r=read_bound_json(episode/'REPORT.json');t=read_bound_json(episode/'TRACE.json');case=read_bound_json(Path(r['case']['path']));m=load_model(r['model']['path']);d=mujoco.MjData(m);h=hand_ids(m);ix=np.array([i for i,n in enumerate(h['names']) if n in case['mesh_finger_template']]);w=m.body('right_wrist_yaw_link').id;R=np.array(case['loaded_grasp_rotation']);out=[]
    for tick in [1143,1144,1213,1214,1215,1220,1225,1230,1235,1240,1245,len(t['records'])-1]:
        if tick>=len(t['records']):continue
        row=t['records'][tick];s=row['substeps'][-1];d.qpos[:]=s['full_qpos_after'];mujoco.mj_kinematics(m,d);wr=d.xmat[w].reshape(3,3);names=[h['names'][i] for i in ix];targets=np.array(s['hand_target_rad'])[ix];actual=d.qpos[h['qpos'][ix]];ratios={n:float(v/case['mesh_finger_template'][n]) for n,v in zip(names,targets)}
        out.append(dict(tick=tick,stage=row['stage'],time_s=s['time_after_s'],wrist_position_m=d.xpos[w].tolist(),wrist_rotation_error_rad=Rotation.from_matrix(R.T@wr).as_rotvec().tolist(),object_m=s['object_m'],object_local_m=s['object_local_m'],desk_supported=s['desk_supported'],actual_group_normal_n=s['forces'],right_finger_names=names,reference_closures=ratios,hand_target_rad=targets.tolist(),actual_finger_angles_rad=actual.tolist(),right_finger_reference_error_rad=(targets-actual).tolist(),actual_motor_torque_nm=np.array(s['actual_finger_actuator_force_nm'])[ix].tolist(),requested_motor_torque_nm=np.array(s['finger_requested_torque_nm'])[ix].tolist(),actual_joint_velocity_rad_s=np.array(s['full_qvel_after'])[h['dofs'][ix]].tolist()))
    safe_save(episode.parent/'MESH_LIFT_DIAGNOSIS.json',dict(new_physics_steps=0,report=_file_binding(episode/'REPORT.json'),trace=r['trace'],rows=out,implementation=_file_binding(Path(__file__)),limitation='Measured reference/motor/pose timing; does not by itself prove a unique cause of contact loss. No force or model changes and no new integration.'))
    print([dict(tick=x['tick'],stage=x['stage'],rotation_error_rad=float(np.linalg.norm(x['wrist_rotation_error_rad'])),ref_error=x['right_finger_reference_error_rad'],motor=x['actual_motor_torque_nm'],forces=x['actual_group_normal_n'],object_local=x['object_local_m']) for x in out],flush=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--episode',type=Path,required=True);run(ap.parse_args().episode)
