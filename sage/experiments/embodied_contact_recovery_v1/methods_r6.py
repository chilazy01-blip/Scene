"""Task-layer methods, preserving the plant, actuators and low-level policies.

C is measured contact/load feedback. D is a constrained object-pose optimizer
with measured receding-horizon replanning. Both use the same logged finger
preload governor and retain cumulative canonical-method failure counts.
"""
import numpy as np
import mujoco
from scipy.spatial.transform import Rotation


def observe(runner):
    m, d = runner.model, runner.data
    obj = m.body('red_block').id
    target = m.geom('table_white_top').id
    support = np.zeros(3)
    fingers = 0
    penetration = 0.
    for i, ct in enumerate(d.contact):
        a, b = int(ct.geom1), int(ct.geom2)
        if int(m.geom_bodyid[a]) != obj and int(m.geom_bodyid[b]) != obj:
            continue
        penetration = max(penetration, -float(ct.dist))
        other = b if int(m.geom_bodyid[a]) == obj else a
        if other == target:
            force = np.zeros(6)
            mujoco.mj_contactForce(m, d, i, force)
            # MuJoCo contact force is on geom2; frame rows are contact axes.
            support += ct.frame.reshape(3,3).T @ force[:3] * (1 if int(m.geom_bodyid[b]) == obj else -1)
        if 'right_hand' in m.body(int(m.geom_bodyid[other])).name:
            fingers += 1
    velocity = np.zeros(6)
    mujoco.mj_objectVelocity(m, d, mujoco.mjtObj.mjOBJ_BODY, obj, velocity, 0)
    rot = d.xmat[obj].reshape(3,3)
    return {'time': float(d.time), 'tilt_deg': float(np.degrees(np.arccos(np.clip(rot[2,2],-1,1)))),
            'speed': float(np.linalg.norm(velocity[3:])), 'angular_speed': float(np.linalg.norm(velocity[:3])),
            'support_N': float(support[2]), 'load_fraction': float(max(0,support[2])/(m.body_mass[obj]*9.81)),
            'finger_contacts': fingers, 'penetration_m': penetration,
            'object_xyz': d.xpos[obj].copy().tolist(), 'finger_actual': d.actuator_force[[a for a in range(m.nu) if m.actuator(a).name.startswith('right_hand')]].copy().tolist()}


def release_ready(obs):
    return (obs['tilt_deg'] <= 5 and obs['load_fraction'] >= .90
            and obs['speed'] <= .025 and obs['angular_speed'] <= .15
            and obs['penetration_m'] <= .01)


