"""D: constrained measured-object replanning with bounded physical arm segments."""
import numpy as np
import mujoco
from scipy.spatial.transform import Rotation
from .methods_r6 import FeedbackPlace, observe
from .pose_planner_static_r3 import solve


def relative_pose(runner):
    palm, wrist = runner.palm_pose()
    return wrist.T @ (runner.cyl_pos() - palm), wrist.T @ runner.data.xmat[runner.cyl_bid].reshape(3, 3)


def relative_error(reference, current):
    return (float(np.linalg.norm(current[0] - reference[0])),
            float(np.degrees(np.linalg.norm(Rotation.from_matrix(current[1] @ reference[1].T).as_rotvec()))))


def segment_clear(runner, target, samples=9):
    """Check scratch configurations; never modify runtime state or the model."""
    m, live, ik = runner.model, runner.data, runner.ik
    scratch = mujoco.MjData(m)
    initial = live.qpos.copy()
    rel, rel_r = relative_pose(runner)
    oa = int(m.jnt_qposadr[m.joint('red_block_joint').id])
    min_torque = float('inf')
    max_pen = 0.
    forbidden = []
    for fraction in np.linspace(0., 1., samples):
        scratch.qpos[:] = initial
        scratch.qvel[:] = 0.
        scratch.qpos[ik.qpos_idx] = initial[ik.qpos_idx] + fraction * (target - initial[ik.qpos_idx])
        mujoco.mj_kinematics(m, scratch)
        wrist = scratch.site_xmat[ik.site_id].reshape(3, 3)
        scratch.qpos[oa:oa + 3] = scratch.site_xpos[ik.site_id] + wrist @ rel
        mujoco.mju_mat2Quat(scratch.qpos[oa + 3:oa + 7], (wrist @ rel_r).ravel())
        mujoco.mj_forward(m, scratch)
        for ct in scratch.contact:
            bs = [m.body(int(m.geom_bodyid[g])).name for g in [ct.geom1, ct.geom2]]
            gn = [m.geom(g).name for g in [ct.geom1, ct.geom2]]
            foot = 'ground' in gn and any('ankle_roll' in b for b in bs)
            held = 'red_block' in bs and any('right_hand' in b for b in bs)
            robot = any('hand' in b or b.endswith('_link') for b in bs)
            max_pen = max(max_pen, float(-ct.dist))
            if robot and not (foot or held) and ct.dist < 0:
                forbidden.append(gn)
        aids, dofs = np.asarray(ik.act_idx), np.asarray(ik.dof_idx)
        margin = np.minimum(scratch.qfrc_bias[dofs] - m.actuator_ctrlrange[aids, 0],
                            m.actuator_ctrlrange[aids, 1] - scratch.qfrc_bias[dofs])
        min_torque = min(min_torque, float(min(margin)))
    return {'passed': not forbidden and max_pen <= .01 and min_torque >= 0.,
            'forbidden': forbidden, 'max_penetration_m': max_pen, 'arm_static_torque_margin_Nm': min_torque,
            'samples': samples}


