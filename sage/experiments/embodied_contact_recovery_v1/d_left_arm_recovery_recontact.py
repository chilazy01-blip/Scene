"""Bounded upright carry motion from the actually acquired D tripod grasp."""
import os
import sys
import traceback
from pathlib import Path
import numpy as np
import h5py
import mujoco
from .work import E, R, c, finish
from . import trace_r4
from .leg_interpolation import LegInterpolation
from .planned_tripod_r2 import PlannedFingerServo, CLOSED, contact_geometry
from .tripod_task_control import loaded_forbidden


class WindowComplete(BaseException): pass


def main(config_path):
    cfg = c.read(config_path)
    approval = c.read(E / 'DIAGNOSTIC_WINDOW_REPLAN_APPROVAL.json')
    assert approval['approved'] and approval['proposal_sha256'] == c.sha(E / 'DIAGNOSTIC_WINDOW_REPLAN_PROPOSAL.json')
    extension = c.read(E / 'D_RECOVERY_EXTENSION_APPROVAL.json')
    assert extension['approved'] and extension['proposal_sha256'] == c.sha(E / 'D_RECOVERY_EXTENSION_PROPOSAL.json')
    work = Path(os.environ['CONTINUOUS_JOB_DIR']); folder = Path(cfg['source_folder'])
    start, steps = cfg['start_row'], cfg['saved_steps']; assert start % 8 == 0 and 0 < steps <= 4000
    os.environ.update(NP_ROOT=str(R), NP_JOB=str(work))
    sys.path.insert(0, str(R / 'tools')); sys.path.insert(0, str(R / 'branches/A/source'))
    sys.modules['instrument'] = trace_r4
    c.write(work / 'USAGE.json', {k: 0 for k in c.read(work / 'REQUEST.json')['reservation']})
    tr = trace_r4.Trace(work / 'episode', 'diagnostic'); tr.install()
    error = None; abort = None; completed = False; reached = False; first_error = None
    try:
        from .target_adapter_r4 import install
        install('A', 'gain_translation', work / 'episode')
        import run
        from ik import pipeline as p, sim
        from .common_control import install as common_install
        m = mujoco.MjModel.from_binary_path(str(folder / 'MODEL.mjb')); d = mujoco.MjData(m)
        with h5py.File(folder / 'TRACE.h5', 'r') as f:
            mujoco.mj_setState(m, d, f['substep/integration_before'][start], mujoco.mjtState.mjSTATE_INTEGRATION)
            previous = f['interpolation/applied'][start - 1]; requested = f['interpolation/requested'][start - 1]
            expected = f['substep/ctrl'][start]
            policy = f['policy/walker_onnx']; index = int(np.searchsorted(policy['physics_row'][:], start))
            assert int(policy['physics_row'][index]) == start
            observation = policy['input'][next(iter(policy['input']))][index].reshape(-1)
            history = f['finger_governor/control'][:start]
        mujoco.mj_forward(m, d)
        source = R / 'branches/A/source'
        policies = [run.ONNXPolicy(str(source / (x + '.onnx'))) for x in ['walker', 'croucher', 'rotator']]
        ctrl = run.G1Controller(m, d, *policies, c.read(source / 'model_config.json'))
        ctrl.last_action = observation[-32:-3].copy()
        ctrl.lin_vel_x, ctrl.lin_vel_y, ctrl.ang_vel_z = map(float, observation[-3:])
        ids = [i for i, name in enumerate(ctrl.joint_names) if any(x in name for x in ['hip', 'knee', 'ankle'])]
        ctrl._contact_leg_interpolation = LegInterpolation(ids, 8); ctrl._contact_leg_interpolation.apply(previous)
        common_install(cfg)
        original_overlay = run.G1Controller.arm_overlay
        start_time = float(d.time)
        def left_clearance(controller, target, proj_gravity=None):
            result = original_overlay(controller, target, proj_gravity)
            fraction = min(1., max(0., float(d.time)-start_time)/2.)
            result[controller.joint_names.index('left_elbow_joint')] += -.10 - .10*fraction
            return result
        run.G1Controller.arm_overlay = left_clearance
        original_controller_step = run.G1Controller.step
        from .velocity_transition import VelocityTransition
        transition = VelocityTransition(cfg['velocity_cap'], cfg['acceleration_cap'])
        transition.issued[:] = observation[-3:]  # Restore the actually issued policy command, including residual approach motion.
        def bounded_velocity(controller):
            attributes = ['lin_vel_x','lin_vel_y','ang_vel_z']
            requested_velocity = np.array([getattr(controller, x) for x in attributes])
            issued_velocity = transition.command(requested_velocity)

            tr.append('velocity_transition/physics_row', tr.n)
            tr.append('velocity_transition/requested', requested_velocity)
            tr.append('velocity_transition/issued', issued_velocity)
            from .velocity_request_adapter import call_with_issued_velocity
            return call_with_issued_velocity(controller, issued_velocity, original_controller_step)
        run.G1Controller.step = bounded_velocity
        sim.OUT_DIR = work / 'episode/native_output'; sim.OUT_DIR.mkdir(exist_ok=True)
        ik = sim.ArmIK6(m, ctrl)
        runner = p.HybridRunner(m, d, ctrl, ik, video=None, snapshots=False, sim_limit=300., wall_limit=280.)
        runner.q_cmd = requested[ctrl.right_arm_indices].copy()
        runner.grip_alpha = runner.grip_alpha_f = 1.; runner.grip_cap = None; runner.hold_tol = None
        servo = PlannedFingerServo(m)
        for i, aid in enumerate(servo.aids):
            indices = np.flatnonzero(history[:, i, 1] == 2)
            assert len(indices)
            servo.reference[int(aid)] = float(history[indices[0], i, 2] + np.sign(CLOSED[i]) * .03)
        desired = np.asarray(c.read(cfg['measured_tripod_plan'])['finger_target_rad'])
        initial_object = runner.cyl_pos().copy(); lost = None; recovery_pending = False; raw = mujoco.mj_step
        runner._D_tripod_servo = servo; runner._D_tripod_desired = desired
        def step(model, data, *args, **kwargs):
            nonlocal first_error, lost, recovery_pending
            if tr.n >= steps: raise WindowComplete()
            telemetry = servo.apply(model, data, desired)
            tr.append('finger_governor/physics_row', tr.n); tr.append('finger_governor/control', telemetry)
            if first_error is None:
                first_error = float(np.max(abs(data.ctrl - expected)))
                c.write(work / 'FIRST_COMMAND_CHECK.json', {'max_error':first_error,'saved_velocity':observation[-3:].tolist(),'restored_transition_issued':transition.issued.tolist()})
                assert first_error < 1e-7, 'saved_carry_interface_mismatch'
            raw(model, data, *args, **kwargs)
            if tr.max_penetration > .01 or loaded_forbidden(model, data):
                raise p.EpisodeAborted('D_carry_actual_contact_limit')
            geometry = contact_geometry(model, data, runner.cyl_bid)
            if geometry['rank'] == 6 and geometry['digits'] == ['index', 'middle', 'thumb']:
                lost = None
            elif lost is None: lost = float(data.time)
            elif data.time - lost >= .04: recovery_pending = True
        mujoco.mj_step = step
        original_runner_step = runner.step_once
        def recover_after_completed_step():
            nonlocal recovery_pending, lost
            original_runner_step()
            if recovery_pending and not getattr(runner, '_D_reacquiring', False):
                runner.ctrl.lin_vel_x = runner.ctrl.lin_vel_y = runner.ctrl.ang_vel_z = 0.
                from .tripod_recontact_control import restore_tripod
                restore_tripod(runner, p)  # Existing maximum2 attempts,0.8s each and100ms stable hold.
                recovery_pending = False; lost = None
        runner.step_once = recover_after_completed_step
        runner.step_once()  # Exact saved controller/servo command before new motion.
        runner.ctrl.lin_vel_x = runner.ctrl.lin_vel_y = runner.ctrl.ang_vel_z = 0.
        runner.run(2.)  # Establish planned left clearance through motors before retreat.
        geo = p.scene_geometry(m)
        west = min(geo['brown_center'][0]-geo['brown_half'][0], geo['blue_center'][0]-geo['blue_half'][0])-.36
        goal = np.array([west, d.qpos[1]])
        yaw = float(p.ep.base_yaw(d))
        c.write(work / 'SAVED_INTERFACE_STATE.json', {'source_row': start, 'finger_encoder_references': servo.reference,
                'first_command_error': first_error, 'body_goal_xy': goal.tolist(), 'held_body_yaw': yaw,
                'arm_goal_retained': runner.q_cmd.tolist(), 'scope': 'Measured D western-route first leg with unchanged acquired arm pose.'})
        runner.move_tag = 'D_retained_upright_grasp_retreat'
        from .pose_velocity_navigation import walk_to
        walk_to(runner, goal, goal_yaw=yaw, timeout=20.)
        reached = True
        ctrl.lin_vel_x = ctrl.lin_vel_y = ctrl.ang_vel_z = 0.
        while tr.n < steps: runner.step_once()
        completed = True
    except WindowComplete: completed = True
    except BaseException as exc:
        if 'p' in locals() and isinstance(exc, p.EpisodeAborted): abort = str(exc); completed = True
        else: error = traceback.format_exc(); print(error, flush=True)
    finally: summary = tr.close()
    result = {'outcome': 'engineering_failure' if error else 'success', 'engineering_error': error,
              'scientific_window_abort': abort, 'window_completed': completed, 'walk_goal_reached': reached,
              'retained_arm_pose_transport': True,
              'recontact_count': getattr(runner, '_D_recontact_count', 0) if 'runner' in locals() else 0,
              'recontact_pending_at_end': recovery_pending if 'recovery_pending' in locals() else False,
              'object_horizontal_displacement_m': float(np.linalg.norm(runner.cyl_pos()[:2]-initial_object[:2])) if 'initial_object' in locals() else None,
              'first_command_error': first_error, 'summary': summary,
              'final_tilt_deg': runner.cyl_tilt_deg() if 'runner' in locals() else None,
              'final_grasp': contact_geometry(m, d, runner.cyl_bid) if 'runner' in locals() else None,
              'full_task': False, 'production_accepted': False, 'new_complete_task_attempts': 0}
    c.write(work / 'DIAGNOSTIC.json', result); finish(result, tr.usage)


if __name__ == '__main__': main(sys.argv[1])
