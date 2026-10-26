"""Distinct D planning: measured tripod acquisition, upright carry and placement.

All live motion goes through retained actuators and body policies. Optimizers
only use scratch data. No dynamics parameter or runtime pose writes occur.
"""
import numpy as np
import mujoco
from .work import c
from .planned_tripod_r2 import plan, PlannedFingerServo, contact_geometry
from .object_pose_receding import RecedingObjectPosePlace, segment_clear, relative_pose, relative_error
from .pose_planner_static_r4 import solve
from .tripod_recontact_control import restore_tripod


def loaded_forbidden(m, d):
    root = m.body('base').id; obj = m.body('red_block').id
    for index, ct in enumerate(d.contact):
        bodies = [int(m.geom_bodyid[g]) for g in [ct.geom1, ct.geom2]]
        names = [m.body(b).name for b in bodies]
        geoms = [m.geom(g).name for g in [ct.geom1, ct.geom2]]
        robot = False
        for body in bodies:
            while body and body != root:
                body = int(m.body_parentid[body])
            robot |= body == root
        allowed = ('ground' in geoms and any('ankle_roll' in x for x in names)) or (
            obj in bodies and any('hand' in x for x in names))
        if not robot or allowed:
            continue
        force = np.zeros(6); mujoco.mj_contactForce(m, d, index, force)
        if ct.dist < -1e-6 or np.linalg.norm(force[:3]) > 1e-4:
            return geoms
    return None


class ObjectPoseMotion:
    def __init__(self, pipeline): self.p = pipeline

    def move(self, runner, goal):
        import instrument
        tr = instrument.ACTIVE_TRACE; started = float(runner.data.time)
        geo = self.p.scene_geometry(runner.model)
        goal = np.asarray(goal).copy()
        for _ in range(48):
            restore_tripod(runner, self.p)
            if np.linalg.norm(runner.cyl_pos() - goal) < .012 and runner.cyl_tilt_deg() <= 5.:
                return
            if runner.data.time - started > 18.:
                raise self.p.EpisodeAborted('D_carry_pose_time_bound')
            result = solve(runner, geo, goal[:2], target_xyz=goal)
            tr.append('carry_planner/physics_row', tr.n)
            tr.append('carry_planner/variables', result['variables'])
            tr.append('carry_planner/diagnostics', [result['cost'], result['iterations'], float(result['valid']), result['object_position_error_m']])
            if not result['valid']:
                raise self.p.EpisodeAborted('D_carry_pose_plan_infeasible')
            actual = runner.data.qpos[runner.ik.qpos_idx].copy()
            delta = np.asarray(result['variables'][:-2]) - actual
            target = actual + delta * min(1., .045 / max(np.max(abs(delta)), 1e-12))
            check = segment_clear(runner, target)
            if not check['passed']:
                raise self.p.EpisodeAborted('D_carry_segment_constraint')
            reference = relative_pose(runner)
            def changed():
                shift, angle = relative_error(reference, relative_pose(runner))
                grasp = contact_geometry(runner.model, runner.data, runner.cyl_bid)
                return shift > .004 or angle > 6. or grasp['rank'] != 6 or grasp['digits'] != ['index', 'middle', 'thumb']
            runner.ramp_to(target, rate=.003, settle=0., sync=True, on_step=changed)
        raise self.p.EpisodeAborted('D_carry_pose_replan_bound')


class PlannedPlace(RecedingObjectPosePlace):
    def align(self, runner, geo, target_xy=None):
        goal = runner.cyl_pos().copy(); goal[:2] = target_xy
        goal[2] = max(goal[2], geo['blue_top_z'] + self.p.ep.CYL_HALF + .065)
        ObjectPoseMotion(self.p).move(runner, goal)
        return runner.palm_pose()[1]

    def event(self, runner, state):
        if state == 'recover' and self.active.get('governor') is not None:
            self.active['governor'].reclose()
        return super().event(runner, state)


