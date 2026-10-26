from collections import deque
import numpy as np
import torch
from torch import nn
from sage.experiments.embodied_action_horizon_v1.model import forward
from sage.experiments.embodied_grip_composition_v1.model import compose, load_components


class HistoryCorrection(nn.Module):
    """Five observed robot states to an arm residual; no time or phase input."""
    def __init__(self, stats):
        super().__init__()
        self.register_buffer('mean', torch.tensor(stats['mean'], dtype=torch.float32))
        self.register_buffer('std', torch.tensor(stats['std'], dtype=torch.float32))
        self.net = nn.Sequential(nn.Linear(90, 256), nn.Tanh(),
                                 nn.Linear(256, 256), nn.Tanh(), nn.Linear(256, 70))
        nn.init.zeros_(self.net[-1].weight)
        nn.init.zeros_(self.net[-1].bias)

    def forward(self, history):
        normalized = (history.float() - self.mean) / self.std
        return self.net(normalized.flatten(1)).reshape(-1, 10, 7) * .01


def augment_history(history, tangent, q_noise, v_noise, enabled):
    from sage.experiments.embodied_recovery_arm_v1.model import augment_state
    current = history[:, -1]
    offset = augment_state(current, tangent, q_noise, v_noise, enabled) - current
    return history + offset[:, None]


def load_history_policy(freeze, composition_freeze):
    from pathlib import Path
    from safetensors.torch import load_file
    from sage.experiments.embodied_scene_bridge.contracts import read, digest
    assert digest(composition_freeze) == freeze['composition_freezes'][composition_freeze]
    base, arm, codec = load_components(read(composition_freeze))
    assert digest(freeze['state_stats_file']) == freeze['state_stats_sha256']
    point = Path(freeze['selected']['path'])
    for relative, sha in freeze['files'].items():
        assert digest(point / relative) == sha
    correction = HistoryCorrection(read(freeze['state_stats_file'])).cuda()
    correction.load_state_dict(load_file(str(point / 'history.safetensors')))
    return base.eval(), arm.eval(), correction.eval(), codec


class HistoryQueue:
    def __init__(self, base, pre, codec, arm, correction, kind, n_action_steps=10):
        if n_action_steps != 10:
            raise ValueError(n_action_steps)
        self.base, self.pre, self.codec = base, pre, codec
        self.arm, self.correction, self.kind = arm, correction, kind
        self.history = deque(maxlen=5)
        self.queue = deque()

    def select(self, sample, step):
        observed = sample['observation.state'].float().cpu().numpy().copy()
        if not self.history:
            self.history.extend(observed.copy() for _ in range(5))
        else:
            self.history.append(observed)
        refreshed = not self.queue
        if refreshed:
            with torch.inference_mode(), torch.autocast(device_type='cuda', enabled=False):
                history = torch.tensor(np.stack(self.history), device=self.codec.mean.device)[None]
                state = history[:, -1]
                base_output = forward(self.base, self.pre(sample)).float()
                baseline = self.arm(state)
                residual = self.correction(history)
                delta = baseline + residual
                commands, effective, prefix, logits = compose(base_output, delta, state, self.codec, self.kind)
                arrays = [x[0].cpu().numpy() for x in
                          [commands, effective, prefix, delta, logits, baseline, residual]]
                self.anchor = state[0, :7].cpu().tolist()
                self.prediction_history = history[0].cpu().tolist()
            arrays[0] = arrays[0].astype('f8')
            arrays[0][:, 7] = np.where(arrays[4] >= 0, .04, 0.)
            self.queue.extend((*[x[k].copy() for x in arrays], k) for k in range(10))
            self.prediction_step = step
        command, effective, base_output, delta, logit, baseline, residual, offset = self.queue.popleft()
        return command, dict(prediction_refreshed=refreshed, prediction_step=self.prediction_step,
            chunk_offset=offset, anchor_q=self.anchor, head_output=effective.tolist(),
            base_head_output=base_output.tolist(), neural_arm_delta_rad=delta.tolist(),
            baseline_arm_delta_rad=baseline.tolist(), history_residual_rad=residual.tolist(),
            prediction_history=self.prediction_history, observation_proprio=observed.tolist(),
            gripper_logit=float(logit), gripper_source_kind=self.kind,
            uses_phase_time_or_expert_plan=False)
