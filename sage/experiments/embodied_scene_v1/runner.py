"""Actual actuator/contact rollouts with reproducible state and failure evidence."""
import os
os.environ.setdefault('MUJOCO_GL', 'egl')
from pathlib import Path
import heapq
import json
import time
import numpy as np
import mujoco
from scipy.spatial.transform import Rotation
from scipy.optimize import least_squares
from .models import make_task, BOOK_START, BOOK_GOAL, NAV_START, NAV_GOAL
from .package import write_json, bound


def wrap(x): return (x + np.pi) % (2*np.pi) - np.pi


class Recorder:
    def __init__(self, model, data):
        self.m, self.d = model, data
        self.mask = mujoco.mjtState.mjSTATE_INTEGRATION
        self.states, self.contacts, self.phases = [], [], []
        self.reset_state = None
        self.max_penetration = 0.; self.forbidden = {}; self.bilateral_steps = 0
        self.max_lift = 0.; self.target_floor_hits = 0; self.max_robot_penetration = 0.
        self.ids = {i: (mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, i) or '') for i in range(model.ngeom)}
        self.owners = {}
        for i in range(model.ngeom):
            b = model.geom_bodyid[i]
            while model.body_parentid[b] != 0: b = model.body_parentid[b]
            self.owners[i] = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, b) or 'world'
    def record_reset(self):
        self.reset_state = np.empty(mujoco.mj_stateSize(self.m, self.mask))
        mujoco.mj_getState(self.m,self.d,self.reset_state,self.mask)
    def audit(self):
        pads = set()
        if 'task_book' in self.owners.values():
            self.max_lift = max(self.max_lift, float(self.d.body('task_book').xpos[2] - BOOK_START[2]))
        for contact_index, c in enumerate(self.d.contact):
            contact_force = np.zeros(6); mujoco.mj_contactForce(self.m,self.d,contact_index,contact_force)
            i, j = int(c.geom1), int(c.geom2)
            names = [self.ids[i], self.ids[j]]; owners = [self.owners[i], self.owners[j]]
            penetration = max(0., -float(c.dist)); self.max_penetration = max(self.max_penetration, penetration)
            if 'task_book' in owners:
                for name in names:
                    if name.startswith('finger') and 'collision' in name and contact_force[0] > 1.: pads.add(name[6])
                if 'floor' in names: self.target_floor_hits += 1
            robot_idx = next((k for k in (0, 1) if owners[k] in ('base', 'base_link')), None)
            if robot_idx is not None:
                other = 1 - robot_idx
                allowed = owners[other] in ('base', 'base_link', 'task_book') or names[other] in ('floor', 'robot_mount') or owners[other] == 'explicit_area_rug'
                if not allowed:
                    self.max_robot_penetration = max(self.max_robot_penetration, penetration)
                    key = '|'.join(sorted(names)); self.forbidden[key] = self.forbidden.get(key, 0) + 1
        if len(pads) == 2: self.bilateral_steps += 1
    def sample(self, phase):
        state = np.empty(mujoco.mj_stateSize(self.m, self.mask))
        mujoco.mj_getState(self.m, self.d, state, self.mask)
        self.states.append(state); self.phases.append(phase)
        rows = []
        for c in self.d.contact:
            force = np.zeros(6)
            index = len(rows); mujoco.mj_contactForce(self.m, self.d, index, force)
            rows.append(dict(geom1=self.ids[int(c.geom1)], geom2=self.ids[int(c.geom2)], dist=float(c.dist), wrench=force.tolist()))
        self.contacts.append(dict(state_time=float(self.d.time), solver_contact_time=float(self.d.time-self.m.opt.timestep), contacts=rows))
    def save(self, output):
        np.savez_compressed(output / 'reset_state.npz', state=self.reset_state, state_spec=int(self.mask))
        np.savez_compressed(output / 'trajectory.npz', state=np.array(self.states), phase=np.array(self.phases),
            state_spec=int(self.mask), dt=self.m.opt.timestep)
        write_json(output / 'contacts.json', self.contacts)


