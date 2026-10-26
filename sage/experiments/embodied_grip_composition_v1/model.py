from collections import deque
import numpy as np
import torch
from sage.experiments.embodied_action_horizon_v1.model import forward
from sage.experiments.embodied_recovery_arm_v1.model import replace_arm_output


def load_components(freeze):
    from pathlib import Path
    from safetensors.torch import load_file
    from sage.experiments.embodied_scene_bridge.contracts import read,digest
    from sage.experiments.embodied_recovery_arm_v1.model import LearnedArm
    from sage.experiments.embodied_action_horizon_v1.model import load_policy as load_short,HorizonCodec
    from sage.experiments.embodied_gripper_transition_v1.model import load_policy as load_full
    assert digest(freeze['arm_freeze'])==freeze['arm_freeze_sha256']
    assert digest(freeze['visual_freeze'])==freeze['visual_freeze_sha256']
    af=read(freeze['arm_freeze']);vf=read(freeze['visual_freeze'])
    for component in [af,vf]:
        for rel,sha in component['files'].items():assert digest(Path(component['selected']['path'])/rel)==sha
        assert digest(component['stats_file'])==component['stats_sha256']
    assert af['stats_sha256']==vf['stats_sha256']
    stats=read(af['stats_file']);codec=HorizonCodec(stats,'cuda',10)
    assert digest(af['state_stats_file'])==af['state_stats_sha256']
    arm=LearnedArm(read(af['state_stats_file'])).cuda()
    arm.load_state_dict(load_file(str(Path(af['selected']['path'])/'arm.safetensors')));arm.eval()
    if freeze['visual_head_kind']=='binary':
        base=load_full(vf['source_base'],stats,'binary',checkpoint=vf['selected']['path'])
    else:
        base=load_short(vf['source_base'],stats,'regression',checkpoint=vf['selected']['path'],horizon=10)
    return base.eval(),arm,codec


def compose(base_output,arm_delta,state,codec,kind):
    prefix=base_output[:,:10]
    effective=replace_arm_output(prefix,arm_delta,codec)
    commands=codec.decode(effective,state[:,:7])
    if kind=='binary':logits=prefix[:,:,7]
    elif kind=='regression':logits=2*(commands[:,:,7]-.02)/.02
    else:raise ValueError(kind)
    commands=commands.clone();commands[:,:,7]=torch.where(logits>=0,.04,0.)
    return commands,effective,prefix,logits


class ComposedQueue:
    def __init__(self,base,pre,codec,arm,kind,n_action_steps=10):
        if n_action_steps!=10:raise ValueError(n_action_steps)
        self.base,self.pre,self.codec,self.arm,self.kind=base,pre,codec,arm,kind
        self.queue=deque()

    def select(self,sample,step):
        refreshed=not self.queue
        if refreshed:
            self.base.eval();self.arm.eval()
            with torch.inference_mode(),torch.autocast(device_type='cuda',enabled=False):
                state=sample['observation.state'].float().to(self.codec.mean.device)[None]
                base=forward(self.base,self.pre(sample)).float();delta=self.arm(state)
                commands,effective,prefix,logits=compose(base,delta,state,self.codec,self.kind)
                self.anchor=state[0,:7].cpu().tolist()
                arrays=[x[0].cpu().numpy() for x in [commands,effective,prefix,delta,logits]]
            arrays[0]=arrays[0].astype('f8')
            arrays[0][:,7]=np.where(arrays[-1]>=0,.04,0.)
            self.queue.extend((*[x[k].copy() for x in arrays],k) for k in range(10))
            self.prediction_step=step
        command,output,base,delta,logit,offset=self.queue.popleft()
        return command,dict(prediction_refreshed=refreshed,prediction_step=self.prediction_step,chunk_offset=offset,
            anchor_q=self.anchor,head_output=output.tolist(),base_head_output=base.tolist(),
            neural_arm_delta_rad=delta.tolist(),gripper_logit=float(logit),gripper_source_kind=self.kind,
            gripper_head='binary_visual',uses_phase_time_or_expert_plan=False)
