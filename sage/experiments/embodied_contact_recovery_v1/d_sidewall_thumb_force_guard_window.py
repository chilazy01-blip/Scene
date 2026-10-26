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
            previous = f['interpolation/applied'][start - 1]; requested = f['interpolation/requested'][start]
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
            initial_offset=float(cfg['saved_left_elbow_offset_rad']);target_offset=float(cfg['target_left_elbow_offset_rad'])
            result[controller.joint_names.index('left_elbow_joint')] += initial_offset+(target_offset-initial_offset)*fraction
            roll_initial=float(cfg.get('saved_left_shoulder_roll_offset_rad',0.));roll_target=float(cfg.get('target_left_shoulder_roll_offset_rad',0.))
            result[controller.joint_names.index('left_shoulder_roll_joint')]+=roll_initial+(roll_target-roll_initial)*fraction
            return result
        run.G1Controller.arm_overlay = left_clearance
        original_controller_step = run.G1Controller.step
        from .velocity_transition import VelocityTransition
        transition = VelocityTransition(cfg['velocity_cap'], cfg['acceleration_cap'])
        transition.issued[:] = observation[-3:]  # Restore the actually issued policy command, including residual approach motion.
        def bounded_velocity(controller):
            attributes = ['lin_vel_x','lin_vel_y','ang_vel_z']
            requested_velocity = np.array([getattr(controller, x) for x in attributes])
            issued_velocity = observation[-3:].copy() if tr.n == 0 else transition.command(requested_velocity)

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
            free=np.flatnonzero(history[:,i,1]!=2);begin=int(free[-1])+1 if len(free) else 0
            indices=np.flatnonzero(history[begin:,i,1]==2)+begin
            assert len(indices), 'source_digit_not_latched_at_boundary'
            servo.reference[int(aid)]=float(history[indices[0],i,2]+np.sign(CLOSED[i])*.03)
        saved_refs=c.read(cfg['source_reference_file'])['finger_encoder_references'];servo.reference={int(a):float(x) for a,x in saved_refs.items()}
        initial_refs=dict(servo.reference);thumb_trigger=None
        desired = np.asarray(c.read(cfg['measured_tripod_plan'])['finger_target_rad'])
        initial_object = runner.cyl_pos().copy(); lost = None; raw = mujoco.mj_step
        def step(model, data, *args, **kwargs):
            nonlocal first_error, lost, thumb_trigger
            if tr.n >= steps: raise WindowComplete()
            telemetry = servo.apply(model, data, desired)
            normal=0.
            for ci,ct in enumerate(data.contact):
                bodies=[int(model.geom_bodyid[g]) for g in [ct.geom1,ct.geom2]]
                if runner.cyl_bid in bodies and any(model.body(b).name.startswith('right_hand_thumb') for b in bodies):
                    force=np.zeros(6);mujoco.mj_contactForce(model,data,ci,force);normal+=max(0.,float(force[0]))
            if tr.n>0 and thumb_trigger is None and normal<.08:thumb_trigger=float(data.time)
            extra=0. if thumb_trigger is None else .02*min(1.,(float(data.time)-thumb_trigger)/.2)
            for i,(aid,qa,digit) in enumerate(zip(servo.aids,servo.qa,servo.digits)):
                if digit!='thumb':continue
                q=float(data.qpos[qa]);limit=.03+extra;reference=initial_refs[int(aid)]+np.sign(CLOSED[i])*extra
                data.ctrl[aid]=np.clip(np.clip(reference,q-limit,q+limit),*model.actuator_ctrlrange[aid]);telemetry[i,5]=float(data.ctrl[aid])
            tr.append('thumb_force_guard/normal_extra',[normal,extra])
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
            elif data.time - lost >= .04: raise p.EpisodeAborted('D_carry_actual_wrench_rank_lost')
        mujoco.mj_step = step
        from .upright_carry_reference import UprightCarryReference
        upright=UprightCarryReference(runner);original_runner_step=runner.step_once
        scratch=mujoco.MjData(m)
        with h5py.File(folder/'TRACE.h5','r') as f:scratch.qpos[:]=f['substep/qpos'][int(cfg['orientation_reference_row'])]
        mujoco.mj_forward(m,scratch);upright.rotation=scratch.xmat[runner.cyl_bid].reshape(3,3).copy()
        def stabilized_step():
            if not upright.update(runner,tr.n):
                c.write(work/'UPRIGHT_REPLAN_FAILURE.json',upright.last)
                raise p.EpisodeAborted('D_upright_carry_replan_infeasible')
            if tr.n%8==0:
                tr.append('upright_carry/physics_row',tr.n);tr.append('upright_carry/arm_target',upright.target)
                if upright.last:tr.append('upright_carry/ik_residual',[upright.last['ik_position_residual_m'],upright.last['ik_rotation_residual_deg']])
            return original_runner_step()
        runner.step_once=stabilized_step
        runner.step_once()  # Exact saved controller/servo command before new motion.
        runner.ctrl.lin_vel_x = runner.ctrl.lin_vel_y = runner.ctrl.ang_vel_z = 0.
        # Source already established left clearance; resume its actual navigation goal.
        geo = p.scene_geometry(m)
        west = min(geo['brown_center'][0]-geo['brown_half'][0], geo['blue_center'][0]-geo['blue_half'][0])-.36
        interface=c.read(cfg['source_reference_file']);goal=np.asarray(interface['body_goal_xy']);yaw=float(interface['held_body_yaw'])
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
              'retained_arm_pose_transport':False,'measured_object_orientation_feedback':True,'thumb_force_guard_triggered':thumb_trigger is not None if 'thumb_trigger' in locals() else False,
              'object_horizontal_displacement_m': float(np.linalg.norm(runner.cyl_pos()[:2]-initial_object[:2])) if 'initial_object' in locals() else None,
              'first_command_error': first_error, 'summary': summary,
              'final_tilt_deg': runner.cyl_tilt_deg() if 'runner' in locals() else None,
              'final_grasp': contact_geometry(m, d, runner.cyl_bid) if 'runner' in locals() else None,
              'full_task': False, 'production_accepted': False, 'new_complete_task_attempts': 0}
    c.write(work / 'DIAGNOSTIC.json', result); finish(result, tr.usage)


if __name__ == '__main__': main(sys.argv[1])
