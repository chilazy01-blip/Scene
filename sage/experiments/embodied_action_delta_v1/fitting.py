"""Frozen descriptive and admission metrics on a single training demonstration."""
import numpy as np


def measure(predicted, truth, phases, gate):
    first = predicted[:, 0]
    error = np.abs(first.astype('f8') - truth.astype('f8'))
    rows = []
    for name in dict.fromkeys(phases.tolist()):
        d = error[phases == name]
        rows.append(dict(phase=name, frames=len(d), arm_mae_rad=float(d[:, :7].mean()),
                         arm_p95_max_rad=float(np.quantile(d[:, :7].max(axis=1), .95)),
                         arm_max_rad=float(d[:, :7].max()), gripper_mae_m=float(d[:, 7].mean()),
                         gripper_p95_m=float(np.quantile(d[:, 7], .95)), gripper_max_m=float(d[:, 7].max())))
    ratios = {}
    for name in gate['key_phases']:
        row = next(x for x in rows if x['phase'] == name)
        for key, limit in [('arm_mae_rad', 'phase_arm_mae_rad'), ('arm_p95_max_rad', 'phase_arm_p95_max_rad'),
                           ('gripper_mae_m', 'phase_gripper_mae_m'), ('gripper_p95_m', 'phase_gripper_p95_m')]:
            ratios[name + '/' + key] = row[key] / gate[limit]
    transitions = np.flatnonzero(np.abs(np.diff(truth[:, 7])) > .002) + 1
    edge = np.unique(np.concatenate([np.arange(max(0, x - gate['transition_window_frames']),
                                             min(len(truth), x + gate['transition_window_frames'] + 1)) for x in transitions]))
    edge_error = float(error[edge, 7].max())
    ratios['transition_gripper_max_m'] = edge_error / gate['transition_gripper_max_m']
    raw = np.arange(len(truth))[:, None] + np.arange(10)[None, :]
    valid = raw < len(truth)
    future = truth[np.minimum(raw, len(truth) - 1)]
    first10_error = np.abs(predicted[:, :10, :7].astype('f8') - future[:, :, :7])
    first10_mae = float(first10_error[valid].mean())
    ratios['first10_arm_mae_rad'] = first10_mae / gate['first10_arm_mae_rad']
    return dict(first_action_arm_mae_rad=float(error[:, :7].mean()), first_action_arm_max_rad=float(error[:, :7].max()),
                gripper_mae_m=float(error[:, 7].mean()), gripper_max_m=float(error[:, 7].max()),
                first10_arm_mae_rad=first10_mae, transition_gripper_max_m=edge_error,
                transition_frames=transitions.tolist(), phase_metrics=rows, gate_ratios=ratios,
                gate_score=max(ratios.values()), gate_passed=bool(max(ratios.values()) <= 1.))
