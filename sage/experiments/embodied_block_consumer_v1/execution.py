from pathlib import Path
import json,traceback
import h5py
import numpy as np
from scipy.spatial.transform import Rotation
from sage.experiments.embodied_scene_quality_v2.contracts import read,read_ref,reference,digest,require,write_new
from sage.experiments.embodied_temporal_dataset_v1.contract import arrays
from sage.experiments.embodied_velocity_reference_v1.execution import contacts
from .executor import ActionBlockExecutor
from .entry import load


class ReferenceAudit:
    """Saved controls are comparison-only; this object never writes native state."""
    def __init__(self,model,data,engine,raw,spec,target_qpos,atol):
        self.model=model;self.data=data;self.engine=engine;self.raw=raw;self.spec=spec;self.target_qpos=target_qpos;self.atol=atol
        self.lookup={int(k):i for i,k in enumerate(raw['snapshot_steps'])}
        self.errors=dict(control=0.,state=0.,contact=0.,joint_state=0.,object_pose=0.,proprio=0.,time=0.)
        self.commands=[];self.command_steps=[];self.states=[];self.state_steps=[];self.contact_rows=[];self.offsets=[0];self.blocks=[];self.contact_checks=0;self.joint_checks=0;self.boundary_checks=0
    def check(self,name,value):
        self.errors[name]=max(self.errors[name],float(value));require(value<=(1e-9 if name=='time' else self.atol),'consumer_mismatch:'+name)
    def state(self,step,score_contacts):
        import mujoco
        state=np.empty(mujoco.mj_stateSize(self.model,self.spec));mujoco.mj_getState(self.model,self.data,state,self.spec)
        self.states.append(state);self.state_steps.append(step);self.check('state',np.max(abs(state-self.raw['states'][self.lookup[step]])))
        cc=contacts(self.model,self.data);self.contact_rows.append(cc);self.offsets.append(self.offsets[-1]+len(cc))
        if score_contacts:
            i=self.lookup[step];expected=self.raw['contacts'][self.raw['contact_offsets'][i]:self.raw['contact_offsets'][i+1]]
            require(cc.shape==expected.shape,'consumer_mismatch:contact_count');self.check('contact',np.max(abs(cc-expected),initial=0));self.contact_checks+=1
    def before(self,step,control):
        self.commands.append(control);self.command_steps.append(step)
        self.check('control',np.max(abs(control-self.raw['controls'][step])))
    def after(self,step):
        c=self.engine.controller;self.check('joint_state',np.max(abs(np.r_[self.data.qpos[c.qi],self.data.qvel[c.vi]]-self.raw['joint_states'][step-1])))
        self.check('object_pose',np.max(abs(self.data.qpos[self.target_qpos:self.target_qpos+7]-self.raw['object_qpos'][step-1])));self.joint_checks+=1
        if step in self.lookup:self.state(step,True)
    def boundary(self,observation,proprio,time):
        self.check('proprio',np.max(abs(observation['proprio']-proprio)));self.check('time',abs(observation['time']-time));self.boundary_checks+=1


def consume(binding_path,pin,output):
    import mujoco
    output=Path(output);require(not (output/'STARTED.json').exists(),'consumer_attempt_already_started')
    b=read(binding_path);p=read_ref(b['protocol']);model,dataset,admission=load(binding_path,pin,'consumer_evaluation',p['request_id'])
    raw=arrays(p['reference_raw']['path']);source=read_ref(p['reference_episode']);prepared=read_ref(p['dataset_prepared']);data=mujoco.MjData(model)
    with h5py.File(dataset.path,'r') as f:initial=f['audit/integration_state'][0].copy()
    require(np.array_equal(initial,raw['states'][0]),'initial_state_changed')
    spec=int(source['state_spec']);mujoco.mj_setState(model,data,initial,spec);mujoco.mj_forward(model,data);mujoco.mj_setState(model,data,initial,spec)
    engine=ActionBlockExecutor(model,data,p['action_contract'],p['budget']['max_physics_steps'])
    task=read_ref(p['task']);bid=model.body(task['target_body']).id;target_qpos=int(model.jnt_qposadr[model.body_jntadr[bid]])
    audit=ReferenceAudit(model,data,engine,raw,spec,target_qpos,p['comparison']['atol']);audit.state(0,False)
    write_new(output/'STARTED.json',dict(request_id=p['request_id'],new_physical_attempts=1,max_physics_steps=17500,dataset_binding=p['dataset_binding'],initial_full_state_exact=True,source_controls_comparison_only=True))
    result=dict(status='consumer_running',passed=False);log=(output/'BLOCKS.jsonl').open('x')
    try:
        for block_index in range(len(dataset)):
            row=dataset[block_index]
            audit.boundary(engine.observe(),row['proprio'],row['time'])
            actual=engine.step(row['action'],block_index=block_index,start_time=row['time'],before_step=audit.before,after_step=audit.after)
            audit.boundary(actual,row['next_proprio'],row['next_time'])
            record=dict(block=block_index,completed_steps=engine.steps,time=actual['time'],errors=dict(audit.errors));audit.blocks.append(record);log.write(json.dumps(record)+'\n');log.flush()
            if (block_index+1)%50==0:print(json.dumps(dict(blocks=engine.blocks,steps=engine.steps,errors=audit.errors)),flush=True)
        require(engine.steps==17500 and engine.blocks==350 and len(audit.commands)==17500 and len(audit.states)==1751 and audit.contact_checks==1750,'incomplete_consumer_regression')
        result.update(status='consumer_regression_passed',passed=True)
    except BaseException as exc:
        result.update(status='consumer_regression_failed',error=str(exc),traceback=traceback.format_exc())
    finally:
        log.close()
        final_state=np.empty(mujoco.mj_stateSize(model,spec));mujoco.mj_getState(model,data,final_state,spec)
        final_contacts=contacts(model,data);path=output/'RAW.npz'
        np.savez_compressed(path,controls=np.asarray(audit.commands).reshape(-1,model.nu),command_steps=audit.command_steps,
            states=np.asarray(audit.states),snapshot_steps=audit.state_steps,contacts=np.concatenate(audit.contact_rows),contact_offsets=audit.offsets,
            final_state=final_state,final_contacts=final_contacts)
        goal=np.asarray(task['goal_pose_z_up']);final_position=data.qpos[target_qpos:target_qpos+3].copy()
        final_xy=float(np.linalg.norm(final_position[:2]-goal[:2,3]));final_angle=float(np.rad2deg(Rotation.from_matrix(goal[:3,:3].T@data.xmat[bid].reshape(3,3)).magnitude()))
        result.update(request_id=p['request_id'],binding=reference(binding_path),raw=reference(path),new_physical_attempts=1,new_physics_steps=engine.steps,native_step_calls=engine.step_calls,
            completed_blocks=engine.blocks,issued_commands=len(audit.commands),integration_state_checks=len(audit.states),contact_checks=audit.contact_checks,joint_object_checks=audit.joint_checks,
            boundary_checks=audit.boundary_checks,maximum_errors=audit.errors,initial_full_state_exact=True,source_episode_success=source['success'],
            final_position_world_m=final_position.tolist(),final_goal_xy_error_m=final_xy,final_goal_orientation_error_deg=final_angle,
            object_state_writes_after_initialization=0,new_ik_queries=0,new_path_checks=0,source_controls_used_for_driving=False,
            reference_trajectory_generator_calls=0,live_rgb_renders=0,policy_forwards=0,new_independent_task_qualification=False,qualified_collection=False,qualified_export=False)
        write_new(output/'RESULT.json',result)
    return result
