"""Explicit engineering gates; contact geometry and physical truth stay separate."""
import numpy as np


def relative_pose(hand_position, hand_rotation, com_position, object_rotation):
    h = np.asarray(hand_rotation).reshape(3, 3)
    return h.T @ (np.asarray(com_position) - hand_position), h.T @ np.asarray(object_rotation).reshape(3, 3)


def pose_drift(reference, current):
    p0, r0 = reference
    p1, r1 = current
    angle = np.arccos(np.clip((np.trace(r0.T @ r1) - 1) / 2, -1, 1))
    return float(np.linalg.norm(p1 - p0)), float(angle)


def contact_quality(contacts, com_world, object_rotation, mass, friction, nominal_force=5.):
    """Contacts have side, part, normal_N, position; COM is inertial, not body origin.

    Lever-arm estimate is diagnostic, not force closure. The scalar friction
    margin assumes opposing horizontal normals and equal nominal finger loads.
    """
    result = {}
    centers = []
    for side in ('left', 'right'):
        rows = [c for c in contacts if c['side'] == side and c['normal_N'] > 0]
        total = sum(c['normal_N'] for c in rows)
        pads = sum(c['normal_N'] for c in rows if c['part'] == 'pad')
        center = np.average([c['position'] for c in rows], axis=0,
                            weights=[c['normal_N'] for c in rows]) if rows else None
        centers.append(center)
        result[side] = dict(force_N=float(total), pad_fraction=float(pads / total) if total else 0.,
                            com_local_m=None if center is None else ((center - com_world) @ object_rotation).tolist(),
                            parts=sorted({c['part'] for c in rows}))
    offset = None
    if all(c is not None for c in centers):
        midpoint = (centers[0] + centers[1]) / 2
        axis = centers[1] - centers[0]
        axis /= max(np.linalg.norm(axis), 1e-12)
        lever = midpoint - com_world
        offset = float(np.linalg.norm(lever - axis * np.dot(axis, lever)))
    result.update(contact_com_offset_m=offset,
                  gravity_force_N=float(mass * 9.81),
                  nominal_friction_margin_N=float(2 * friction * nominal_force - mass * 9.81),
                  min_equal_squeeze_N=float(mass * 9.81 / (2 * friction)),
                  gravity_moment_Nm=None if offset is None else float(mass * 9.81 * offset),
                  interpretation='diagnostic prior; no force-closure or hardware certificate')
    return result


def contact_gate(quality, limits):
    reasons = []
    for side in ('left', 'right'):
        if not np.isfinite(quality[side]['force_N']) or quality[side]['force_N'] < limits['min_each_side_force_N']:
            reasons.append(side + '_contact_missing')
        if not np.isfinite(quality[side]['pad_fraction']) or quality[side]['pad_fraction'] < limits['min_pad_force_fraction']:
            reasons.append(side + '_pad_contact_insufficient')
    offset = quality['contact_com_offset_m']
    if offset is None or not np.isfinite(offset) or offset > limits['max_contact_com_offset_m']:
        reasons.append('contact_off_center_of_mass')
    return reasons


def test_lift_gate(samples, limits, dt):
    """Require a complete contiguous tail; a momentary zero support force cannot pass."""
    count = round(limits['window_seconds'] / dt)
    if len(samples) < count:
        return ['incomplete_test_lift_window']
    reasons = set()
    for s in samples[-count:]:
        reasons.update(contact_gate(s['contact_quality'], limits))
        for key, bound, minimum in (
            ('relative_slip_m', limits['max_relative_slip_m'], False),
            ('relative_rotation_rad', limits['max_relative_rotation_rad'], False),
            ('object_lift_m', limits['min_test_lift_m'], True),
            ('support_clearance_m', limits['min_clearance_m'], True),
            ('support_force_N', limits['max_support_force_N'], False),
        ):
            value = s[key]
            if not np.isfinite(value) or (value < bound if minimum else value > bound):
                reasons.add(key)
    return sorted(reasons)


class TaskGate:
    """Transport can only follow a successful trial-lift hold in this attempt."""
    def __init__(self):
        self.test_lift_passed = False
        self.failed = False

    def finish_test_lift(self, samples, limits, dt):
        reasons = test_lift_gate(samples, limits, dt)
        self.failed |= bool(reasons)
        self.test_lift_passed = not self.failed
        return reasons

    def require_transport(self):
        if self.failed or not self.test_lift_passed:
            raise ValueError('transport_requires_passed_test_lift')