def restore_check(m, d):
    mask = mujoco.mjtState.mjSTATE_INTEGRATION
    state = np.empty(mujoco.mj_stateSize(m, mask)); mujoco.mj_getState(m, d, state, mask)
    b = mujoco.MjData(m)
    mujoco.mj_setState(m, b, state, mask)
    exact = True
    for _ in range(30):
        mujoco.mj_step(m, d); mujoco.mj_step(m, b)
        sa = np.empty_like(state); sb = np.empty_like(state)
        mujoco.mj_getState(m, d, sa, mask); mujoco.mj_getState(m, b, sb, mask)
        exact &= np.array_equal(sa, sb)
    mujoco.mj_setState(m, d, state, mask); mujoco.mj_forward(m,d)
    return bool(exact)



class PandaController:
    def __init__(self, m, d):
        self.m, self.d = m, d
        self.joints = [m.joint(f'joint{i}').id for i in range(1, 8)]
        self.qi = m.jnt_qposadr[self.joints]; self.vi = m.jnt_dofadr[self.joints]
        self.ai = np.array([m.actuator(f'torq_j{i}').id for i in range(1, 8)])
        self.fi = [m.actuator('gripper_finger_joint1').id, m.actuator('gripper_finger_joint2').id]
        self.site = m.site('grip_site').id
        self.ikdata = mujoco.MjData(m)
        self.qhome = np.array([0, -.6, 0, -2.2, 0, 1.7, .8])
        self.target_rot = np.diag([1., -1., -1.])
        self.kp = np.array([400, 400, 400, 400, 200, 100, 80.])
        self.kd = np.array([45, 45, 45, 45, 25, 15, 12.])
    def ik(self, xyz, seed):
        d, m = self.ikdata, self.m
        d.qpos[:] = self.d.qpos
        def residual(q):
            d.qpos[self.qi] = q
            mujoco.mj_kinematics(m, d)
            rot = d.site_xmat[self.site].reshape(3, 3)
            return np.r_[np.asarray(xyz)-d.site_xpos[self.site], Rotation.from_matrix(self.target_rot @ rot.T).as_rotvec()]
        lo = m.jnt_range[self.joints,0]+.005; hi = m.jnt_range[self.joints,1]-.005
        result = least_squares(residual, np.clip(seed,lo,hi), bounds=(lo,hi), max_nfev=250,
                               xtol=1e-10, ftol=1e-10, gtol=1e-10)
        return result.x.copy(), float(np.linalg.norm(result.fun))
    def action(self, q, grip):
        force = self.kp*(q-self.d.qpos[self.qi]) - self.kd*self.d.qvel[self.vi] + self.d.qfrc_bias[self.vi]
        self.d.ctrl[self.ai] = np.clip(force, self.m.actuator_ctrlrange[self.ai, 0], self.m.actuator_ctrlrange[self.ai, 1])
        self.d.ctrl[self.fi] = [grip, -grip]


def run_arm(m, d, rec):
    ctrl = PandaController(m, d)
    # Only reset initialization writes qpos. All subsequent motion uses actuators.
    d.qpos[ctrl.qi] = ctrl.qhome
    d.qpos[m.jnt_qposadr[m.joint('finger_joint1').id]] = .04
    d.qpos[m.jnt_qposadr[m.joint('finger_joint2').id]] = -.04
    mujoco.mj_forward(m, d)
    rec.record_reset()
    start = np.array(BOOK_START); goal = np.array(BOOK_GOAL)
    grasp_z = start[2] + .08
    phases = [('approach', 3., [start[0], start[1], grasp_z+.15], .04),
              ('descend', 2., [start[0], start[1], grasp_z], .04),
              ('close', 1.2, [start[0], start[1], grasp_z], 0.),
              ('lift', 2., [start[0], start[1], grasp_z+.16], 0.),
              ('transfer', 3., [goal[0], goal[1], grasp_z+.16], 0.),
              ('lower', 2., [goal[0], goal[1], grasp_z+.005], 0.),
              ('release', 1.5, [goal[0], goal[1], grasp_z+.005], .04),
              ('retreat', 2., [goal[0], goal[1], grasp_z+.20], .04),
              ('settle', 2., [goal[0], goal[1], grasp_z+.20], .04)]
    iklog = []; qprev = ctrl.qhome.copy(); step = 0
    for phase, seconds, position, grip in phases:
        qgoal, error = ctrl.ik(position, qprev); iklog.append(dict(phase=phase, error=error, q=qgoal.tolist()))
        print(phase, 'IK error', round(error, 6), flush=True)
        for k in range(round(seconds / m.opt.timestep)):
            alpha = min(1., (k*m.opt.timestep)/max(.01, seconds*.8)); alpha = alpha*alpha*(3-2*alpha)
            ctrl.action(qprev*(1-alpha)+qgoal*alpha, grip)
            mujoco.mj_step(m, d); rec.audit()
            if step % 20 == 0: rec.sample(phase)
            step += 1
        qprev = qgoal
    bid = m.body('task_book').id; joint = m.joint('target_free').id
    vel = d.qvel[m.jnt_dofadr[joint]:m.jnt_dofadr[joint]+3]
    xyerr = float(np.linalg.norm(d.xpos[bid, :2] - goal[:2]))
    support = any('task_book' in (rec.owners[int(c.geom1)], rec.owners[int(c.geom2)]) and
        any(('explicit_desk' in rec.owners[int(g)] or rec.ids[int(g)]=='reference_table') for g in (c.geom1,c.geom2)) for c in d.contact)
    passed = rec.max_lift >= .08 and xyerr < .06 and np.linalg.norm(vel) < .03 and rec.bilateral_steps > 50 and support and rec.max_robot_penetration < .003 and rec.target_floor_hits == 0
    return dict(success=bool(passed), final_target_xyz=d.xpos[bid].tolist(), final_speed_m_s=float(np.linalg.norm(vel)),
        goal_xy_error_m=xyerr, max_lift_m=rec.max_lift, bilateral_contact_steps=rec.bilateral_steps,
        final_support_contact=bool(support), target_floor_contact_steps=rec.target_floor_hits, ik=iklog)


