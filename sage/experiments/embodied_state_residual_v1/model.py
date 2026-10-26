from collections import deque
import torch
from torch import nn
from sage.experiments.embodied_action_horizon_v1.model import forward as base_forward


class ArmResidual(nn.Module):
    def __init__(self, kind, state_stats):
        super().__init__()
        self.kind = kind
        self.register_buffer('mean', torch.tensor(state_stats['mean'], dtype=torch.float32))
        self.register_buffer('std', torch.tensor(state_stats['std'], dtype=torch.float32))
        if kind == 'linear':
            self.net = nn.Sequential(nn.Linear(18, 70))
        elif kind == 'mlp':
            self.net = nn.Sequential(nn.Linear(18, 128), nn.Tanh(), nn.Linear(128, 128), nn.Tanh(), nn.Linear(128, 70))
        else:
            raise ValueError(kind)
        nn.init.zeros_(self.net[-1].weight)
        nn.init.zeros_(self.net[-1].bias)

    def forward(self, raw_state):
        return self.net((raw_state.float()-self.mean)/self.std).reshape(-1, 10, 7)*.01


def corrected_output(base_output, raw_state, residual, codec):
    correction = residual(raw_state)
    output = base_output.clone()
    output[:, :, :7] += correction/codec.std[None, :, :7]
    return output, correction


class ResidualQueue:
    def __init__(self, base, pre, codec, residual, n_action_steps):
        assert n_action_steps in (1, 10)
        self.base, self.pre, self.codec, self.residual = base, pre, codec, residual
        self.n_action_steps = n_action_steps
        self.queue = deque()

    def select(self, sample, step):
        refreshed = not self.queue
        if refreshed:
            self.anchor = sample['observation.state'][:7].float().cpu().numpy().copy()
            self.base.eval(); self.residual.eval()
            with torch.inference_mode(), torch.autocast(device_type='cuda', enabled=False):
                raw_state = sample['observation.state'].float().to(self.codec.mean.device)[None]
                z = base_forward(self.base, self.pre(sample)).float()
                effective, correction = corrected_output(z, raw_state, self.residual, self.codec)
                commands = self.codec.decode(effective, raw_state[:, :7])[0].cpu().numpy()
                z, effective, correction = z[0].cpu().numpy(), effective[0].cpu().numpy(), correction[0].cpu().numpy()
            self.queue.extend((commands[k].copy(), effective[k].copy(), z[k].copy(), correction[k].copy(), k) for k in range(self.n_action_steps))
            self.prediction_step = step
        command, effective, base, correction, offset = self.queue.popleft()
        return command, dict(prediction_refreshed=refreshed, prediction_step=self.prediction_step, chunk_offset=offset,
            anchor_q=self.anchor.tolist(), head_output=effective.tolist(), base_head_output=base.tolist(),
            arm_residual_rad=correction.tolist(), gripper_head='regression')