class FeedbackPlace:
    method = 'C_measured_contact_recovery'
    def __init__(self, pipeline, config):
        self.p = pipeline
        self.config = config

    def event(self, runner, state):
        import instrument
        obs = observe(runner)
        trace = instrument.ACTIVE_TRACE
        if trace is not None:
            trace.append('feedback/physics_row', trace.n)
            trace.append('feedback/state', self.states.index(state))
            trace.append('feedback/observation', [obs[k] for k in
                         ['time','tilt_deg','speed','angular_speed','support_N','load_fraction','finger_contacts','penetration_m']])
        return obs

    states = ['align','approach','seat','unload','open','verify','recover','withdraw','failed']

    def align(self, runner, geo, target_xy=None):
        """Use the measured object-to-palm transform for small orientation corrections."""
        palm, wrist = runner.palm_pose()
        obj = runner.data.xmat[runner.cyl_bid].reshape(3,3).copy()
        # Correct only the tilt, retaining measured object yaw.
        yaw = np.arctan2(obj[1,0],obj[0,0])
        desired = Rotation.from_euler('z',yaw).as_matrix()
        corrected = desired @ obj.T @ wrist
        relative = wrist.T @ (runner.cyl_pos()-palm)
        goal = runner.cyl_pos().copy()
        if target_xy is not None:
            goal[:2] = target_xy
        goal[2] = max(goal[2], geo['blue_top_z'] + self.p.ep.CYL_HALF + .06)
        runner.move_tag = 'C_measured_object_align'
        runner.goto(goal-corrected@relative,corrected,rounds=2,rate=.002,settle=.25)
        return corrected

    def __call__(self, runner, geo, R_c, T, phase=None):
        T['contact_method'] = self.method
        T['contact_stages'] = []
        runner.trace_slip = False
        target = np.asarray(geo['blue_center'][:2],float)
        # The nearest interior point keeps the whole upright cylinder away from edges.
        lo = target - np.asarray(geo['blue_half'][:2]) + .08
        hi = target + np.asarray(geo['blue_half'][:2]) - .08
        target = np.clip(runner.cyl_pos()[:2],lo,hi)
        T['place_target'] = [*target,geo['blue_top_z']+self.p.ep.CYL_HALF]
        for recovery in range(3):
            T['reseat_count'] = recovery
            self.event(runner,'align' if recovery == 0 else 'recover')
            wrist = self.align(runner,geo,target)
            settled = 0.
            start = runner.data.time
            while runner.data.time-start < 10:
                obs = self.event(runner,'seat')
                if release_ready(obs):
                    settled += .04
                    runner.run(.04)
                    if settled >= .2: break
                    continue
                settled = 0.
                palm, actual_R = runner.palm_pose()
                dz = -.001 if obs['load_fraction'] < .9 else 0.
                if obs['penetration_m'] > .009: dz = .001
                if obs['tilt_deg'] > 8 and obs['load_fraction'] > .1: break
                q, resid, _ = runner.ik.solve(runner.data,palm+np.array([0,0,dz]),wrist,iters=80)
                if resid > .025: break
                runner.ramp_to(q,rate=.001,settle=.04)
            if settled < .2:
                T['contact_stages'].append({'state':'seat_not_stable',**observe(runner)})
                if recovery < 2:
                    palm,_ = runner.palm_pose()
                    runner.goto(palm+np.array([0,0,.025]),wrist,rounds=1,rate=.002,settle=.15)
                    continue
                self.event(runner,'failed')
                T['abort']='contact_seat_not_stable'
                raise self.p.EpisodeAborted('contact_seat_not_stable')
            # Each small command decrement requires renewed measured support.
            released = True
            for _ in range(24):
                obs=self.event(runner,'unload')
                if not release_ready(obs):
                    released=False
                    break
                t=max(0.,runner.grip_alpha-.05)
                f=max(0.,runner.grip_alpha_f-.05)
                runner.grip_alpha=t
                runner.grip_alpha_f=f
                runner.run(.08)
                if t == 0 and f == 0: break
            if not released:
                T['contact_stages'].append({'state':'unload_unstable',**observe(runner)})
                if recovery < 2:
                    runner.set_grip(.65,seconds=.3)
                    continue
                raise self.p.EpisodeAborted('contact_unload_unstable')
            # Reaching grip_alpha0 does not imply that encoders/contact reached open.
            open_start=runner.data.time
            while runner.data.time-open_start<8.:
                obs=self.event(runner,'unload')
                if not release_ready(obs):raise self.p.EpisodeAborted('contact_opening_support_lost')
                runner.grip_alpha=runner.grip_alpha_f=0.
                open_error=max(abs(float(runner.data.qpos[qa])) for qa in runner._fq)
                if obs['finger_contacts']==0 and open_error<.05:break
                runner.run(.04)
            else:raise self.p.EpisodeAborted('measured_finger_open_timeout')
            obs=self.event(runner,'open')
            palm,_=runner.palm_pose()
            runner.goto(palm+np.array([0,0,.14]),wrist,rounds=1,rate=.002,settle=.2)
            good=True
            for _ in range(25):
                runner.run(.04)
                obs=self.event(runner,'verify')
                good &= release_ready(obs) and obs['finger_contacts']==0
            T['measured_release_passed']=bool(good)
            if not good: raise self.p.EpisodeAborted('contact_terminal_unstable')
            if phase: phase('released')
            T['touched']=True
            return


