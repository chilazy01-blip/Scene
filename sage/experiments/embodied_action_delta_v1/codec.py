"""Per-horizon action coordinates. Delta chunks share one observation anchor."""
from collections import deque
import numpy as np
import torch


class ActionCodec:
    def __init__(self, record, device='cpu'):
        self.representation = record['representation']
        if self.representation not in ('absolute', 'delta'):
            raise ValueError(self.representation)
        self.mean = torch.tensor(record['mean'], dtype=torch.float32, device=device)
        self.std = torch.tensor(record['std'], dtype=torch.float32, device=device)
        assert self.mean.shape == self.std.shape == (40, 8)
        assert torch.isfinite(self.mean).all() and torch.isfinite(self.std).all() and (self.std > 0).all()

    def encode(self, absolute, anchor):
        values = absolute.float().clone()
        if self.representation == 'delta':
            values[..., :7] -= anchor.float()[:, None, :7]
        return (values - self.mean) / self.std

    def decode(self, normalized, anchor):
        values = normalized.float() * self.std + self.mean
        if self.representation == 'delta':
            values = values.clone()
            values[..., :7] += anchor.float()[:, None, :7]
        return values


class AnchoredQueue:
    """Decode once at prediction time, then consume fixed absolute targets."""
    def __init__(self, policy, pre, codec, n_action_steps):
        if n_action_steps not in (1, 10):
            raise ValueError(n_action_steps)
        self.policy, self.pre, self.codec = policy, pre, codec
        self.n_action_steps = n_action_steps
        self.queue = deque()
        self.anchor = None
        self.prediction_step = None

    def select(self, sample, step):
        refreshed = not self.queue
        if refreshed:
            self.anchor = sample['observation.state'][:7].float().cpu().numpy().copy()
            batch = self.pre(sample)
            anchor = torch.from_numpy(self.anchor).to(self.codec.mean.device).unsqueeze(0)
            with torch.inference_mode(), torch.autocast(device_type='cuda', enabled=False):
                normalized = self.policy.predict_action_chunk(batch).float()
                absolute = self.codec.decode(normalized, anchor)[0].cpu().numpy()
            z = normalized[0].cpu().numpy()
            self.queue.extend((absolute[k].copy(), z[k].copy(), k) for k in range(self.n_action_steps))
            self.prediction_step = step
        absolute, normalized, offset = self.queue.popleft()
        return absolute, dict(prediction_refreshed=refreshed, prediction_step=self.prediction_step,
                              chunk_offset=offset, anchor_q=self.anchor.tolist(), normalized_action=normalized.tolist())
