"""Crop learned decoder queries without changing the official ACT implementation."""
from pathlib import Path
import torch
from torch import nn
from safetensors.torch import load_file
from sage.experiments.embodied_gripper_transition_v1.model import (
    load_policy as load_full_policy, forward, decode, GripperQueue)
from sage.experiments.embodied_action_delta_v1.codec import ActionCodec
from sage.experiments.embodied_arm_precision_v1.objective import objective as full_objective


class HorizonCodec(ActionCodec):
    def __init__(self, record, device='cpu', horizon=40):
        super().__init__(record, device)
        if horizon not in (10, 40):
            raise ValueError(horizon)
        self.mean = self.mean[:horizon]
        self.std = self.std[:horizon]


def load_policy(source, stats, kind='regression', checkpoint=None, horizon=40,
                initial_checkpoint=None, device='cuda'):
    if kind != 'regression' or horizon not in (10, 40):
        raise ValueError((kind, horizon))
    policy = load_full_policy(source, stats, kind, initial_checkpoint, device)
    assert policy.config.chunk_size == 40
    if horizon == 10:
        weight = policy.model.decoder_pos_embed.weight[:10].detach().clone()
        policy.model.decoder_pos_embed = nn.Embedding.from_pretrained(weight, freeze=False)
        policy.config.chunk_size = 10
        policy.config.n_action_steps = 1
    if checkpoint is not None:
        policy.load_state_dict(load_file(str(Path(checkpoint)/'model.safetensors')), strict=True)
    return policy.to(device)


def objective(output, target_z, open_label, valid, edge, edge_weight, std,
              early_mse_weight, loss_horizon):
    if loss_horizon not in (10, 40) or loss_horizon > output.shape[1]:
        raise ValueError(loss_horizon)
    # Slice before reduction so both short objectives use the same denominator.
    return full_objective(output[:, :loss_horizon], target_z[:, :loss_horizon],
                          open_label[:, :loss_horizon], valid[:, :loss_horizon],
                          edge[:, :loss_horizon], edge_weight, std[:loss_horizon],
                          early_mse_weight)
