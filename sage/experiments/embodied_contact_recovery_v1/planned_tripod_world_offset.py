"""D measured-state tripod geometry planner and retained-actuator reference servo."""
import numpy as np
import mujoco
from scipy.spatial.transform import Rotation

FINGER_NAMES = ['thumb_0', 'thumb_1', 'thumb_2', 'index_0', 'index_1', 'middle_0', 'middle_1']
CLOSED = np.array([.8, -.9, -1.5, 1.4, 1.5, 1.4, 1.5])
GROUPS = {'thumb': [0, 1, 2], 'index': [3, 4], 'middle': [5, 6]}


def forbidden_robot_contacts(m, d, obj):
    root = m.body('base').id
    robot = set()
    for body in range(m.nbody):
        parent = body
        while parent and parent != root:
            parent = int(m.body_parentid[parent])
        if parent == root:
            robot.add(body)
    bad = []
    for ct in d.contact:
        if ct.dist >= 0:
            continue
        bodies = [int(m.geom_bodyid[g]) for g in [ct.geom1, ct.geom2]]
        if not any(body in robot for body in bodies):
            continue
        names = [m.body(body).name for body in bodies]
        geoms = [m.geom(g).name for g in [ct.geom1, ct.geom2]]
        foot = 'ground' in geoms and any('ankle_roll' in name for name in names)
        grasp = obj in bodies and any(name.startswith('right_hand') for name in names)
        if not (foot or grasp):
            bad.append(geoms)
    return bad


def hand_contacts(m, d, obj):
    contacts, forbidden = [], []
    for ct in d.contact:
        bs = [int(m.geom_bodyid[g]) for g in [ct.geom1, ct.geom2]]
        names = [m.body(b).name for b in bs]
        if ct.dist > 0:
            continue
        right = any('right_hand' in name for name in names)
        if right:
            (contacts if obj in bs else forbidden).append(ct)
    return contacts, forbidden


def contact_geometry(m, d, obj):
    contacts, forbidden = hand_contacts(m, d, obj)
    matrices, digits = [], set()
    for ct in contacts:
        x, y, z = ct.pos - d.xipos[obj]
        cross = np.array([[0., -z, y], [z, 0., -x], [-y, x, 0.]])
        frame = ct.frame.reshape(3, 3)
        axes = frame[:1].T if ct.dim == 1 else frame.T
        block = np.vstack([axes, cross @ axes / .037])
        if ct.dim > 3:
            torque = frame[:1].T if ct.dim == 4 else frame.T
            block = np.c_[block, np.vstack([np.zeros_like(torque), torque])]
        matrices.append(block)
        digits.update(m.body(int(m.geom_bodyid[g])).name.split('_')[2] for g in [ct.geom1, ct.geom2]
                      if m.body(int(m.geom_bodyid[g])).name.startswith('right_hand'))
    rank = int(np.linalg.matrix_rank(np.concatenate(matrices, axis=1), tol=1e-8)) if matrices else 0
    return {'digits': sorted(digits), 'rank': rank, 'contacts': len(contacts),
            'forbidden': len(forbidden), 'maximum_object_penetration_m': max([-float(ct.dist) for ct in contacts], default=0.)}


