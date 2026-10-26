"""Semantic Panda environment. Truth and task diagnostics are separate from observe()."""
from copy import deepcopy
from pathlib import Path
from xml.etree import ElementTree as ET

import mujoco
import numpy as np
from scipy.spatial.transform import Rotation

from sage.experiments.embodied_simdata_v0.controller import PandaController
from .contracts import read, require


def vec(values):
    return ' '.join(format(float(v), '.10g') for v in np.asarray(values).ravel())


def owners(model):
    result = {}
    for i in range(model.ngeom):
        body = int(model.geom_bodyid[i])
        while model.body_parentid[body] != 0:
            body = int(model.body_parentid[body])
        result[i] = model.body(body).name or 'world'
    return result


def support_probe(model, data, task, point, half_xy=None):
    """Probe generated geometry at the entire target footprint, not a marker."""
    group = np.array([0,0,0,1,0,0], dtype=np.uint8)
    dims = np.array(task['target_dimensions_m'])
    half = dims[:2]/2 if half_xy is None else np.asarray(half_xy)
    rot = np.array(task['target_rotation'])
    ownership = owners(model)
    target = model.body(task['target_body']).id
    result = []
    for x,y in [(0,0),(-1,-1),(-1,1),(1,-1),(1,1)]:
        corner = np.asarray(point) + rot @ [x*half[0],y*half[1],0]
        origin = np.r_[corner[:2], task['support_top_z_m']+.4]
        geom = np.array([-1],dtype=np.int32)
        distance = mujoco.mj_ray(model,data,origin,np.array([0.,0.,-1.]),group,1,target,geom)
        z = float(origin[2]-distance)
        require(distance >= 0 and ownership.get(int(geom[0])) == task['support_body']
                and abs(z-task['support_top_z_m']) <= .015, 'target_region_has_no_real_support')
        result.append(dict(xy=corner[:2].tolist(),z=z,geom=model.geom(int(geom[0])).name))
    return result


def forbidden_contacts(model, data, task, allow_target=True, threshold=.001):
    ownership = owners(model)
    rows = []
    for c in data.contact:
        ids = [int(c.geom1),int(c.geom2)]
        own = [ownership[i] for i in ids]
        names = [model.geom(i).name for i in ids]
        if 'base' not in own:
            continue
        k = own.index('base'); other = 1-k
        allowed = own[other] == 'base' or names[other] == 'robot_mount'
        if allow_target and own[other] == task['target_body']:
            allowed = names[k].startswith('finger')
        if not allowed and c.dist < -threshold:
            rows.append(dict(geoms=names,penetration_m=-float(c.dist)))
    return rows


