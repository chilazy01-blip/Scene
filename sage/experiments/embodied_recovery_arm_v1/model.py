from collections import deque
import torch
from torch import nn
from sage.experiments.embodied_action_horizon_v1.model import forward


class LearnedArm(nn.Module):
    """Robot state to ten anchored joint commands; no trajectory or phase at inference."""
    def __init__(self, stats):
        super().__init__()
        self.register_buffer('mean',torch.tensor(stats['mean'],dtype=torch.float32))
        self.register_buffer('std',torch.tensor(stats['std'],dtype=torch.float32))
        self.net=nn.Sequential(nn.Linear(18,256),nn.Tanh(),nn.Linear(256,256),nn.Tanh(),nn.Linear(256,70))
        nn.init.zeros_(self.net[-1].weight);nn.init.zeros_(self.net[-1].bias)

    def forward(self, state):
        return self.net((state.float()-self.mean)/self.std).reshape(-1,10,7)*.05


def augment_state(state, tangent, q_noise, v_noise, enabled):
    """Training-only perturbations normal to the demonstrated local arm direction."""
    length=tangent.norm(dim=-1,keepdim=True)
    unit=torch.where(length>1e-8,tangent/length.clamp_min(1e-8),torch.zeros_like(tangent))
    q_noise=q_noise-(q_noise*unit).sum(-1,keepdim=True)*unit
    v_noise=v_noise-(v_noise*unit).sum(-1,keepdim=True)*unit
    noisy=state.clone()
    noisy[:,:7]+=q_noise*enabled[:,None]
    noisy[:,9:16]+=v_noise*enabled[:,None]
    return noisy


def replace_arm_output(base_output, arm_delta, codec):
    effective=base_output.clone()
    effective[:,:,:7]=(arm_delta-codec.mean[None,:,:7])/codec.std[None,:,:7]
    return effective


class LearnedArmQueue:
    """Neural proprioceptive arm head plus frozen visual ACT gripper head."""
    def __init__(self,base,pre,codec,arm,n_action_steps):
        if n_action_steps not in (1,10):raise ValueError(n_action_steps)
        self.base,self.pre,self.codec,self.arm=base,pre,codec,arm
        self.n_action_steps=n_action_steps;self.queue=deque()

    def select(self,sample,step):
        refresh=not self.queue
        if refresh:
            self.base.eval();self.arm.eval()
            with torch.inference_mode(),torch.autocast(device_type='cuda',enabled=False):
                state=sample['observation.state'].float().to(self.codec.mean.device)[None]
                base=forward(self.base,self.pre(sample)).float();delta=self.arm(state)
                effective=replace_arm_output(base,delta,self.codec)
                commands=self.codec.decode(effective,state[:,:7])[0].cpu().numpy()
                self.anchor=state[0,:7].cpu().tolist()
                output=effective[0].cpu().numpy();base=base[0].cpu().numpy();delta=delta[0].cpu().numpy()
            self.queue.extend((commands[k].copy(),output[k].copy(),base[k].copy(),delta[k].copy(),k) for k in range(self.n_action_steps))
            self.prediction_step=step
        command,output,base,delta,offset=self.queue.popleft()
        return command,dict(prediction_refreshed=refresh,prediction_step=self.prediction_step,chunk_offset=offset,
            anchor_q=self.anchor,head_output=output.tolist(),base_head_output=base.tolist(),
            neural_arm_delta_rad=delta.tolist(),gripper_head='frozen_visual_ACT_regression',
            arm_head='learned_proprioceptive_command',uses_phase_time_or_expert_plan=False)