def plan(runner, template):
    m, live, ik = runner.model, runner.data, runner.ik
    d = mujoco.MjData(m)
    q0 = live.qpos.copy()
    palm, wrist = runner.palm_pose()
    goal = palm + wrist @ np.asarray(template['palm_local_offset_m']) + np.asarray(template.get('palm_world_offset_m', [0.,0.,0.]))
    desired_wrist = wrist @ Rotation.from_euler('x', template['palm_roll_change_deg'], degrees=True).as_matrix()
    arm, resid, rot_resid = ik.solve(live, goal, desired_wrist, iters=100)
    result = {'valid': False, 'arm_ik_residual_m': float(resid), 'arm_ik_rotation_residual_deg': float(rot_resid)}
    if resid > .003 or rot_resid > 1.:
        return result
    qa = np.array([m.jnt_qposadr[m.joint('right_hand_' + name + '_joint').id] for name in FINGER_NAMES])
    def evaluate(alphas):
        d.qpos[:] = q0
        d.qvel[:] = 0.
        d.qpos[ik.qpos_idx] = arm
        for digit, ids in GROUPS.items():
            d.qpos[qa[ids]] = CLOSED[ids] * alphas[digit]
        mujoco.mj_forward(m, d)
    fractions = {}
    for digit in GROUPS:
        low, high = .15, None
        for alpha in np.linspace(.15, 1., 35):
            alphas = {name: .15 for name in GROUPS}
            alphas[digit] = float(alpha)
            evaluate(alphas)
            contacts, _ = hand_contacts(m, d, runner.cyl_bid)
            found = any(any(m.body(int(m.geom_bodyid[g])).name.startswith('right_hand_' + digit + '_')
                            for g in [ct.geom1, ct.geom2]) for ct in contacts)
            if found:
                high = float(alpha)
                break
            low = float(alpha)
        if high is None:
            result['reason'] = digit + '_unreachable'
            return result
        for _ in range(9):
            mid = .5 * (low + high)
            alphas = {name: .15 for name in GROUPS}
            alphas[digit] = mid
            evaluate(alphas)
            contacts, _ = hand_contacts(m, d, runner.cyl_bid)
            found = any(any(m.body(int(m.geom_bodyid[g])).name.startswith('right_hand_' + digit + '_')
                            for g in [ct.geom1, ct.geom2]) for ct in contacts)
            if found: high = mid
            else: low = mid
        fractions[digit] = high + .001
    evaluate(fractions)
    endpoint = contact_geometry(m, d, runner.cyl_bid)
    target_q = d.qpos.copy()
    path_bad, path_pen = [], 0.
    for fraction in np.linspace(0., 1., 81):
        d.qpos[:] = q0
        d.qpos[ik.qpos_idx] += fraction * (target_q[ik.qpos_idx] - q0[ik.qpos_idx])
        d.qpos[qa] += fraction * (target_q[qa] - q0[qa])
        mujoco.mj_forward(m, d)
        contacts, forbidden = hand_contacts(m, d, runner.cyl_bid)
        path_pen = max(path_pen, max([-float(ct.dist) for ct in contacts], default=0.))
        all_forbidden = forbidden_robot_contacts(m, d, runner.cyl_bid)
        if forbidden or all_forbidden:
            path_bad.append(float(fraction))
    result.update(arm_target_rad=arm.tolist(), finger_target_rad=target_q[qa].tolist(),
                  initial_arm_rad=q0[ik.qpos_idx].tolist(), initial_finger_rad=q0[qa].tolist(),
                  planned_wrist_rotation=desired_wrist.tolist(), finger_first_contact_alpha=fractions,
                  endpoint=endpoint, path_forbidden_fractions=path_bad, path_max_object_penetration_m=path_pen)
    result['valid'] = bool(endpoint['digits'] == ['index', 'middle', 'thumb'] and endpoint['rank'] == 6
                           and endpoint['forbidden'] == 0 and not path_bad and path_pen <= .002)
    assert np.array_equal(live.qpos, q0), 'planner_modified_live_configuration'
    return result


class PlannedFingerServo:
    def __init__(self, m, free_speed=.20, contact_preload=.03):
        self.aids = np.array([m.actuator('right_hand_' + name + '_joint').id for name in FINGER_NAMES])
        self.qa = m.jnt_qposadr[m.actuator_trnid[self.aids, 0]]
        self.va = m.jnt_dofadr[m.actuator_trnid[self.aids, 0]]
        self.obj = m.body('red_block').id
        self.digits = [name.split('_')[0] for name in FINGER_NAMES]
        self.reference = {}
        self.free_speed, self.cap = free_speed, contact_preload
        self.released = False

    def release(self):
        self.released = True
        self.reference.clear()

    def reclose(self):
        self.released = False
        self.reference.clear()

    def apply(self, m, d, desired, desired_velocity=None):
        feedforward = np.zeros_like(desired) if desired_velocity is None else np.asarray(desired_velocity, float)
        assert feedforward.shape == np.asarray(desired).shape
        contacts, _ = hand_contacts(m, d, self.obj)
        touching = {m.body(int(m.geom_bodyid[g])).name.split('_')[2] for ct in contacts for g in [ct.geom1, ct.geom2]
                    if m.body(int(m.geom_bodyid[g])).name.startswith('right_hand')}
        rows = []
        for i, (a, qa, va, digit) in enumerate(zip(self.aids, self.qa, self.va, self.digits)):
            q, velocity = float(d.qpos[qa]), float(d.qvel[va])
            if not self.released and digit in touching and int(a) not in self.reference:
                self.reference[int(a)] = q + np.sign(CLOSED[i]) * self.cap
            if int(a) in self.reference:
                target = np.clip(self.reference[int(a)], q - self.cap, q + self.cap)
                mode = 2
            else:
                goal_velocity = float(np.clip(feedforward[i] + 3. * (desired[i] - q), -self.free_speed, self.free_speed))
                if abs(desired[i] - q) < 1e-5 and abs(feedforward[i]) < 1e-12:
                    goal_velocity = 0.
                # Retained actuator equation, with a desired free-motion speed.
                damping = m.dof_damping[va] - m.actuator_biasprm[a, 2]
                torque = np.sign(goal_velocity) * m.dof_frictionloss[va] + damping * goal_velocity + d.qfrc_bias[va]
                target = q + torque / m.actuator_gainprm[a, 0]
                mode = 0
            d.ctrl[a] = np.clip(target, *m.actuator_ctrlrange[a])
            rows.append([a, mode, q, velocity, float(desired[i]), float(d.ctrl[a]), float(digit in touching)])
        return np.asarray(rows)
