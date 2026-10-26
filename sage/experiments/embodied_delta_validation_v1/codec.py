"""Joint deltas use one unnormalized observation anchor for an entire chunk."""
from collections import deque
import torch


def delta_batch(raw):
    result = dict(raw)
    result['action'] = raw['action'].clone()
    result['action'][..., :7] -= raw['observation.state'][:, None, :7]
    return result


def restore(delta, anchor):
    result = delta.clone()
    anchor = torch.as_tensor(anchor, dtype=result.dtype, device=result.device)
    result[..., :7] += anchor[:, None, :7]
    return result


class AnchoredQueue:
    def __init__(self, policy, pre, post):
        assert policy.config.chunk_size == policy.config.n_action_steps == 10
        self.policy, self.pre, self.post = policy, pre, post
        self.pending = deque()
        self.anchor = None
        self.prediction_step = None

    @torch.inference_mode()
    def select(self, sample, step):
        refreshed = not self.pending
        if refreshed:
            assert sample is not None
            self.anchor = sample['observation.state'][:7].detach().cpu().clone()
            self.prediction_step = step
            chunk = self.policy.predict_action_chunk(self.pre(sample))
            delta = self.post(chunk)
            absolute = restore(delta, self.anchor[None])
            assert absolute.shape == (1, 10, 8) and torch.isfinite(absolute).all()
            for offset in range(10):
                self.pending.append((absolute[0, offset].cpu().numpy().copy(),
                                     delta[0, offset].cpu().numpy().copy(), offset))
        absolute, delta, offset = self.pending.popleft()
        return absolute, dict(prediction_step=self.prediction_step,
                              anchor_q=self.anchor.tolist(), chunk_offset=offset,
                              delta_action=delta.tolist(), refreshed=refreshed)
