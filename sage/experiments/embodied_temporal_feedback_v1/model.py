import torch
from lerobot.policies.act.modeling_act import ACTTemporalEnsembler
from sage.experiments.embodied_action_horizon_v1.model import forward
from sage.experiments.embodied_state_residual_v1.model import corrected_output


class TemporalResidual:
    """Average overlapping absolute arm forecasts, keep current gripper prediction."""
    def __init__(self, base, pre, codec, residual, n_action_steps=1, coefficient=.01):
        if n_action_steps != 1:
            raise ValueError('Temporal inference must refresh each observation')
        self.base, self.pre, self.codec, self.residual = base, pre, codec, residual
        self.ensemble = ACTTemporalEnsembler(coefficient, 10)

    def select(self, sample, step):
        self.base.eval();self.residual.eval()
        with torch.inference_mode(), torch.autocast(device_type='cuda', enabled=False):
            state=sample['observation.state'].float().to(self.codec.mean.device)[None]
            base=forward(self.base,self.pre(sample)).float()
            output,correction=corrected_output(base,state,self.residual,self.codec)
            generated=self.codec.decode(output,state[:,:7])
            first_arm=self.ensemble.update(generated[:,:,:7])
            effective=generated.clone()
            effective[:,0,:7]=first_arm
            effective[:,1:,:7]=self.ensemble.ensembled_actions
        command=effective[0,0].cpu().numpy().copy()
        return command,dict(prediction_refreshed=True,prediction_step=step,chunk_offset=0,
            anchor_q=state[0,:7].cpu().tolist(),head_output=output[0,0].cpu().tolist(),
            base_head_output=base[0,0].cpu().tolist(),arm_residual_rad=correction[0,0].cpu().tolist(),
            generated_chunk=generated[0].cpu().tolist(),effective_chunk=effective[0].cpu().tolist(),
            generated_head_chunk=output[0].cpu().tolist(),base_head_chunk=base[0].cpu().tolist(),
            residual_chunk=correction[0].cpu().tolist(),gripper_head='regression',
            aggregation='official ACTTemporalEnsembler, absolute arm commands only, coefficient0.01')
