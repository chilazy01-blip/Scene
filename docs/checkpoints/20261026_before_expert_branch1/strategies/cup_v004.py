"""Cup-frame upright placement with supported, gradual native-finger release."""
import numpy as np
from scipy.spatial.transform import Rotation
from sage.experiments.embodied_native_sonic_body_grasp_v1.task_stand import Task as BaseTask
from sage.experiments.embodied_native_sonic_grasp_feedback_v1.continuous_lift import make_path
from sage.experiments.embodied_native_object_transport_v1.task_v3 import smooth
from sage.experiments.embodied_sonic_command_integration_v1.native_envelope import allocate
from sage.experiments.embodied_sonic_command_integration_v1.task_envelope import fast_update
from sage.experiments.embodied_native_sonic_grasp_feedback_v1.relative_grip_wrench import wrench
from sage.experiments.embodied_native_walk_motion_v2.engine import hand_ids
from sage.experiments.embodied_carry_v1.grasp import RIGHT_CLOSED


def upright(R):
    axis = R[:, 2]
    cross = np.cross(axis, [0., 0., 1.])
    angle = np.arctan2(np.linalg.norm(cross), axis[2])
    if np.linalg.norm(cross) < 1e-9:
        return R.copy()
    return Rotation.from_rotvec(cross / np.linalg.norm(cross) * angle).as_matrix() @ R


