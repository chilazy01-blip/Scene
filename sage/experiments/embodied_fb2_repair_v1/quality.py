"""Consume every declared quality limit, including explicitly framed root drift."""
import numpy as np
from sage.experiments.embodied_expert_task_v2.physical_quality_r3 import measure as native_measure
from sage.experiments.embodied_expert_task_v2.physical_quality_r3 import terminal as native_terminal

CONSUMED_LIMITS = {
    'max_tilt_rad','max_xy_drift_m','max_z_drift_m','min_height_m','max_penetration_m',
    'joint_limit_tolerance_rad','max_ground_gap_seconds','max_generalized_speed_sanity',
    'max_arm_speed_rps','max_hand_speed_rps','final_window_seconds',
    'min_final_both_feet_ground_fraction','max_final_slip_mps',
    'max_final_base_linear_speed_mps','max_final_base_angular_speed_rps',
    'max_final_lower_tracking_error_rad','max_final_upper_tracking_error_rad',
    'max_final_hand_tracking_error_rad'}


def validate_limits(limits):
    if set(limits) != CONSUMED_LIMITS:
        raise ValueError('unknown_or_missing_quality_limits:'+str(set(limits)^CONSUMED_LIMITS))
    if not all(np.isfinite(v) and v>=0 for v in limits.values()):
        raise ValueError('invalid_quality_limit')


def measure(model,data,names,roles,limits,qpos_by_pin,command,root_reference):
    validate_limits(limits)
    r = native_measure(model,data,names,roles,limits,qpos_by_pin,command)
    reference = np.asarray(root_reference)
    if reference.shape!=(3,) or not np.isfinite(reference).all():
        raise ValueError('explicit_root_reference_required')
    r['root_xy_error'] = float(np.linalg.norm(data.qpos[:2]-reference[:2]))
    r['root_z_error'] = float(abs(data.qpos[2]-reference[2]))
    if r['root_xy_error']>limits['max_xy_drift_m']:r['violations'].append('root_xy_tracking')
    if r['root_z_error']>limits['max_z_drift_m']:r['violations'].append('root_z_tracking')
    r['violations'] = sorted(set(r['violations']))
    return r


def terminal(rows,limits):
    validate_limits(limits)
    return native_terminal(rows,limits)
