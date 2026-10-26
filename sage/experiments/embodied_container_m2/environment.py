"""Panda control inherited unchanged; containment and bottom support audited at 1 kHz."""
from copy import deepcopy
import mujoco
import numpy as np
from sage.experiments.embodied_planner_m2_v2.environment import ExecutionEnvironment as BaseEnvironment, ForbiddenContact
from sage.experiments.embodied_scene_bridge.environment import support_probe
from .contacts import ContactPolicy
from .cavity import bottom_probe, containment


class ExecutionEnvironment(BaseEnvironment):
    def __init__(self, package):
        super().__init__(package)
        if self.task['task'] != 'place_in_container':
            raise ValueError('container_task_required')
        self.contact_policy = ContactPolicy(self.model, self.owner, self.task)

    def reset(self, seed, jitter=True):
        mujoco.mj_resetData(self.model, self.data)
        self.data.qpos[self.ctrl.qi] = self.ctrl.qhome
        self.data.qpos[self.qi[-2:]] = [.04, -.04]
        self.start = np.asarray(self.task['start']).copy()
        if jitter:
            self.start[:2] += np.random.default_rng(seed).uniform(-.02, .02, 2)
        self.data.qpos[self.target_qi:self.target_qi+3] = self.start
        self.data.qpos[self.target_qi+3:self.target_qi+7] = self.task['target_quat']
        mujoco.mj_forward(self.model, self.data)
        support_probe(self.model, self.data, self.task, self.start)
        self.reset_bottom_probe = bottom_probe(self.model, self.data, self.task)
        self.metrics = dict(max_lift_m=0., bilateral_s=0., stable_s=0., floor_contact=False,
                            forbidden_contact=False, robot_self_collision=False,
                            goal_xy_error_m=float(np.linalg.norm(self.start[:2]-self.task['goal'][:2])),
                            inside_container=False, max_bilateral_continuous_s=0.)
        self.native_steps = 0
        self.ready = True
        self.audit_rows, self.contact_rows, self.container_rows = [], [], []
        self.bilateral_streak = 0.
        self.last_pad_forces = [0., 0.]
        self.last_finger_contact = False
        self.last_support_force = 0.
        self.max_penetration = 0.
        self.forbidden_pairs = {}
        return self.observe()

    def _audit(self):
        m, d, t = self.model, self.data, self.task
        pads = [0., 0.]
        finger = False
        support = 0.
        for i, contact in enumerate(d.contact):
            ids = [int(contact.geom1), int(contact.geom2)]
            own = [self.owner[j] for j in ids]
            names = [m.geom(j).name for j in ids]
            force = np.zeros(6)
            mujoco.mj_contactForce(m, d, i, force)
            self.contact_rows.append([float(d.time), float(d.time-.001), *ids, float(contact.dist), *force.tolist()])
            penetration = max(0., -float(contact.dist))
            if t['target_body'] in own:
                target_index = own.index(t['target_body'])
                other = 1-target_index
                for gid, name in zip(ids, names):
                    if gid in self.contact_policy.fingers:
                        finger = True
                        pads[int(name[6])-1] += max(0., float(force[0]))
                if names[other] == 'floor':
                    self.metrics['floor_contact'] = True
                if ids[other] in self.contact_policy.bottom:
                    normal = contact.frame[2] * (1 if target_index == 1 else -1)
                    if normal > .5:
                        support += max(0., float(force[0]*normal))
            if not self.contact_policy.allowed(*ids):
                self.max_penetration = max(self.max_penetration, penetration)
                if penetration > t['success']['max_forbidden_penetration_m']:
                    pair = '|'.join(sorted(names))
                    self.forbidden_pairs[pair] = self.forbidden_pairs.get(pair, 0)+1
                    self.metrics['forbidden_contact'] = True
                    if own == ['base', 'base']:
                        self.metrics['robot_self_collision'] = True
        self.last_pad_forces = pads
        self.last_finger_contact = finger
        self.last_support_force = support
        bilateral = min(pads) > t['success']['min_bilateral_force_n']
        self.bilateral_streak = self.bilateral_streak+.001 if bilateral else 0.
        self.metrics['bilateral_s'] += .001 if bilateral else 0.
        self.metrics['max_bilateral_continuous_s'] = max(self.metrics['max_bilateral_continuous_s'], self.bilateral_streak)
        pos = d.qpos[self.target_qi:self.target_qi+3]
        quat = d.qpos[self.target_qi+3:self.target_qi+7]
        speed = float(np.linalg.norm(d.qvel[self.target_vi:self.target_vi+3]))
        angular = float(np.linalg.norm(d.qvel[self.target_vi+3:self.target_vi+6]))
        goal_error = float(np.linalg.norm(pos[:2]-t['goal'][:2]))
        inside = containment(t, pos, quat)
        stable = (inside['inside'] and support > 0 and not finger
                  and speed < t['success']['max_speed_m_s']
                  and angular < t['success']['max_angular_speed_rad_s']
                  and goal_error < t['success']['goal_xy_tolerance_m'])
        self.metrics['stable_s'] = self.metrics['stable_s']+.001 if stable else 0.
        self.metrics['max_lift_m'] = max(self.metrics['max_lift_m'], float(pos[2]-self.start[2]))
        self.metrics.update(goal_xy_error_m=goal_error, speed_m_s=speed, angular_speed_rad_s=angular,
                            support_force_n=support, finger_contact=finger, inside_container=inside['inside'],
                            side_margin_m=inside['side_margin_m'], rim_margin_m=inside['rim_margin_m'],
                            bottom_margin_m=inside['bottom_margin_m'])
        self.audit_rows.append([float(d.time), *pos.tolist(), *pads, support, float(finger),
                               goal_error, self.metrics['stable_s'], self.max_penetration])
        self.container_rows.append([float(d.time), float(inside['inside']), inside['side_margin_m'],
                                    inside['rim_margin_m'], inside['bottom_margin_m'], support])
        if self.metrics['forbidden_contact']:
            raise ForbiddenContact('forbidden_contact:' + ','.join(self.forbidden_pairs))

    def evaluate(self):
        v, t = self.metrics, self.task['success']
        success = (v['max_lift_m'] >= t['min_lift_m']
                   and v['max_bilateral_continuous_s'] >= t['min_bilateral_s']
                   and v['stable_s'] >= t['stable_s'] and v['inside_container']
                   and v['goal_xy_error_m'] < t['goal_xy_tolerance_m']
                   and not v['floor_contact'] and not v['forbidden_contact'])
        return dict(success=bool(success), metrics=deepcopy(v), native_steps=self.native_steps,
                    task=t.get('task', self.task['task']), status='success' if success else 'not_successful')