def occupancy_path(package, reference=False, radius=.38):
    if reference: return np.array([NAV_START[:2], NAV_GOAL])
    objects = json.loads((Path(package)/'objects.json').read_text())
    pitch = .05; shape = (117, 101); grid = np.zeros(shape, dtype=bool)
    xx, yy = np.meshgrid(np.arange(shape[0])*pitch, np.arange(shape[1])*pitch, indexing='ij')
    grid |= (xx < radius) | (xx > 5.8-radius) | (yy < radius) | (yy > 5-radius)
    for name, obj in objects.items():
        if name in ('task_book', 'explicit_area_rug') or name.startswith('leaning_book'): continue
        pose = np.asarray(obj['pose_z_up']); ext = np.asarray(obj['dimensions_local_m'])
        if pose[2,3]-ext[2]/2 > 1.5: continue
        local = np.stack([xx-pose[0,3], yy-pose[1,3]], axis=-1) @ pose[:2,:2]
        delta = np.maximum(np.abs(local)-ext[:2]/2, 0)
        grid |= np.linalg.norm(delta, axis=-1) < radius
    start = tuple(np.rint(np.array(NAV_START[:2])/pitch).astype(int)); goal = tuple(np.rint(np.array(NAV_GOAL)/pitch).astype(int))
    if grid[start] or grid[goal]: raise ValueError('Navigation start/goal violates declared clearance')
    todo = [(0, start)]; cost={start:0}; parent={}
    while todo:
        _, current=heapq.heappop(todo)
        if current==goal: break
        for dx,dy in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)):
            n=(current[0]+dx,current[1]+dy)
            if not (0<=n[0]<shape[0] and 0<=n[1]<shape[1]) or grid[n]:continue
            if dx and dy and (grid[current[0]+dx,current[1]] or grid[current[0],current[1]+dy]):continue
            c=cost[current]+np.hypot(dx,dy)
            if c<cost.get(n, float('inf')):
                cost[n]=c;parent[n]=current;heapq.heappush(todo,(c+np.linalg.norm(np.array(n)-goal),n))
    if goal not in parent: raise ValueError('No collision-clear path')
    cells=[goal]
    while cells[-1]!=start:cells.append(parent[cells[-1]])
    return np.array(cells[::-1])*pitch


