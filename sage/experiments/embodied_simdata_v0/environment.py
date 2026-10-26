"""20 Hz policy environment with 1 kHz finite-torque control and contact audit."""
import os
os.environ.setdefault('MUJOCO_GL', 'egl')
from .gpu_egl import bind
RENDER_BINDING = bind()
from copy import deepcopy
from pathlib import Path
import json

import mujoco
import numpy as np
from scipy.spatial.transform import Rotation

from .controller import PandaController
from .common import binding, digest, outcome


class TaskEnvironment:
    def __init__(self, scene, render=True, width=160, height=120):
        self.scene = Path(scene)
        self.config = json.loads((self.scene / 'task.json').read_text())
        cache = self.scene / 'compiled_model.json'
        if cache.exists():
            identity = json.loads(cache.read_text())
            if (identity['xml_sha256'] != binding(self.scene / 'model.xml')['sha256']
                    or identity['binary_sha256'] != binding(self.scene / 'model.mjb')['sha256']):
                raise ValueError('compiled_model_identity_mismatch')
            if identity['mujoco'] != mujoco.__version__:
                raise ValueError('compiled_model_version_mismatch_use_pinned_environment')
            self.model = mujoco.MjModel.from_binary_path(str(self.scene / 'model.mjb'))
        else:
            self.model = mujoco.MjModel.from_xml_path(str(self.scene / 'model.xml'))
        if (self.model.opt.timestep != .001 or self.config['dt_s'] != .001
                or self.config['policy_dt_s'] != .05 or self.config['duration_s'] != 18.7):
            raise ValueError('unsupported_solver_or_control_schedule')
        self.data = mujoco.MjData(self.model)
        self.ctrl = PandaController(self.model, self.data)
        self.ctrl.target_rot = Rotation.from_euler('z', self.config['grasp_yaw_rad']).as_matrix() @ np.diag([1., -1., -1.])
        self.mask = mujoco.mjtState.mjSTATE_INTEGRATION
        self.identity = digest(dict(model=binding(self.scene / 'model.xml'), config=self.config))
        m = self.model
        self.joints = [m.joint(f'joint{i}').id for i in range(1, 8)] + [m.joint('finger_joint1').id, m.joint('finger_joint2').id]
        self.qi = m.jnt_qposadr[self.joints]; self.vi = m.jnt_dofadr[self.joints]
        self.target_qi = m.jnt_qposadr[m.joint('target_free').id]
        self.target_vi = m.jnt_dofadr[m.joint('target_free').id]
        self.target_body = m.body('task_book').id
        self.names = {i: mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, i) or '' for i in range(m.ngeom)}
        self.owners = {}
        for i in range(m.ngeom):
            b = int(m.geom_bodyid[i])
            while m.body_parentid[b] != 0:
                b = int(m.body_parentid[b])
            self.owners[i] = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, b) or 'world'
        self.width, self.height = width, height
        self.renderer = mujoco.Renderer(m, height=height, width=width) if render else None
        self.options = mujoco.MjvOption()
        # Robot collision meshes overlap robot visuals; diagnostic sites include
        # a ten-metre grip cylinder. Only visual surfaces and the goal marker
        # belong in policy images. Groups affect rendering, never collisions.
        for i in range(m.ngeom):
            if self.owners[i] == 'world' and m.geom_group[i] == 0:
                m.geom_group[i] = 2
        m.site_group[:] = 5
        m.site_group[m.site('goal_marker').id] = 0
        self.options.geomgroup[:] = [0, 1, 1, 0, 0, 0]
        self.options.sitegroup[:] = [1, 0, 0, 0, 0, 0]
        self.render_profile = 'visual_surfaces_and_goal_only/v3'
        self.options.flags[mujoco.mjtVisFlag.mjVIS_CONTACTPOINT] = False
        self.steps = 0; self.stopped = True
        self.support_probe(self.config['start'])
        self.support_probe(self.config['goal'])

    def support_probe(self, point):
        m, d = self.model, self.data
        mujoco.mj_forward(m, d)
        group = np.zeros(6, dtype=np.uint8); group[3] = 1
        rotation = np.asarray(self.config['workspace_rotation'])
        results = []
        for x in (-.015, .015):
            for y in (-.08, .08):
                corner = np.asarray(point) + rotation @ [x, y, 0.]
                origin = np.r_[corner[:2], 1.5]
                geom = np.array([-1], dtype=np.int32)
                distance = mujoco.mj_ray(m, d, origin, np.array([0., 0., -1.]), group, 1, self.target_body, geom)
                z = float(1.5 - distance)
                if distance < 0 or self.owners.get(int(geom[0])) != 'explicit_desk' or abs(z - .75) > .025:
                    raise ValueError('target_region_has_no_real_support')
                results.append(dict(xy=corner[:2].tolist(), z=z, geom=self.names[int(geom[0])]))
        return results

    def state(self):
        value = np.empty(mujoco.mj_stateSize(self.model, self.mask))
        mujoco.mj_getState(self.model, self.data, value, self.mask)
        return value

    def reset(self, seed):
        m, d = self.model, self.data
        mujoco.mj_resetData(m, d)
        self.seed = int(seed); self.rng = np.random.default_rng(seed)
        self.active = deepcopy(self.config)
        rotation = np.asarray(self.config['workspace_rotation'])
        for key in ('start', 'goal'):
            jitter = self.rng.uniform(-self.config['initialization_xy_jitter_m'], self.config['initialization_xy_jitter_m'], 2)
            self.active[key] = (np.asarray(self.config[key]) + rotation @ np.r_[jitter, 0.]).tolist()
        d.qpos[self.ctrl.qi] = self.ctrl.qhome
        d.qpos[self.qi[-2:]] = [.04, -.04]
        d.qpos[self.target_qi:self.target_qi+3] = self.active['start']
        self.model.site_pos[self.model.site('goal_marker').id, :2] = self.active['goal'][:2]
        mujoco.mj_forward(m, d)
        self.support = {k: self.support_probe(self.active[k]) for k in ('start', 'goal')}
        self.steps = 0; self.stopped = False
        self.metrics = dict(max_lift_m=0., bilateral_seconds=0., stable_seconds=0.,
                            max_robot_scene_penetration_m=0., target_floor_contact_steps=0,
                            forbidden_contact_steps={}, goal_xy_error_m=1., final_speed_m_s=0.,
                            final_support_contact=False, final_finger_contact=False, final_support_force_n=0.)
        self.audit_rows = []; self.actions = []; self.states = [self.state()]
        self.observations = [self.observe()]
        if self.renderer is not None:
            from .gpu_egl import proof
            self.render_backend = proof(RENDER_BINDING)
        return self.observations[-1]

    def observe(self):
        # Compute rendering kinematics on a separate MjData, preserving solver state.
        rgb = None
        if self.renderer is not None:
            visual = mujoco.MjData(self.model)
            mujoco.mj_setState(self.model, visual, self.state(), self.mask)
            mujoco.mj_forward(self.model, visual)
            self.renderer.update_scene(visual, camera='front', scene_option=self.options)
            rgb = self.renderer.render().copy()
        return dict(rgb=rgb, proprio=np.r_[self.data.qpos[self.qi], self.data.qvel[self.vi]].copy(),
                    time=float(self.data.time))

    def plan_reference(self):
        s, g = self.active['start'], self.active['goal']; z = s[2] + .08
        phases = [('approach', 3., [*s[:2], z+.15], .04), ('descend', 2., [*s[:2], z], .04),
                  ('close', 1.2, [*s[:2], z], 0.), ('lift', 2., [*s[:2], z+.16], 0.),
                  ('transfer', 3., [*g[:2], z+.16], 0.), ('lower', 2., [*g[:2], z+.005], 0.),
                  ('release', 1.5, [*g[:2], z+.005], .04), ('retreat', 2., [*g[:2], z+.20], .04),
                  ('settle', 2., [*g[:2], z+.20], .04)]
        self.plan = []; qprev = self.ctrl.qhome.copy(); start = 0.
        for phase, duration, position, grip in phases:
            qgoal, error = self.ctrl.ik(position, qprev)
            if error > .015:
                raise ValueError('reference_IK_failed')
            self.plan.append(dict(phase=phase, start=start, duration=duration, qprev=qprev.tolist(),
                                  qgoal=qgoal.tolist(), grip=grip, ik_error=error))
            qprev = qgoal; start += duration
        return self.plan

    def reference_action(self):
        t = self.steps * .05
        phase = next((p for p in self.plan if t < p['start'] + p['duration'] - 1e-8), self.plan[-1])
        a = np.clip((t - phase['start']) / (phase['duration'] * .8), 0, 1)
        a = a*a*(3-2*a)
        return np.r_[(1-a)*np.asarray(phase['qprev']) + a*np.asarray(phase['qgoal']), phase['grip']]

    def _audit(self):
        m, d, v, c = self.model, self.data, self.metrics, self.active
        pads = set(); finger = False; support_force = 0.
        for index, contact in enumerate(d.contact):
            ids = [int(contact.geom1), int(contact.geom2)]
            owners = [self.owners[i] for i in ids]; names = [self.names[i] for i in ids]
            if not ('task_book' in owners or 'base' in owners):
                continue
            force = np.zeros(6); mujoco.mj_contactForce(m, d, index, force)
            if 'task_book' in owners:
                for name in names:
                    if name.startswith('finger') and 'collision' in name:
                        finger = True
                        if force[0] > 1.: pads.add(name[6])
                if 'floor' in names: v['target_floor_contact_steps'] += 1
                if 'explicit_desk' in owners:
                    normal_z = contact.frame[2] * (1 if owners.index('task_book') == 1 else -1)
                    if normal_z > .5: support_force += max(0., force[0] * normal_z)
            for k in (0, 1):
                if owners[k] == 'base' and owners[1-k] not in c['allowed_robot_contact_owners'] and names[1-k] not in c['allowed_robot_contact_geoms']:
                    pair = '|'.join(sorted(names))
                    v['forbidden_contact_steps'][pair] = v['forbidden_contact_steps'].get(pair, 0) + 1
                    v['max_robot_scene_penetration_m'] = max(v['max_robot_scene_penetration_m'], -float(contact.dist))
        v['bilateral_seconds'] += .001 if len(pads) == 2 else 0.
        pos = d.qpos[self.target_qi:self.target_qi+3]
        speed = float(np.linalg.norm(d.qvel[self.target_vi:self.target_vi+3]))
        v['max_lift_m'] = max(v['max_lift_m'], float(pos[2] - c['start'][2]))
        stable = support_force > 0 and not finger and speed < .03
        v['stable_seconds'] = v['stable_seconds'] + .001 if stable else 0.
        v.update(goal_xy_error_m=float(np.linalg.norm(pos[:2] - c['goal'][:2])),
                 final_speed_m_s=speed, final_support_contact=bool(support_force > 0),
                 final_finger_contact=finger, final_support_force_n=float(support_force))
        self.audit_rows.append([float(d.time), float(d.time-.001), speed, support_force,
                               float(finger), float(len(pads) == 2), v['goal_xy_error_m'], pos[2]])

    def step(self, action):
        action = np.asarray(action, dtype=float)
        ranges = self.model.jnt_range[self.ctrl.joints]
        if action.shape != (8,) or not np.isfinite(action).all():
            raise ValueError('invalid_action_shape_or_values')
        if np.any(action[:7] < ranges[:, 0]) or np.any(action[:7] > ranges[:, 1]) or not 0 <= action[7] <= .04:
            raise ValueError('action_out_of_bounds')
        if self.stopped:
            raise RuntimeError('episode_not_running')
        for _ in range(50):
            mujoco.mj_forward(self.model, self.data)
            self.ctrl.action(action[:7], action[7])
            mujoco.mj_step(self.model, self.data)
            self._audit()
            if not np.isfinite(self.state()).all():
                raise FloatingPointError('nonfinite_simulator_state')
        self.steps += 1
        self.stopped = self.steps >= round(self.config['duration_s']/.05)
        obs = self.observe()
        self.actions.append(action.copy()); self.states.append(self.state()); self.observations.append(obs)
        return obs

    def evaluate(self):
        return outcome(self.active, self.metrics, stopped=self.stopped, reason='task_horizon', engineering=True)

    def checkpoint(self):
        return dict(identity=self.identity, state=self.state().tolist(), steps=self.steps,
                    active=deepcopy(self.active), metrics=deepcopy(self.metrics), rng=self.rng.bit_generator.state)

    def restore(self, saved):
        if saved['identity'] != self.identity:
            raise ValueError('checkpoint_identity_mismatch')
        if saved['steps'] > len(self.actions):
            raise ValueError('checkpoint_recording_prefix_required')
        mujoco.mj_setState(self.model, self.data, np.asarray(saved['state']), self.mask)
        self.steps = saved['steps']; self.active = deepcopy(saved['active']); self.metrics = deepcopy(saved['metrics'])
        self.rng.bit_generator.state = saved['rng']; self.stopped = self.steps >= 374
        self.actions = self.actions[:self.steps]
        self.states = self.states[:self.steps+1]
        self.observations = self.observations[:self.steps+1]
        self.audit_rows = self.audit_rows[:self.steps*50]

    def camera_calibration(self):
        m, d = self.model, self.data
        mujoco.mj_forward(m, d)
        i = m.camera('front').id
        f = .5*self.height/np.tan(np.deg2rad(m.cam_fovy[i])*.5)
        camera_to_world = np.eye(4)
        camera_to_world[:3, :3] = d.cam_xmat[i].reshape(3, 3) @ np.diag([1., -1., -1.])
        camera_to_world[:3, 3] = d.cam_xpos[i]
        return dict(width=self.width, height=self.height,
                    K=[[f, 0, (self.width-1)/2], [0, f, (self.height-1)/2], [0, 0, 1]],
                    camera_to_world_optical=camera_to_world.tolist(),
                    convention='pixel centers, +X right +Y down +Z forward; world +Z up',
                    source='analytic simulator camera, not real-camera calibration')

    def close(self):
        if self.renderer is not None:
            self.renderer.close()
