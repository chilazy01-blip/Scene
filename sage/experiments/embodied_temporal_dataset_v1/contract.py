from pathlib import Path
import hashlib
import numpy as np
from sage.experiments.embodied_scene_quality_v2.contracts import read,read_ref,bound,require,reference,write_new

SCHEMA='scene-temporal-action-blocks/v1'

def arrays(path):
    with np.load(path,allow_pickle=False) as f:return {k:f[k] for k in f.files}

def statistics(rgb):
    require(rgb.dtype==np.uint8 and rgb.ndim==3 and rgb.shape[2]==3,'rgb_format')
    x=rgb.astype(np.float64);mean=x.mean((0,1));std=x.std((0,1))
    require(np.allclose(std,np.sqrt(((x-mean)**2).mean((0,1))),rtol=0,atol=1e-10),'rgb_variance_reference')
    return mean,std

def action_blocks(q,v,controls,gripper_ids,block=50):
    q=np.asarray(q);v=np.asarray(v);controls=np.asarray(controls);n=len(q)
    require(q.shape==v.shape==(n,7),'position_velocity_shape')
    require(n>0 and n%block==0 and controls.shape==(n,9),'substep_count')
    require(np.array_equal(controls[:,gripper_ids[0]],-controls[:,gripper_ids[1]]),'gripper_sign')
    result=np.column_stack([q,v,controls[:,gripper_ids[0]]]).reshape(n//block,block,15)
    require(np.isfinite(result).all(),'nonfinite_action');require(np.all((result[:,:,14]>=0)&(result[:,:,14]<=.04)),'gripper_range')
    return result

def check_times(times,steps,dt=.001):
    require(times.shape==steps.shape and len(times)>1,'time_shape')
    require(np.array_equal(steps,np.arange(len(times))*50),'frame_steps')
    require(np.allclose(times,steps*dt,rtol=0,atol=1e-9),'observation_times')

def source_evidence(p):
    for key in ['source_binding','source_episode','source_replay','source_raw','source_seal','source_controller_protocol','physical_model','task','source_camera','scene_manifest','layout']:
        ref=p[key];bound(ref['path'],ref['sha256'])
    episode=read_ref(p['source_episode']);replay=read_ref(p['source_replay']);seal=read_ref(p['source_seal'])
    require(episode['success'] and episode['status']=='fixed_episode_passed','source_task_failed')
    require(episode['new_physics_steps']==17500 and episode['raw']==p['source_raw'] and episode['binding']==p['source_binding'],'source_episode_identity')
    require(replay['passed'] and replay['new_physics_steps']==17500 and replay['source']==p['source_episode'] and replay['state_max_error']==replay['contact_max_error']==0,'source_replay_failed')
    require(seal['seal_passed'] and seal['all_services_stopped_mainpid_zero'],'source_not_sealed')
    old=read_ref(p['source_controller_protocol']);require(old['physical_model']==p['physical_model'] and old['task']==p['task'],'source_model_changed')
    require(old['controller']==p['action']['controller'],'source_controller_changed')
    camera=read_ref(p['source_camera']);require(camera['passed'] and camera['model']==p['physical_model'],'source_camera_failed')
    oldp=read_ref(old['source_protocol']);limits=p['observation']
    for k in ['width','height','minimum_visible_target_pixels','minimum_unoccluded_target_pixels','minimum_visible_fraction','rule']:
        require(limits[k]==oldp['observation'][k],'observation_condition_changed:'+k)
    require(p['scope']['split']=='development' and p['scope']['independent_validation_combinations']==0 and not p['scope']['production_qualified'],'scope_changed')
    require(limits['frame_steps']==list(range(0,17501,50)) and limits['frames']==351,'frame_schedule_changed')
    require(p['action']['shape']==[350,50,15] and p['action']['substep_dt_s']==.001 and p['action']['observation_dt_s']==.05,'action_contract_changed')
    return episode,camera

def prepare(protocol_path,output):
    import mujoco
    from sage.experiments.embodied_velocity_reference_v1.entry import load
    from sage.experiments.embodied_velocity_reference_v1.controller import VelocityReferenceController
    from sage.experiments.embodied_task_clearance_v1.visibility import camera_pose
    protocol_path=Path(protocol_path);output=Path(output);p=read(protocol_path);episode,camera=source_evidence(p)
    model,admission=load(p['source_binding']['path'],p['source_binding']['sha256'],'controller_evaluation','V01')
    raw=arrays(p['source_raw']['path']);data=mujoco.MjData(model);c=VelocityReferenceController(model,data)
    steps=np.asarray(p['observation']['frame_steps'],dtype=np.int64);lookup={int(step):i for i,step in enumerate(raw['snapshot_steps'])}
    require(all(int(k) in lookup for k in steps),'saved_frame_missing');states=raw['states'][[lookup[int(k)] for k in steps]].copy()
    action=action_blocks(raw['reference_positions'],raw['reference_velocities'],raw['controls'],c.fi)
    qi=np.r_[c.qi,[model.jnt_qposadr[model.joint(n).id] for n in ['finger_joint1','finger_joint2']]]
    vi=np.r_[c.vi,[model.jnt_dofadr[model.joint(n).id] for n in ['finger_joint1','finger_joint2']]]
    proprio=[];times=[]
    for state in states:
        mujoco.mj_setState(model,data,state,episode['state_spec']);mujoco.mj_forward(model,data)
        require(np.array_equal(state[1:1+model.nq],data.qpos) and np.array_equal(state[1+model.nq:1+model.nq+model.nv],data.qvel),'native_state_layout')
        proprio.append(np.r_[data.qpos[qi],data.qvel[vi]]);times.append(data.time)
    proprio=np.asarray(proprio);times=np.asarray(times);check_times(times,steps)
    pose,quat=camera_pose(read_ref(p['task'])['goal_pose_z_up'],read_ref(p['layout'])['room'],p['observation']['rule'])
    require(np.array_equal(pose,camera['position']) and np.array_equal(quat,camera['quaternion']),'camera_rule_changed')
    cid=int(camera['camera_id']);require(model.camera('overview').id==cid and model.cam_bodyid[cid]==0,'camera_identity')
    manifest=read_ref(p['scene_manifest']);task=read_ref(p['task'])
    names=[row['name'] for row in manifest['visuals'] if row['owner']==task['roles']['target_id']];ids=[model.geom(name).id for name in names]
    require(bool(ids) and all(model.geom_group[i]==1 for i in ids),'target_visuals')
    phase_ids=raw['phase_ids'].reshape(350,50);obs_phases=raw['phase_ids'][np.minimum(steps,17499)]
    path=output/'PREPARED.npz';require(not path.exists(),'prepared_already_exists')
    np.savez_compressed(path,action=action,controls=raw['controls'].reshape(350,50,9),states=states,proprio=proprio,times=times,steps=steps,
        phase_ids=phase_ids,observation_phase=obs_phases,substep_start=np.arange(17500).reshape(350,50)*.001,substep_end=np.arange(1,17501).reshape(350,50)*.001)
    value=dict(passed=True,prepared=reference(path),protocol=reference(protocol_path),state_spec=episode['state_spec'],nq=model.nq,nv=model.nv,
        qpos_ids=qi.tolist(),dof_ids=vi.tolist(),joint_actuator_ids=c.ai.tolist(),gripper_actuator_ids=c.fi,target_geom_names=names,target_geom_ids=ids,
        geom_object_type=int(mujoco.mjtObj.mjOBJ_GEOM),camera_id=cid,position=pose.tolist(),quaternion=quat.tolist(),fovy_deg=float(model.cam_fovy[cid]),
        image_origin='top_left',optical_axes='MuJoCo camera +X right +Y up -Z forward',pixel_center_convention='K uses width/2 and height/2',
        kp=c.kp.tolist(),kd=c.kd.tolist(),torque_limits=model.actuator_ctrlrange[c.ai].tolist(),phase_names=[e['phase'] for e in episode['events']],
        initial_state_exact=True,all_frames_available=True,native_proprio_checked=351,new_physics_steps=0,source_admission=admission)
    write_new(output/'PREPARE.json',value);return value