def run_nav(m, d, rec, package, reference):
    path = occupancy_path(package, reference)
    bid = m.body('base_link').id
    basejoint = m.body_jntadr[bid]; qadr = m.jnt_qposadr[basejoint]
    # Reset yaw toward the first waypoint, before the episode starts.
    direction = path[min(1, len(path)-1)]-path[0]; angle=np.arctan2(direction[1],direction[0])
    d.qpos[qadr+3:qadr+7] = [np.cos(angle/2), 0, 0, np.sin(angle/2)]
    d.ctrl[m.actuator('lift').id] = -.2
    d.qpos[m.jnt_qposadr[m.joint('joint_lift').id]] = -.2
    mujoco.mj_forward(m, d)
    rec.record_reset()
    left=m.jnt_dofadr[m.joint('joint_left_wheel').id];right=m.jnt_dofadr[m.joint('joint_right_wheel').id]
    ai=m.actuator('forward').id;ti=m.actuator('turn').id
    index=1; stable=0; reached=False; step=0
    for step in range(round(60/m.opt.timestep)):
        pos=d.xpos[bid,:2]; rot=d.xmat[bid].reshape(3,3);yaw=np.arctan2(rot[1,0],rot[0,0])
        while index<len(path)-1 and np.linalg.norm(pos-path[index])<.18:index+=1
        delta=path[index]-pos;dist=np.linalg.norm(delta)
        goal_dist=np.linalg.norm(pos-NAV_GOAL); reached=goal_dist<.08
        angle_error=wrap(np.arctan2(delta[1],delta[0])-yaw)
        v=0. if reached else min(.22, .7*dist)*max(0.,np.cos(angle_error))
        w=0. if reached else np.clip(2.*angle_error,-.7,.7)
        wl=-(v-w*.3407/2)/.0508;wr=-(v+w*.3407/2)/.0508
        # Original forward/turn tendon torques; no imposed base motion.
        forward_error=(wl+wr-d.qvel[left]-d.qvel[right])/2
        turn_error=(wr-wl-d.qvel[right]+d.qvel[left])/2
        d.ctrl[ai]=np.clip((.3*(wl+wr)/2+.8*forward_error)/1.5,-1,1);d.ctrl[ti]=np.clip((.3*(wr-wl)/2+.8*turn_error)/1.5,-1,1)
        mujoco.mj_step(m,d);rec.audit()
        if step%20==0:rec.sample('navigate' if not reached else 'stop')
        speed=float(np.linalg.norm(d.qvel[m.jnt_dofadr[basejoint]:m.jnt_dofadr[basejoint]+2]))
        stable = stable+1 if reached and speed<.04 else 0
        if stable>=1000:break
    err=float(np.linalg.norm(d.xpos[bid,:2]-NAV_GOAL))
    return dict(success=bool(stable>=1000 and not rec.forbidden and rec.max_robot_penetration<.003),
        final_xyz=d.xpos[bid].tolist(),goal_xy_error_m=err,final_speed_m_s=speed,path=path.tolist(),stable_steps=stable,
        actual_wheel_rotation_rad=d.qpos[[m.jnt_qposadr[m.joint('joint_left_wheel').id],m.jnt_qposadr[m.joint('joint_right_wheel').id]]].tolist())


def run(package, output, task, variant='baseline', reference=False, physics_only=False):
    output=Path(output);started=time.monotonic()
    spec=make_task(package,output,task,variant,reference,physics_only)
    loadtime=time.monotonic();m=mujoco.MjModel.from_xml_path(str(output/'model.xml'));d=mujoco.MjData(m)
    compile_s=time.monotonic()-loadtime
    mujoco.mj_saveModel(m,str(output/'model.mjb'),None)
    rec=Recorder(m,d)
    result=run_arm(m,d,rec) if task=='pick_place' else run_nav(m,d,rec,package,reference)
    result.update(schema='scene-robot-episode/v1', task=spec, simulator=mujoco.__version__,
        model=bound(output/'model.xml'),compiled_model=bound(output/'model.mjb'),simulation_s=float(d.time),wall_seconds=time.monotonic()-started,compile_seconds=compile_s,
        max_contact_penetration_m=rec.max_penetration,max_robot_scene_penetration_m=rec.max_robot_penetration,
        forbidden_contact_steps=rec.forbidden,finite=bool(np.isfinite(d.qpos).all() and np.isfinite(d.qvel).all()),
        warning_counts=[int(x.number) for x in d.warning],exact_30_step_restore=restore_check(m,d),
        model_counts=dict(nq=m.nq,nv=m.nv,nu=m.nu,ngeom=m.ngeom,nmesh=m.nmesh,neq=m.neq),
        frame_semantics='50 Hz integration states after step; contact forces belong to solver at state time minus dt; rendered sensors recomputed at exact saved state')
    result['success'] &= result['finite'] and not any(result['warning_counts']) and result['exact_30_step_restore']
    rec.save(output);write_json(output/'result.json',result)
    print(json.dumps(result,indent=2),flush=True)
    return result
