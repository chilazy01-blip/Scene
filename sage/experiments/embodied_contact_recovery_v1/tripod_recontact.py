"""Measured geometric replanning of a missing tripod digit, without arm motion."""
import numpy as np
import mujoco
from .planned_tripod_r2 import FINGER_NAMES, GROUPS, CLOSED, contact_geometry, forbidden_robot_contacts


def plan_recontact(m, live, obj, maximum_joint_increment=.12):
    geometry = contact_geometry(m, live, obj)
    missing = [name for name in GROUPS if name not in geometry['digits']]
    qa = np.array([m.jnt_qposadr[m.joint('right_hand_' + name + '_joint').id] for name in FINGER_NAMES])
    joints = np.array([m.joint('right_hand_' + name + '_joint').id for name in FINGER_NAMES])
    d = mujoco.MjData(m); initial = live.qpos.copy(); target = initial[qa].copy()
    results = []
    for digit in missing:
        ids = GROUPS[digit]; direction = CLOSED[ids] / max(abs(CLOSED[ids]))
        found = False
        for distance in np.linspace(0., maximum_joint_increment, 49):
            candidate = np.clip(initial[qa[ids]] + distance * direction,
                                m.jnt_range[joints[ids], 0], m.jnt_range[joints[ids], 1])
            d.qpos[:] = initial; d.qvel[:] = 0.
            d.qpos[qa] = target; d.qpos[qa[ids]] = candidate
            mujoco.mj_forward(m, d)
            state = contact_geometry(m, d, obj)
            if state['forbidden'] or forbidden_robot_contacts(m, d, obj):
                break
            if digit in state['digits'] and state['maximum_object_penetration_m'] <= .002:
                target[ids] = candidate; found = True
                results.append({'digit': digit, 'increment_rad': float(distance), 'endpoint': state})
                break
        if not found:
            return {'valid': False, 'missing_digits': missing, 'reason': digit + '_no_collision_free_recontact'}
    d.qpos[:] = initial; d.qvel[:] = 0.; d.qpos[qa] = target
    mujoco.mj_forward(m, d); final = contact_geometry(m, d, obj)
    valid = final['digits'] == ['index', 'middle', 'thumb'] and final['rank'] == 6 and not forbidden_robot_contacts(m, d, obj)
    assert np.array_equal(live.qpos, initial)
    return {'valid': bool(valid), 'missing_digits': missing, 'finger_target_rad': target.tolist(),
            'digits': results, 'endpoint': final, 'maximum_joint_increment_rad': maximum_joint_increment,
            'scope': 'Scratch49point incremental finger closure with all other measured joints fixed; no dynamic guarantee.'}