def choose_mount(root, output, task):
    """Bounded robot-only mounting search; objects and goals never change."""
    model = mujoco.MjModel.from_xml_path(str(output/'model_unmounted.xml'))
    data = mujoco.MjData(model)
    ctrl = PandaController(model,data)
    ctrl.target_rot = np.asarray(task['target_rotation']) @ np.diag([1.,-1.,-1.])
    data.qpos[ctrl.qi] = ctrl.qhome
    data.qpos[model.jnt_qposadr[model.joint('finger_joint1').id]] = .04
    data.qpos[model.jnt_qposadr[model.joint('finger_joint2').id]] = -.04
    support = np.array(task['support_pose'])
    w,l,_ = task['support_dimensions_m']
    offsets = [(-w/2+.11,0),(w/2-.11,0),(-w/2+.11,-l/4),(w/2-.11,-l/4),
               (-w/4,-l/2+.11),(w/4,-l/2+.11),(-w/4,l/2-.11),(w/4,l/2-.11)]
    base_id = model.body('base').id
    mount_id = model.geom('robot_mount').id
    rows = []
    for index,(x,y) in enumerate(offsets):
        xyz = support[:3,3] + support[:3,:3] @ [x,y,0.]
        xyz[2] = task['support_top_z_m']+.02
        direction = support[:3,3]-xyz
        yaw = np.arctan2(direction[1],direction[0])
        quat = [np.cos(yaw/2),0,0,np.sin(yaw/2)]
        model.body_pos[base_id] = xyz
        model.body_quat[base_id] = quat
        model.geom_pos[mount_id] = xyz-[0,0,.01]
        # IK uses a separate data object with the same updated model.
        data.qpos[ctrl.qi] = ctrl.qhome
        mujoco.mj_forward(model,data)
        row = dict(index=index,position_m=xyz.tolist(),quaternion_wxyz=quat,home_collisions=forbidden_contacts(model,data,task,False))
        try:
            row['mount_support'] = support_probe(model,data,task,xyz,half_xy=[.09,.09])
            row['start_support'] = support_probe(model,data,task,task['start'])
            row['goal_support'] = support_probe(model,data,task,task['goal'])
            require(not row['home_collisions'], 'robot_home_collision')
            q = ctrl.qhome.copy()
            ik = []
            grasp_height = task['grasp_height_offset_m']
            for point,height in [(task['start'],grasp_height+.10),(task['start'],grasp_height),
                                 (task['goal'],grasp_height),(task['goal'],grasp_height+.10)]:
                target = np.asarray(point)+[0,0,height]
                q,error = ctrl.ik(target,q)
                data.qpos[ctrl.qi] = q
                mujoco.mj_forward(model,data)
                ik.append(dict(position_m=target.tolist(),q=q.tolist(),residual=error,
                               forbidden_contacts=forbidden_contacts(model,data,task)))
            row['endpoint_ik'] = ik
            require(all(p['residual'] < .015 and not p['forbidden_contacts'] for p in ik), 'endpoint_IK_or_collision_unresolved')
            row['status'] = 'endpoint_checks_passed_path_and_execution_unknown'
            rows.append(row)
            root.find("worldbody/body[@name='base']").set('pos',vec(xyz))
            root.find("worldbody/body[@name='base']").set('quat',vec(quat))
            root.find("worldbody/geom[@name='robot_mount']").set('pos',vec(xyz-[0,0,.01]))
            return dict(selected=row,candidates=rows,budget=8,scene_edits=0,
                        interpretation='static support and endpoint IK; no path planner or task success claim')
        except ValueError as exc:
            row.update(status='unknown_feasibility',reason=str(exc))
            rows.append(row)
    from .contracts import write
    write(output/'mount_candidates.json',dict(selected=None,candidates=rows,budget=8))
    raise ValueError('mount_budget_unsolved_not_proof_of_infeasibility')