class Task(BaseTask):
    def plan(self, tick, data, goal, R, duration, label):
        p, old_R = self.desired(tick)
        self.path = make_path(tick, p, old_R, goal, R, duration)
        self.joint_path = None
        self.events.append(dict(kind='cup_frame_reference', tick=tick, label=label,
                                origin=p.tolist(), goal=np.asarray(goal).tolist(),
                                rotation=R.tolist(), duration=duration))
        self.synchronize(tick, data, force=True)

    def move(self, tick, data, goal, rotation, duration=65):
        if tick < 1597 or self.stage != 'place':
            return super().move(tick, data, goal, rotation, duration)
        pid = self.model.body('payload').id
        W = data.xmat[self.wrist].reshape(3, 3)
        C = data.xmat[pid].reshape(3, 3)
        self.place_relative_R = W.T @ C
        self.place_local = W.T @ (data.xpos[pid] - data.xpos[self.wrist])
        self.place_com_local = W.T @ (data.xipos[pid] - data.xpos[self.wrist])
        self.place_cup_R = upright(C)
        self.place_wrist_R = self.place_cup_R @ self.place_relative_R.T
        self.place_goal = np.asarray(self.case['target_object_xyz_m']).copy()
        requested = self.place_goal.copy()
        desk = self.model.body('generated_desk').id
        desk_vertices = np.asarray(data.flexvert_xpos)[np.asarray(self.model.flex_vertbodyid) == desk]
        top = desk_vertices[desk_vertices[:, 2] >= float(self.case['support_top_m']) - .003]
        fid = self.mujoco.mj_name2id(self.model, self.mujoco.mjtObj.mjOBJ_FLEX, 'payload_surface')
        start = int(self.model.flex_vertadr[fid])
        count = int(self.model.flex_vertnum[fid])
        vertices = np.asarray(data.flexvert_xpos[start:start + count])
        local_vertices = (vertices - data.xpos[pid]) @ C
        planned = local_vertices @ self.place_cup_R.T
        base = planned[planned[:, 2] <= planned[:, 2].min() + .003]
        lower = top[:, :2].min(axis=0) - base[:, :2].min(axis=0) + .020
        upper = top[:, :2].max(axis=0) - base[:, :2].max(axis=0) - .020
        self.place_goal[:2] = np.clip(self.place_goal[:2], lower, upper)
        self.edge_projected = bool(np.linalg.norm(self.place_goal[:2] - requested[:2]) > .001)
        self.support_next = tick
        self.events.append(dict(kind='mesh_base_supported_target', tick=tick,
                                requested_cup_origin=requested.tolist(), planned_cup_origin=self.place_goal.tolist(),
                                feasible_origin_lower_xy=lower.tolist(), feasible_origin_upper_xy=upper.tolist(),
                                desk_top_bounds=[top[:, :2].min(axis=0).tolist(), top[:, :2].max(axis=0).tolist()],
                                cup_base_bounds=[base[:, :2].min(axis=0).tolist(), base[:, :2].max(axis=0).tolist()],
                                margin_m=.020, projected=self.edge_projected))
        self.airborne_support_finished = False
        self.place_step = 'align'
        self.place_step_start = tick
        self.release_origin = None
        self.support_corrections = 0
        self.support_next = tick
        self.plan(tick, data, self.place_goal + [0., 0., .035] -
                  self.place_wrist_R @ self.place_local,
                  self.place_wrist_R, 90, 'upright_above_target')

    def airborne_grip(self, tick, data, m):
        if m['desk_supported']:
            self.airborne_support_finished = True
        if self.airborne_support_finished:
            return
        h = hand_ids(self.model)
        pid = self.model.body('payload').id
        R = data.xmat[self.wrist].reshape(3, 3)
        C = data.xmat[pid].reshape(3, 3)
        mass = float(self.model.body_mass[pid])
        weight = mass * abs(float(self.model.opt.gravity[2]))
        hv = np.zeros(6)
        cv = np.zeros(6)
        J = np.zeros((3, self.model.nv))
        Jr = np.zeros_like(J)
        self.mujoco.mj_jac(self.model, data, J, Jr, data.xpos[self.wrist], self.wrist)
        hv[:3], hv[3:] = Jr @ data.qvel, J @ data.qvel
        self.mujoco.mj_jac(self.model, data, J, Jr, data.xipos[pid], pid)
        cv[:3], cv[3:] = Jr @ data.qvel, J @ data.qvel
        target = wrench(weight, mass, data.xpos[self.wrist], R, self.place_com_local,
                        self.place_relative_R, data.xipos[pid], C, hv, cv)
        proposal = allocate(self.mujoco, self.model, data, self.contact_minimum,
                            target, float(self.case['loaded_native_reference_ratio']))
        if proposal['feasible']:
            ix = np.array(proposal['right_finger_indices'])
            ends = np.array([RIGHT_CLOSED[h['names'][i]] * self.case['loaded_native_reference_ratio'] for i in ix])
            self.finger_reference[ix] = fast_update(self.finger_reference[ix],
                np.asarray(proposal['desired_contact_torque_nm']),
                np.asarray(proposal['measured_contact_torque_nm']), h['kp'][ix], ends)
        if tick % 5 == 0:
            self.events.append(dict(kind='airborne_place_native_grip_feedback', tick=tick,
                                    feasible=bool(proposal['feasible']), wrench=target.tolist(),
                                    reference_rad=self.finger_reference.tolist()))

    def observe(self, tick, data, m):
        pid = self.model.body('payload').id
        C = data.xmat[pid].reshape(3, 3)
        vel = np.zeros(6)
        self.mujoco.mj_objectVelocity(self.model, data, self.mujoco.mjtObj.mjOBJ_BODY,
                                     pid, vel, 0)
        up = float(C[2, 2])
        if tick % 5 == 0:
            self.events.append(dict(kind='cup_support_transfer', tick=tick,
                                    stage=self.stage, cup_up=up,
                                    angular_velocity=vel[:3].tolist(),
                                    cup_position=data.xpos[pid].tolist(),
                                    desk_supported=m['desk_supported'],
                                    hand_contact=m['hand_contact'],
                                    forces=dict(m['forces']),
                                    hand_reference=self.finger_reference.tolist()))
        return C, vel, up

    def update(self, tick, data, m):
        if self.stage == 'settle':
            if self.done or self.failure:
                return
            if tick-self.start > self.case['stage_timeouts_ticks']['settle']:
                self.failure = 'settle_timeout'
                return
            ready = (m['desk_supported'] and not m['hand_contact'] and
                     np.linalg.norm(m['object_velocity_m_s']) < .02 and
                     np.linalg.norm(data.qvel[:3]) < .06)
            self.stable = self.stable+1 if ready else 0
            if self.stable >= 51:
                self.events.append(dict(kind='expert_full_settle_observation_window',tick=tick,
                                        observations=51,complete_intervals=50,
                                        unchanged_final_substep_gate=True))
                self.done = True
                self.change('done',tick,data,m)
            return
        if tick < 1597 or self.stage not in ('place', 'release', 'retract'):
            return super().update(tick, data, m)
        if self.done or self.failure:
            return
        age = tick - self.start
        self.last_object_local = m['object_local_m']
        self.last_object_local_world = np.asarray(m['object_m'])
        C, vel, up = self.observe(tick, data, m)
        if self.stage == 'place':
            self.airborne_grip(tick, data, m)
            if age > 600:
                self.failure = 'cup_upright_place_timeout'
                return
            slip = float(np.linalg.norm(np.asarray(m['object_local_m']) - self.anchor))
            self.max_slip = max(self.max_slip, slip)
            if slip > .04:
                self.failure = 'object_slipped'
                return
            if self.place_step == 'align':
                ready = self.reached(tick, data) and up > .985 and np.linalg.norm(vel[:3]) < (.6 if self.edge_projected else .3)
                self.stable = self.stable + 1 if ready else 0
                if self.stable >= (5 if self.edge_projected else 10):
                    self.stable = 0
                    self.place_step = 'lower'
                    self.place_step_start = tick
                    self.support_next = tick + 85
                    self.plan(tick, data, self.place_goal -
                              self.place_wrist_R @ self.place_local,
                              self.place_wrist_R, 65, 'upright_lower_to_support')
            else:
                ready = (self.reached(tick, data) and m['desk_supported'] and
                         up > .985 and np.linalg.norm(vel[:3]) < .25 and
                         np.linalg.norm(np.asarray(m['object_m'])[:2] - self.place_goal[:2]) < .10)
                self.stable = self.stable + 1 if ready else 0
                if (self.stable == 0 and tick >= self.support_next and
                        self.support_corrections < 5 and
                        (up < .985 or not m['desk_supported'])):
                    p, R = self.desired(tick)
                    W = data.xmat[self.wrist].reshape(3, 3)
                    pid = self.model.body('payload').id
                    local = W.T @ (data.xpos[pid] - data.xpos[self.wrist])
                    tilt = Rotation.from_matrix(upright(C) @ C.T).as_rotvec()
                    magnitude = np.linalg.norm(tilt)
                    correction = (tilt * min(.7, .10 / max(magnitude, 1e-9))
                                  if up < .985 else np.zeros(3))
                    G = Rotation.from_rotvec(correction).as_matrix() @ R
                    goal = p - (G - R) @ local
                    weight = float(self.model.body_mass[pid] * abs(self.model.opt.gravity[2]))
                    relief = (np.clip((m['forces']['desk'] - weight) * .0006, 0., .003)
                              if m['desk_supported'] else (-.001 if up > .985 else .001))
                    goal[2] += relief
                    nominal_z = self.place_goal[2] - (G @ self.place_local)[2]
                    goal[2] = np.clip(goal[2], nominal_z - .010, nominal_z + .015)
                    self.support_corrections += 1
                    self.support_next = tick + 65
                    self.events.append(dict(kind='measured_cup_support_correction', tick=tick,
                                            attempt=self.support_corrections, cup_up=up,
                                            correction_rad=correction.tolist(), relief_m=float(relief),
                                            cup_in_wrist_m=local.tolist(), forces=dict(m['forces'])))
                    self.plan(tick, data, goal, G, 40, 'measured_cup_support_correction')
                if self.stable >= (8 if self.support_corrections else 20):
                    self.change('release', tick, data, m)
                    self.release_start = tick
                    self.release_origin = self.finger_reference.copy()
        elif self.stage == 'release':
            # Native position targets only; maintain wrist pose during transfer.
            f = float(smooth(age / 100.))
            self.finger_reference = self.release_origin * (1. - f)
            self.closure = self.case['grip_closure'] * (1. - f)
            if age >= 115 and m['desk_supported'] and not m['hand_contact']:
                self.change('retract', tick, data, m)
                p, R = self.desired(tick)
                self.plan(tick, data, p + [-.15, 0., .08], R, 60, 'open_hand_retract')
            elif age > 200:
                self.failure = 'supported_release_timeout'
        elif self.stage == 'retract':
            self.finger_reference[:] = 0.
            if self.reached(tick, data):
                self.change('settle', tick, data, m)
            elif age > 250:
                self.failure = 'retract_timeout'