def install(pipeline, config):
    import run, instrument
    from ik import sim
    p = pipeline
    tr = instrument.ACTIVE_TRACE
    active = {'enabled': False, 'governor': None, 'desired': None, 'captured': False, 'rank_lost_since': None}
    template = c.read(config['tripod_template'])['selected']
    carry_plan = c.read(config['tripod_carry_plan'])
    assert carry_plan['passed'] and carry_plan['selected']['valid']
    original_step = mujoco.mj_step
    def step(m, d, *args, **kwargs):
        if active['enabled']:
            servo = active['governor']
            desired = d.ctrl[servo.aids].copy() if servo.released else active['desired']
            telemetry = servo.apply(m, d, desired)
            tr.append('finger_governor/physics_row', tr.n)
            tr.append('finger_governor/control', telemetry)
        return original_step(m, d, *args, **kwargs)
    mujoco.mj_step = step

    raw_monitor = p.HybridRunner._monitor
    def monitor(runner):
        raw_monitor(runner)
        if tr.max_penetration > .01:
            raise p.EpisodeAborted('D_whole_body_penetration_limit')
        bad = loaded_forbidden(runner.model, runner.data)
        if bad:
            tr.append('D_abort/forbidden_geom_ids', [runner.model.geom(x).id for x in bad])
            raise p.EpisodeAborted('D_whole_body_forbidden_contact')
        if active['captured'] and not active['governor'].released:
            geometry = contact_geometry(runner.model, runner.data, runner.cyl_bid)
            good = geometry['rank'] == 6 and geometry['digits'] == ['index', 'middle', 'thumb']
            if good:
                active['rank_lost_since'] = None
            elif active['rank_lost_since'] is None:
                active['rank_lost_since'] = float(runner.data.time)
            elif runner.data.time - active['rank_lost_since'] >= (.8 if getattr(runner, '_D_reacquiring', False) else .04):
                raise p.EpisodeAborted('D_planned_wrench_rank_lost')
    p.HybridRunner._monitor = monitor

    old_fly = p.fly_grasp_azimuths
    def fly(runner, *args, **kwargs):
        R_s, tilt, sign, details = old_fly(runner, *args, **kwargs)
        measured = plan(runner, template)
        c.write(tr.job / 'D_MEASURED_TRIPOD_PLAN.json', measured)
        if not measured['valid']:
            raise p.EpisodeAborted('D_measured_tripod_plan_infeasible')
        servo = PlannedFingerServo(runner.model)
        finger_start = np.asarray(measured['initial_finger_rad'])
        finger_target = np.asarray(measured['finger_target_rad'])
        arm_start = runner.q_cmd.copy(); arm_target = np.asarray(measured['arm_target_rad'])
        duration = max(np.max(abs(arm_target - arm_start)) / .18,
                       np.max(abs(finger_target - finger_start)) / .18, .4)
        if duration > 5.8:
            raise p.EpisodeAborted('D_tripod_plan_motion_time')
        active.update(enabled=True, governor=servo, desired=finger_start.copy())
        runner._D_tripod_servo = servo; runner._D_tripod_desired = active['desired']
        runner.grip_cap = None; runner.hold_tol = None
        runner.grip_alpha = runner.grip_alpha_f = 1.
        stable = 0; started = float(runner.data.time)
        while runner.data.time - started < 6.5:
            fraction = min(1., (runner.data.time - started + runner.model.opt.timestep) / duration)
            runner.q_cmd = arm_start + fraction * (arm_target - arm_start)
            active['desired'][:] = finger_start + fraction * (finger_target - finger_start)
            runner.step_once()
            geometry = contact_geometry(runner.model, runner.data, runner.cyl_bid)
            good = geometry['digits'] == ['index', 'middle', 'thumb'] and geometry['rank'] == 6 and runner.cyl_tilt_deg() < 10.
            stable = stable + 1 if good and fraction == 1. else 0
            if tr.n % 80 == 0:
                tr.append('tripod/observation', [tr.n, fraction, geometry['contacts'], geometry['rank'], runner.cyl_tilt_deg()])
            if stable * runner.model.opt.timestep >= .2:
                active['captured'] = True
                break
        if not active['captured']:
            raise p.EpisodeAborted('D_tripod_capture_not_stable')
        runner.trace_slip = False
        return runner.palm_pose()[1], 0., sign, {**details, 'D_tripod_planned_capture': True}
    p.fly_grasp_azimuths = fly

    def close_and_lift(runner, R_s, cyl_rest, grip=None, lift=None, verbose=True, offset=None, lift_R=None):
        assert active['captured']
        palm, wrist = runner.palm_pose()
        target = palm + [0., 0., p.LIFT_M if lift is None else lift]
        arm, error, rotation = runner.ik.solve(runner.data, target, wrist, iters=100)
        if error > .003 or rotation > 1. or not segment_clear(runner, arm, samples=81)['passed']:
            raise p.EpisodeAborted('D_upright_lift_path_infeasible')
        runner.move_tag = 'D_planned_upright_lift'
        runner.goto(target, wrist, rounds=2, rate=.004, settle=0.)
        runner.run(.5)
        rise = float(runner.cyl_pos()[2] - cyl_rest[2])
        return {'lift_rise_m': rise, 'n_finger_contacts': runner.finger_contacts(),
                'n_finger_contacts_lifted': runner.finger_contacts(),
                'captured': rise > .10 and contact_geometry(runner.model, runner.data, runner.cyl_bid)['rank'] == 6,
                'close_tilt_deg': runner.cyl_tilt_deg(), 'D_fixed_encoder_tripod': True}
    p.close_and_lift = close_and_lift
    p.cradle_frame = lambda wrist, tilt: (wrist.copy(), wrist.copy(), 0.)

    old_goto = sim.Runner.goto
    def goto(runner, target, wrist, *args, **kwargs):
        if getattr(runner, 'move_tag', '') == 'tuck' and active['captured']:
            palm, _ = runner.palm_pose()
            desired = p.ep.pelvis_to_world(runner.data, carry_plan['selected']['palm_pelvis_local_m'])
            ObjectPoseMotion(p).move(runner, runner.cyl_pos() + desired - palm)
            return float(np.linalg.norm(runner.palm_pose()[0] - desired))
        return old_goto(runner, target, wrist, *args, **kwargs)
    sim.Runner.goto = goto

    original_route = p.walk_to_pose_around
    def route(runner, goal_xy, goal_yaw, geo, tag='route'):
        if tag != 'transport':
            return original_route(runner, goal_xy, goal_yaw, geo, tag=tag)
        brown_west = geo['brown_center'][0] - geo['brown_half'][0]
        blue_west = geo['blue_center'][0] - geo['blue_half'][0]
        here = runner.data.qpos[:2].copy()
        if here[0] >= brown_west:
            raise p.EpisodeAborted('D_west_route_start_not_outside_table')
        west = min(brown_west, blue_west) - .36
        goal = np.array([blue_west - .36, geo['blue_center'][1] + .15])
        waypoints = [np.array([west, here[1]]), np.array([west, goal[1]])]
        if abs(west - goal[0]) > .07:
            waypoints.append(goal)
        for waypoint in waypoints:
            tr.append('D_route/physics_row', tr.n); tr.append('D_route/goal', waypoint)
            p.ep.walk_to(runner, waypoint, goal_yaw=-.35, timeout=20.)
            runner.ctrl.lin_vel_x = runner.ctrl.lin_vel_y = runner.ctrl.ang_vel_z = 0.
            runner.run(1.)
        angle = float(p.ep.base_yaw(runner.data)) + .35
        return float(np.linalg.norm(runner.data.qpos[:2] - goal)), float(np.degrees(np.arctan2(np.sin(angle), np.cos(angle))))
    p.walk_to_pose_around = route

    original_ctrl = run.G1Controller.step
    def control(ctrl):
        for attribute, limit in zip(['lin_vel_x', 'lin_vel_y', 'ang_vel_z'], config['velocity_cap']):
            setattr(ctrl, attribute, float(np.clip(getattr(ctrl, attribute), -limit, limit)))
        return original_ctrl(ctrl)
    run.G1Controller.step = control
    p.place_object = PlannedPlace(p, config, active)
    return {'method': 'D_object_pose_planning', 'tripod_capture': 'measured7arm+3digit collision-constrained plan',
            'carry': 'measured upright object-pose optimization, no fixed cradle roll',
            'route': 'explicit west-side retreat and transport,36cm table clearance',
            'placement': 'measured object-pose receding optimization and supported release',
            'plant_unchanged': True, 'research_only': True, 'dynamic_full_task_qualified': False}
