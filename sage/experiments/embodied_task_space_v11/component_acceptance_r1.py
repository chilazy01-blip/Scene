"""Prepared stricter acceptance: preserve qualified endpoint components.

A contact-failing phase may still have qualified palm or hand endpoints. This
candidate rule prevents trading those away for another phase's improvement.
No solver, robot evaluation, method admission, or success claim is provided.
"""
import numpy as np
from sage.experiments.embodied_task_space_v5.minimax_acceptance_r1 import accept_step as original_accept_step


def accept_step(before, after, hard_residual, tolerance=1e-10):
    decision = original_accept_step(before, after, hard_residual, tolerance)
    if not decision['accepted']:
        return decision
    old = np.asarray(before['ends'], dtype=float)
    new = np.asarray(after['ends'], dtype=float)
    lost = np.argwhere((old <= tolerance) & (new > tolerance))
    if len(lost):
        return dict(accepted=False, reason='qualified_endpoint_component_regression',
                    original_decision=decision,
                    lost_endpoint_components=[dict(
                        stage=before['meta']['phases'][int(i)]['stage'],
                        component=('palm', 'hand')[int(j)],
                        before_excess=float(old[i, j]), after_excess=float(new[i, j]))
                        for i, j in lost])
    return decision
