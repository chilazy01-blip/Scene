"""Native Stretch names/units and complete collision bodies, no hidden reset."""
import numpy as np
import mujoco

NAMES = ('forward', 'turn', 'lift', 'arm_extend', 'wrist_yaw', 'grip', 'head_pan', 'head_tilt')


class Stretch:
    def __init__(self, model, binding):
        self.m, self.b = model, binding
        assert model.nu == 8 and tuple(model.actuator(i).name for i in range(8)) == NAMES
        assert model.nq == binding['nq'] and model.nv == binding['nv']
        assert list(model.geom_bodyid) == binding['geom_body']
        self.jq = lambda name: int(model.jnt_qposadr[model.joint(name).id])
        self.robot = set(binding['robot_body_ids'])
        self.hands = {model.body(n).id: (side, part)
                      for side in ('left', 'right')
                      for n, part in [('link_gripper_finger_' + side, 'link'), ('rubber_tip_' + side, 'pad')]}
        self.pad = [next(g for g in range(model.ngeom)
                         if model.geom_bodyid[g] == model.body('rubber_tip_' + side).id
                         and model.geom_type[g] == mujoco.mjtGeom.mjGEOM_CYLINDER
                         and model.geom_contype[g]) for side in ('left', 'right')]
        self.target = model.body('target').id
        self.support = model.body('support').id
        self.hand = model.body('link_gripper_slider').id

    def command(self, data, values, names=NAMES, units='native_m_rad'):
        if tuple(names) != NAMES or units != 'native_m_rad':
            raise ValueError('native_names_or_units')
        a = np.asarray(values, float)
        if a.shape != (8,) or not np.isfinite(a).all():
            raise ValueError('action_shape_or_nonfinite')
        limited = self.m.actuator_ctrllimited.astype(bool)
        if np.any(a[limited] < self.m.actuator_ctrlrange[limited, 0]) or np.any(a[limited] > self.m.actuator_ctrlrange[limited, 1]):
            raise ValueError('native_action_range')
        data.ctrl[:] = a

    def geometry(self, data):
        points = data.geom_xpos[self.pad].copy()
        axis = points[1] - points[0]
        distance = np.linalg.norm(axis)
        axis /= distance
        radius = []
        for g in self.pad:
            c = float(data.geom_xmat[g].reshape(3, 3)[:, 2] @ axis)
            radius.append(self.m.geom_size[g, 1] * abs(c) + self.m.geom_size[g, 0] * np.sqrt(max(0., 1-c*c)))
        return points.mean(axis=0), axis, float(distance - sum(radius))

    def place_for_planning(self, data, initial, station, x):
        data.qpos[:] = initial
        data.qvel[:] = 0
        q = self.b['base_qpos']
        data.qpos[q:q+3] = np.asarray(station['position']) + x[0] * np.asarray(station['tangent'])
        data.qpos[q+3:q+7] = [np.cos(station['yaw']/2), 0, 0, np.sin(station['yaw']/2)]
        for name, value in [('joint_lift', x[1]), ('joint_wrist_yaw', x[3]), ('joint_gripper_slide', x[4])]:
            data.qpos[self.jq(name)] = value
        for i in range(4):
            data.qpos[self.jq('joint_arm_l'+str(i))] = x[2]/4
        for side in ('left', 'right'):
            data.qpos[self.jq('joint_gripper_finger_'+side+'_open')] = 10*x[4]
            for axis in ('x', 'y'):
                data.qpos[self.jq('rubber_'+side+'_'+axis)] = 0
        mujoco.mj_forward(self.m, data)

    def contacts(self, data, actual_forces=True):
        rows = []
        for i, c in enumerate(data.contact):
            b1, b2 = map(int, self.m.geom_bodyid[[c.geom1, c.geom2]])
            if self.target not in (b1, b2):
                continue
            other = b2 if b1 == self.target else b1
            if other not in self.hands:
                continue
            force = np.zeros(6)
            if actual_forces:
                mujoco.mj_contactForce(self.m, data, i, force)
            side, part = self.hands[other]
            rows.append(dict(side=side, part=part, position=c.pos.tolist(),
                             normal_N=max(0., float(force[0])) if actual_forces else 1.,
                             depth_m=max(0., -float(c.dist)), normal=c.frame[:3].tolist()))
        return rows


def action(x):
    return np.array([0., 0., x[1], x[2], x[3], x[4], 0., 0.])
