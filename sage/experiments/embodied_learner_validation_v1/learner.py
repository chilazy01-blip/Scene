"""Unmodified official ACT with a bounded, explicitly configured development setup."""
import torch
from lerobot.configs.types import FeatureType, PolicyFeature
from lerobot.policies.act.configuration_act import ACTConfig
from lerobot.policies.act.modeling_act import ACTPolicy
from lerobot.policies.act.processor_act import make_act_pre_post_processors
from sage.experiments.embodied_control_diag_v1.precision import configure_numeric_execution
from .data import stats


def create(run, spec, pretrained=True):
    configure_numeric_execution()
    inputs = {'observation.state': PolicyFeature(FeatureType.STATE, (18,))}
    inputs.update({f'observation.images.{cam}': PolicyFeature(FeatureType.VISUAL, (3, 120, 160))
                   for cam in ['workspace', 'wrist']})
    config = ACTConfig(input_features=inputs,
        output_features={'action': PolicyFeature(FeatureType.ACTION, (8,))},
        chunk_size=spec['chunk_size'], n_action_steps=spec['n_action_steps'],
        dim_model=spec['dim_model'], dim_feedforward=spec['dim_feedforward'], n_heads=spec['n_heads'],
        n_encoder_layers=spec['n_encoder_layers'], n_decoder_layers=spec['n_decoder_layers'],
        use_vae=spec['use_vae'], dropout=spec['dropout'],
        pretrained_backbone_weights='ResNet18_Weights.IMAGENET1K_V1' if pretrained else None,
        optimizer_lr=spec['lr'], optimizer_lr_backbone=spec['lr_backbone'], device='cuda')
    policy = ACTPolicy(config).cuda()
    pre, post = make_act_pre_post_processors(config, stats(run))
    return policy, pre, post


@torch.no_grad()
def evaluate(policy, pre, post, samples, indices):
    policy.eval()
    normalized_sum = valid_count = 0
    arm, finger = [], []
    for start in range(0, len(indices), 8):
        raw = samples.batch(indices[start:start+8])
        batch = pre(raw)
        prediction = policy.predict_action_chunk(batch)
        decoded = post(prediction)
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
                all_finite=True, anchors=len(indices))
