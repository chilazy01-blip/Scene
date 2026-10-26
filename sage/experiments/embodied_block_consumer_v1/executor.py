import numpy as np
from sage.experiments.embodied_scene_quality_v2.contracts import require
from sage.experiments.embodied_velocity_reference_v1.controller import VelocityReferenceController


def canonical_contract():
    return dict(schema='joint_position_velocity_gripper_block/v1',shape=[50,15],joint_order=[f'joint{i}' for i in range(1,8)],
        position_unit='rad',velocity_unit='rad/s',gripper_unit='m',substep_dt_s=.001,block_steps=50,
        reference_sample='at substep end; command applied during [start,end)')


def validate_contract(contract):
    require(contract==canonical_contract(),'action_contract_changed')


def validate_block(block,contract,joint_ranges):
    validate_contract(contract)
    require(isinstance(block,np.ndarray) and block.dtype==np.float64 and block.shape==(50,15),'action_shape_or_dtype')
    value=block.copy();require(np.isfinite(value).all(),'nonfinite_action')
    require(np.all(value[:,:7]>=joint_ranges[:,0]) and np.all(value[:,:7]<=joint_ranges[:,1]),'joint_position_range')
    require(np.all((value[:,14]>=0)&(value[:,14]<=.04)),'gripper_range')
    return value


class ActionBlockExecutor:
    """No reference trajectory generation, source controls, reset or object writes."""
    def __init__(self,model,data,contract,max_steps=17500):
        validate_contract(contract);require(model.opt.timestep==contract['substep_dt_s'],'native_timestep_changed')
        self.model=model;self.data=data;self.contract=dict(contract);self.controller=VelocityReferenceController(model,data)
        self.joint_ranges=model.jnt_range[self.controller.joints].copy()
        self.qpos_ids=np.r_[self.controller.qi,[model.jnt_qposadr[model.joint(n).id] for n in ['finger_joint1','finger_joint2']]]
        self.dof_ids=np.r_[self.controller.vi,[model.jnt_dofadr[model.joint(n).id] for n in ['finger_joint1','finger_joint2']]]
        self.origin=float(data.time);self.steps=0;self.step_calls=0;self.blocks=0;self.max_steps=max_steps;self.failed=False
    def observe(self):
        return dict(proprio=np.r_[self.data.qpos[self.qpos_ids],self.data.qvel[self.dof_ids]].copy(),time=float(self.data.time))
    def step(self,block,*,block_index,start_time,before_step=None,after_step=None):
        require(not self.failed,'executor_failed')
        value=validate_block(block,self.contract,self.joint_ranges)
        require(self.model.opt.timestep==self.contract['substep_dt_s'],'native_timestep_changed')
        require(isinstance(block_index,int) and block_index==self.blocks,'block_order')
        require(np.isfinite(start_time) and abs(start_time-self.origin-self.steps*.001)<=1e-9 and abs(self.data.time-start_time)<=1e-9,'block_start_time')
        require(self.steps+50<=self.max_steps,'consumer_step_budget')
        import mujoco
        try:
            for row in value:
                self.controller.action(row[:7],float(row[14]),row[7:14])
                if before_step is not None:before_step(self.steps,self.data.ctrl.copy())
                self.step_calls+=1;mujoco.mj_step(self.model,self.data);self.steps+=1;mujoco.mj_forward(self.model,self.data)
                require(np.isfinite(self.data.qpos).all() and np.isfinite(self.data.qvel).all(),'nonfinite_physics')
                require(not any(w.number for w in self.data.warning),'simulator_warning')
                if after_step is not None:after_step(self.steps)
            self.blocks+=1
        except BaseException:
            self.failed=True;raise
        return self.observe()