class RecedingObjectPosePlace(FeedbackPlace):
    method = 'D_object_pose_planning'

    def __init__(self, pipeline, config, active):
        super().__init__(pipeline, config)
        self.active = active

    def event(self, runner, state):
        if state == 'unload' and self.active.get('governor') is not None:
            self.active['governor'].release()
        return super().event(runner, state)

    def align(self, runner, geo, target_xy=None):
        import instrument
        tr = instrument.ACTIVE_TRACE
        started = float(runner.data.time)
        target_xy = np.asarray(target_xy, float)
        for replan in range(48):
            obs = observe(runner)
            if obs['finger_contacts'] < 2 and obs['load_fraction'] < .9:
                raise self.p.EpisodeAborted('D_measured_grasp_lost_before_plan')
            if obs['penetration_m'] > .01:
                raise self.p.EpisodeAborted('D_measured_contact_limit_before_plan')
            if runner.data.time - started > 18.:
                raise self.p.EpisodeAborted('D_alignment_time_bound')
            if obs['tilt_deg'] <= 5. and np.linalg.norm(runner.cyl_pos()[:2] - target_xy) < .012:
                return runner.palm_pose()[1]
            result = solve(runner, geo, target_xy, allow_stance=False)
            tr.append('planner/physics_row', tr.n)
            tr.append('planner/variables', result['variables'])
            tr.append('planner/diagnostics', [result['cost'], result['iterations'], float(result['valid']), result['min_constraint']])
            if not result['valid']:
                raise self.p.EpisodeAborted('D_measured_object_pose_plan_infeasible')
            actual = runner.data.qpos[runner.ik.qpos_idx].copy()
            delta = np.asarray(result['variables'][:-2]) - actual
            target = actual + delta * min(1., .045 / max(float(np.max(abs(delta))), 1e-12))
            check = segment_clear(runner, target)
            tr.append('planner/segment_constraints', [float(check['passed']), check['max_penetration_m'], check['arm_static_torque_margin_Nm']])
            if not check['passed']:
                raise self.p.EpisodeAborted('D_local_path_constraint_failed')
            reference = relative_pose(runner)
            interruption = {'reason': 0}
            def monitor():
                current = observe(runner)
                translation, rotation = relative_error(reference, relative_pose(runner))
                reason = (1 if current['finger_contacts'] < 2 and current['load_fraction'] < .9 else
                          2 if current['penetration_m'] > .01 else
                          3 if translation > .004 or rotation > 6. else 0)
                if reason:
                    interruption['reason'] = reason
                    tr.append('planner/interrupt', [tr.n, reason, translation, rotation, current['finger_contacts']])
                return bool(reason)
            runner.move_tag = 'D_measured_object_segment'
            runner.ramp_to(target, rate=.003, settle=0., sync=True, on_step=monitor)
            # An interrupted ramp leaves its actual command in place; replan from
            # the measured state. Loss of contact or excess penetration aborts.
            if interruption['reason'] in [1, 2]:
                raise self.p.EpisodeAborted('D_grasp_or_contact_limit_during_segment')
        raise self.p.EpisodeAborted('D_measured_replan_count_bound')


def install(pipeline, config):
    import run, instrument
    from .contact_finger_hold import MeasuredFingerHold
    from .measured_capture import install as capture_install
    active = {'enabled': False, 'governor': None}
    raw_step = mujoco.mj_step
    def step(m, d, *args, **kwargs):
        if active['enabled']:
            if active['governor'] is None:
                active['governor'] = MeasuredFingerHold(m)
            telemetry = active['governor'].apply(m, d)
            trace = instrument.ACTIVE_TRACE
            trace.append('finger_governor/control', telemetry)
            trace.append('finger_governor/physics_row', trace.n)
        return raw_step(m, d, *args, **kwargs)
    mujoco.mj_step = step
    capture_install(pipeline, active)
    squeeze = pipeline.squeeze
    def measured_squeeze(runner, *args, **kwargs):
        result = squeeze(runner, *args, **kwargs)
        active['governor'].hold(runner.model, runner.data)
        return result
    pipeline.squeeze = measured_squeeze
    old_ctrl = run.G1Controller.step
    def controller_step(ctrl):
        vx, vy, wz = config.get('velocity_cap', [.4, .2, .3])
        ctrl.lin_vel_x = float(np.clip(ctrl.lin_vel_x, -vx, vx))
        ctrl.lin_vel_y = float(np.clip(ctrl.lin_vel_y, -vy, vy))
        ctrl.ang_vel_z = float(np.clip(ctrl.ang_vel_z, -wz, wz))
        return old_ctrl(ctrl)
    run.G1Controller.step = controller_step
    pipeline.place_object = RecedingObjectPosePlace(pipeline, config, active)
    return {'method': RecedingObjectPosePlace.method, 'maximum_segment_joint_delta_rad': .045,
            'measured_transform_replan_threshold_m_deg': [.004, 6.], 'maximum_replans': 48,
            'stance_fixed_after_actual_navigation': True, 'measured_encoder_hold_after_capture': True,
            'plant_unchanged': True, 'dynamic_validated': False}
