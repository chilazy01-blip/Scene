"""Reuse the frozen official architecture; translate only target and output joints."""
import torch
from sage.experiments.embodied_learner_validation_v1.learner import create
from .codec import delta_batch, restore


@torch.no_grad()
def evaluate(policy, pre, post, samples, indices):
    policy.eval()
    normalized_sum = valid_count = 0
    arm, finger = [], []
    for start in range(0, len(indices), 8):
        raw = samples.batch(indices[start:start+8])
        anchor = raw['observation.state'][:, :7].clone()
        batch = pre(delta_batch(raw))
        prediction = policy.predict_action_chunk(batch)
        decoded = restore(post(prediction), anchor)
        mask = ~batch['action_is_pad']
        assert torch.isfinite(prediction).all() and torch.isfinite(decoded).all()
        normalized_sum += float(((prediction-batch['action']).abs()*mask.unsqueeze(-1)).sum())
        valid_count += int(mask.sum())*8
        physical = (decoded-raw['action'].cpu()).abs()
        keep = mask.cpu()
        arm.append(physical[:, :, :7][keep].reshape(-1))
        finger.append(physical[:, :, 7][keep])
    arm = torch.cat(arm); finger = torch.cat(finger)
    return dict(normalized_l1=normalized_sum/valid_count, valid_action_components=valid_count,
                joint_mae_rad=float(arm.mean()), joint_p95_rad=float(torch.quantile(arm, .95)),
                finger_mae_m=float(finger.mean()), finger_p95_m=float(torch.quantile(finger, .95)),
                all_finite=True, anchors=len(indices), normalized_loss_cross_representation_comparable=False)