class TaskEnvironment:
    def __init__(self, package):
        self.package = Path(package)
        self.task = read(self.package/'task.json')
        self.model = mujoco.MjModel.from_xml_path(str(self.package/'model.xml'))
        self.data = mujoco.MjData(self.model)
        self.ctrl = PandaController(self.model,self.data)
        self.ctrl.target_rot = np.asarray(self.task['target_rotation']) @ np.diag([1.,-1.,-1.])
        self.joints = [self.model.joint(f'joint{i}').id for i in range(1,8)] + [self.model.joint('finger_joint1').id,self.model.joint('finger_joint2').id]
        self.qi = self.model.jnt_qposadr[self.joints]
        self.vi = self.model.jnt_dofadr[self.joints]
        self.target_qi = self.model.jnt_qposadr[self.model.joint('task_target_free').id]
        self.target_vi = self.model.jnt_dofadr[self.model.joint('task_target_free').id]
        self.owner = owners(self.model)
        self.mask = mujoco.mjtState.mjSTATE_INTEGRATION
        require(self.model.opt.timestep == .001, 'physics_timestep')
        self.ready = False

    def reset(self, seed, jitter=True):
        mujoco.mj_resetData(self.model,self.data)
        self.data.qpos[self.ctrl.qi] = self.ctrl.qhome
        self.data.qpos[self.qi[-2:]] = [.04,-.04]
        self.start = np.asarray(self.task['start']).copy()
        if jitter:
            self.start[:2] += np.random.default_rng(seed).uniform(-.02,.02,2)
        self.data.qpos[self.target_qi:self.target_qi+3] = self.start
        self.data.qpos[self.target_qi+3:self.target_qi+7] = self.task['target_quat']
        mujoco.mj_forward(self.model,self.data)
        support_probe(self.model,self.data,self.task,self.start)
        support_probe(self.model,self.data,self.task,self.task['goal'])
        self.metrics = dict(max_lift_m=0.,bilateral_s=0.,stable_s=0.,floor_contact=False,forbidden_contact=False,
                            goal_xy_error_m=float(np.linalg.norm(self.start[:2]-self.task['goal'][:2])))
        self.native_steps = 0
        self.ready = True
        return self.observe()

    def observe(self):
        return dict(proprio=np.r_[self.data.qpos[self.qi],self.data.qvel[self.vi]].copy())

    def state(self):
        value = np.empty(mujoco.mj_stateSize(self.model,self.mask))
        mujoco.mj_getState(self.model,self.data,value,self.mask)
        return value

    def _audit(self):
        m,d,t = self.model,self.data,self.task
        pads = set(); finger = False; support = 0.
        for i,c in enumerate(d.contact):
            ids = [int(c.geom1),int(c.geom2)]
            own = [self.owner[j] for j in ids]
            names = [m.geom(j).name for j in ids]
            if t['target_body'] not in own:
                continue
            force = np.zeros(6);mujoco.mj_contactForce(m,d,i,force)
            for name in names:
                if name.startswith('finger') and 'collision' in name:
                    finger = True
                    if force[0] > t['success']['min_bilateral_force_n']:
                        pads.add(name[6])
            if 'floor' in names:
                self.metrics['floor_contact'] = True
            if t['support_body'] in own:
                normal = c.frame[2]*(1 if own.index(t['target_body']) == 1 else -1)
                if normal > .5:
                    support += max(0.,force[0]*normal)
        self.metrics['forbidden_contact'] |= bool(forbidden_contacts(m,d,t,threshold=t['success']['max_forbidden_penetration_m']))
        pos = d.qpos[self.target_qi:self.target_qi+3]
        velocity = d.qvel[self.target_vi:self.target_vi+6]
        speed = float(np.linalg.norm(velocity[:3]))
        angular = float(np.linalg.norm(velocity[3:]))
        self.metrics['max_lift_m'] = max(self.metrics['max_lift_m'],float(pos[2]-self.start[2]))
        self.metrics['bilateral_s'] += .001 if len(pads) == 2 else 0.
        goal_error = float(np.linalg.norm(pos[:2]-t['goal'][:2]))
        stable = (support > 0 and not finger and speed < t['success']['max_speed_m_s']
                  and angular < t['success']['max_angular_speed_rad_s'] and goal_error < t['success']['goal_xy_tolerance_m'])
        self.metrics['stable_s'] = self.metrics['stable_s']+.001 if stable else 0.
        self.metrics.update(goal_xy_error_m=goal_error,speed_m_s=speed,
                            angular_speed_rad_s=angular,support_force_n=float(support),finger_contact=finger)

    def step(self, action):
        action = np.asarray(action,dtype=float)
        require(action.shape == (8,) and np.isfinite(action).all(), 'invalid_action')
        bounds = self.model.jnt_range[self.ctrl.joints]
        require(np.all(action[:7] >= bounds[:,0]) and np.all(action[:7] <= bounds[:,1]) and 0 <= action[7] <= .04, 'action_out_of_bounds')
        require(self.ready, 'reset_required')
        for _ in range(50):
            mujoco.mj_forward(self.model,self.data)
            self.ctrl.action(action[:7],action[7])
            mujoco.mj_step(self.model,self.data)
            self.native_steps += 1
            self._audit()
        require(np.isfinite(self.state()).all(), 'nonfinite_physics')
        return self.observe()

    def evaluate(self):
        v,t = self.metrics,self.task['success']
        success = (v['max_lift_m'] >= t['min_lift_m'] and v['bilateral_s'] >= t['min_bilateral_s']
                   and v['stable_s'] >= t['stable_s'] and v['goal_xy_error_m'] < t['goal_xy_tolerance_m']
                   and not v['floor_contact'] and not v['forbidden_contact'])
        return dict(success=bool(success),metrics=deepcopy(v),native_steps=self.native_steps,
                    task=self.task['task'],status='success' if success else 'not_successful')