class ObjectPosePlace(FeedbackPlace):
    method = 'D_object_pose_planning'

    def align(self, runner, geo, target_xy=None):
        from scipy.optimize import minimize
        m,d,ik=runner.model,runner.data,runner.ik
        palm,wrist=runner.palm_pose()
        relative_p=wrist.T@(runner.cyl_pos()-palm)
        relative_R=wrist.T@d.xmat[runner.cyl_bid].reshape(3,3)
        scratch=mujoco.MjData(m)
        scratch.qpos[:]=d.qpos
        scratch.qvel[:]=0
        base=d.qpos[:2].copy()
        seed=d.qpos[ik.qpos_idx].copy()
        goal=runner.cyl_pos().copy()
        goal[:2]=target_xy
        goal[2]=max(goal[2],geo['blue_top_z']+self.p.ep.CYL_HALF+.065)
        obj_yaw=np.arctan2(d.xmat[runner.cyl_bid].reshape(3,3)[1,0],d.xmat[runner.cyl_bid].reshape(3,3)[0,0])
        desired_R=Rotation.from_euler('z',obj_yaw).as_matrix()
        aids=np.asarray(ik.act_idx)
        dofs=np.asarray(ik.dof_idx)
        def fk(x):
            scratch.qpos[:]=d.qpos
            scratch.qpos[ik.qpos_idx]=x[:-2]
            scratch.qpos[:2]=base+x[-2:]
            mujoco.mj_kinematics(m,scratch)
            mujoco.mj_comPos(m,scratch)
            rw=scratch.site_xmat[ik.site_id].reshape(3,3)
            op=scratch.site_xpos[ik.site_id]+rw@relative_p
            return op,rw@relative_R,rw
        def cost(x):
            pos,rot,_=fk(x)
            orient=Rotation.from_matrix(desired_R@rot.T).as_rotvec()
            return 1500*np.sum((pos-goal)**2)+8*np.sum(orient**2)+.15*np.sum((x[:-2]-seed)**2)+20*np.sum(x[-2:]**2)
        def constraints(x):
            pos,rot,_=fk(x)
            # Measured full-body support envelope and static actuator feasibility.
            feet=np.array([scratch.xpos[m.body(side+'_ankle_roll_link').id,:2] for side in ['left','right']])
            com=scratch.subtree_com[m.body('pelvis').id,:2] if any(m.body(i).name=='pelvis' for i in range(m.nbody)) else scratch.subtree_com[1,:2]
            stability=np.r_[com-(feet.min(axis=0)-.07),feet.max(axis=0)+.07-com]
            obj_adr=int(m.jnt_qposadr[m.joint('red_block_joint').id])
            scratch.qpos[obj_adr:obj_adr+3]=pos
            quat=np.zeros(4);mujoco.mju_mat2Quat(quat,rot.ravel())
            scratch.qpos[obj_adr+3:obj_adr+7]=quat
            mujoco.mj_forward(m,scratch)
            collision_margin=1.
            for ct in scratch.contact:
                bodies=[m.body(int(m.geom_bodyid[g])).name for g in [ct.geom1,ct.geom2]]
                ground=any(m.geom(g).name=='ground' for g in [ct.geom1,ct.geom2])
                foot=any('ankle_roll' in b for b in bodies)
                held='red_block' in bodies and any('right_hand' in b for b in bodies)
                tolerance=.01 if ground and foot else (.008 if held else 0.)
                collision_margin=min(collision_margin,float(ct.dist)+tolerance)
            torque=np.minimum(scratch.qfrc_bias[dofs]-m.actuator_ctrlrange[aids,0],m.actuator_ctrlrange[aids,1]-scratch.qfrc_bias[dofs])
            table_clear=pos[2]-geo['blue_top_z']-self.p.ep.CYL_HALF-.02
            return np.r_[stability,torque,table_clear,rot[2,2]-np.cos(np.radians(5)),collision_margin]
        result=minimize(cost,np.r_[seed,0.,0.],method='SLSQP',
                        bounds=list(zip(ik.lo,ik.hi))+[(-.12,.12),(-.12,.12)],
                        constraints=[{'type':'ineq','fun':constraints}],
                        options={'maxiter':65,'ftol':1e-7})
        pos,rot,planned_wrist=fk(result.x)
        valid=bool(result.success and np.min(constraints(result.x))>=-1e-5 and np.linalg.norm(pos-goal)<.025)
        self.event(runner,'align')
        import instrument
        tr=instrument.ACTIVE_TRACE
        tr.append('planner/variables',result.x)
        tr.append('planner/diagnostics',[float(result.fun),float(result.nit),float(valid),float(np.min(constraints(result.x)))])
        if not valid:
            raise self.p.EpisodeAborted('object_pose_plan_infeasible')
        # Stance is an optimization variable, executed by the retained dynamic walker.
        if np.linalg.norm(result.x[-2:])>.02:
            yaw=float(self.p.ep.base_yaw(d))
            self.p.walk_to_pose_around(runner,base+result.x[-2:],yaw,geo,tag='D_planned_stance')
            # Re-solve arm pose against the measured stance; no teleportation.
            runner.move_tag='D_object_pose_replan'
            runner.goto(goal-planned_wrist@relative_p,planned_wrist,rounds=2,rate=.002,settle=.25)
        else:
            runner.move_tag='D_object_pose_plan'
            runner.ramp_to(result.x[:-2],rate=.002,settle=.25)
        return planned_wrist


def install(pipeline, config):
    """Wrap only task-layer commands; no plant parameter changes."""
    import instrument
    from ik import sim
    import run
    from .contact_finger_governor_r2 import ContactFingerGovernor
    from .measured_capture import install as capture_install
    tracer=instrument.ACTIVE_TRACE
    active={'enabled':False,'governor':None}
    raw_step=mujoco.mj_step
    def step(m,d,*a,**kw):
        if active['enabled']:
            if active['governor'] is None:active['governor']=ContactFingerGovernor(m)
            telemetry=active['governor'].apply(m,d)
            tracer.append('finger_governor/control',telemetry)
            tracer.append('finger_governor/physics_row',tracer.n)
        return raw_step(m,d,*a,**kw)
    mujoco.mj_step=step
    capture_install(pipeline,active)
    original_ctrl_step=run.G1Controller.step
    def controller_step(ctrl):
        vx,vy,wz=config.get('velocity_cap',[.35,.2,.3])
        ctrl.lin_vel_x=float(np.clip(ctrl.lin_vel_x,-vx,vx))
        ctrl.lin_vel_y=float(np.clip(ctrl.lin_vel_y,-vy,vy))
        ctrl.ang_vel_z=float(np.clip(ctrl.ang_vel_z,-wz,wz))
        return original_ctrl_step(ctrl)
    run.G1Controller.step=controller_step
    place=ObjectPosePlace if config.get('method')=='D_object_pose_planning' else FeedbackPlace
    pipeline.place_object=place(pipeline,config)
    return {'method':place.method,'finger_preload_rad':config.get('finger_preload_rad',.03),
            'plant_unchanged':True,'release_requires_measured_support':True,'max_reseats':2,'free_finger_speed_rps':.20,'contact_preload_rad':.03,'release_waits_for_measured_open':True,'opposed_capture_measured':True}
