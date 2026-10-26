"""Physical-unit early-chunk MSE supplements the frozen regression objective."""
from sage.experiments.embodied_gripper_transition_v1.model import objective as base_objective


def objective(output, target_z, open_label, valid, edge, edge_weight, std, early_mse_weight):
    base, details = base_objective(output, target_z, open_label, valid, edge, 'regression', edge_weight)
    physical = (output[:, :10, :7] - target_z[:, :10, :7]) * std[None, :10, :7]
    mask = valid[:, :10, None]
    denominator = (mask.sum() * 7).clamp_min(1)
    auxiliary = ((physical / .01).square() * mask).sum() / denominator
    details['early_physical_mse'] = float(auxiliary.detach())
    return base + early_mse_weight * auxiliary, details
