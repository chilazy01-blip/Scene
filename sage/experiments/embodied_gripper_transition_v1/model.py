"""Separate arm and gripper objectives without modifying official ACT sources."""
from collections import deque
from pathlib import Path
import torch
from torch import nn
from torch.nn import functional as F
from safetensors.torch import load_file
from lerobot.policies.act.modeling_act import ACTPolicy
from lerobot.utils.constants import OBS_IMAGES
from sage.experiments.embodied_action_delta_v1.codec import ActionCodec


class SeparateHeads(nn.Module):
    def __init__(self, source, stats, kind):
        super().__init__()
        if kind not in ('regression', 'binary'):
            raise ValueError(kind)
        self.kind = kind
        self.arm = nn.Linear(source.in_features, 7)
        self.gripper = nn.Linear(source.in_features, 1)
        with torch.no_grad():
            self.arm.weight.copy_(source.weight[:7]); self.arm.bias.copy_(source.bias[:7])
            self.gripper.weight.copy_(source.weight[7:]); self.gripper.bias.copy_(source.bias[7:])
        self.register_buffer('grip_mean', torch.tensor(stats['mean'], dtype=torch.float32)[:, 7:].contiguous())
        self.register_buffer('grip_std', torch.tensor(stats['std'], dtype=torch.float32)[:, 7:].contiguous())

    def forward(self, features):
        gripper = self.gripper(features)
        if self.kind == 'binary':
            gripper = 2. * (gripper * self.grip_std + self.grip_mean - .02) / .02
        return torch.cat([self.arm(features), gripper], dim=-1)


def load_policy(source, stats, kind, checkpoint=None, device='cuda'):
    policy = ACTPolicy.from_pretrained(Path(source))
    assert not policy.config.use_vae and policy.config.dropout == 0
    policy.model.action_head = SeparateHeads(policy.model.action_head, stats, kind)
    if checkpoint is not None:
        policy.load_state_dict(load_file(str(Path(checkpoint)/'model.safetensors')), strict=True)
    return policy.to(device)


def forward(policy, batch):
    batch = dict(batch)
    batch[OBS_IMAGES] = [batch[key] for key in policy.config.image_features]
    return policy.model(batch)[0]


def objective(output, target_z, open_label, valid, edge, kind, edge_weight):
    arm = (output[..., :7] - target_z[..., :7]).abs().sum(dim=-1)
    if kind == 'regression':
        grip = (output[..., 7] - target_z[..., 7]).abs()
    elif kind == 'binary':
        grip = F.binary_cross_entropy_with_logits(output[..., 7], open_label, reduction='none')
    else:
        raise ValueError(kind)
    weights = 1. + (edge_weight - 1.) * edge
    denominator = output.shape[0] * output.shape[1] * 8
    arm_loss = (arm * valid).sum()/denominator
    gripper_loss = (grip * weights * valid).sum()/denominator
    return arm_loss + gripper_loss, dict(arm_loss=float(arm_loss.detach()), gripper_loss=float(gripper_loss.detach()))


def decode(output, anchor, codec, kind):
    absolute = codec.decode(output, anchor)
    if kind == 'binary':
        absolute = absolute.clone()
        absolute[..., 7] = torch.where(output[..., 7] >= 0, .04, 0.)
    return absolute


class GripperQueue:
    """Decode arm anchor and binary decision once, then consume the fixed chunk."""
    def __init__(self, policy, pre, codec, kind, n_action_steps):
        assert n_action_steps in (1, 10)
        self.policy, self.pre, self.codec, self.kind = policy, pre, codec, kind
        self.n_action_steps = n_action_steps
        self.queue = deque()

    def select(self, sample, step):
        refreshed = not self.queue
        if refreshed:
            self.anchor = sample['observation.state'][:7].float().cpu().numpy().copy()
            batch = self.pre(sample)
            anchor = torch.tensor(self.anchor, device=self.codec.mean.device).unsqueeze(0)
            self.policy.eval()
            with torch.inference_mode(), torch.autocast(device_type='cuda', enabled=False):
                outputs = forward(self.policy, batch).float()
                commands = decode(outputs, anchor, self.codec, self.kind)[0].cpu().numpy()
            outputs = outputs[0].cpu().numpy()
            self.queue.extend((commands[k].copy(), outputs[k].copy(), k) for k in range(self.n_action_steps))
            self.prediction_step = step
        command, output, offset = self.queue.popleft()
        return command, dict(prediction_refreshed=refreshed, prediction_step=self.prediction_step, chunk_offset=offset,
            anchor_q=self.anchor.tolist(), head_output=output.tolist(), gripper_head=self.kind)
