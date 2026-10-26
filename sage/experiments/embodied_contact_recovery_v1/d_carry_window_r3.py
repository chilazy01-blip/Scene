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
from .planned_tripod_r3 import PlannedFingerServo, CLOSED, contact_geometry
from .tripod_task_control_r3 import ObjectPoseMotion, loaded_forbidden


class WindowComplete(BaseException): pass


def main(config_path):
    cfg = c.read(config_path)
    approval = c.read(E / 'DIAGNOSTIC_WINDOW_REPLAN_APPROVAL.json')
    assert approval['approved'] and approval['proposal_sha256'] == c.sha(E / 'DIAGNOSTIC_WINDOW_REPLAN_PROPOSAL.json')
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
        ctrl.lin_vel_x = ctrl.lin_vel_y = ctrl.ang_vel_z = 0.
        ids = [i for i, name in enumerate(ctrl.joint_names) if any(x in name for x in ['hip', 'knee', 'ankle'])]
        ctrl._contact_leg_interpolation = LegInterpolation(ids, 8); ctrl._contact_leg_interpolation.apply(previous)
        common_install(cfg)
        sim.OUT_DIR = work / 'episode/native_output'; sim.OUT_DIR.mkdir(exist_ok=True)
        ik = sim.ArmIK6(m, ctrl)
        runner = p.HybridRunner(m, d, ctrl, ik, video=None, snapshots=False, sim_limit=300., wall_limit=280.)
        runner.q_cmd = requested[ctrl.right_arm_indices].copy()
        runner.grip_alpha = runner.grip_alpha_f = 1.; runner.grip_cap = None; runner.hold_tol = None
        servo = PlannedFingerServo(m)
        saved_interface = c.read(folder.parent / 'SAVED_INTERFACE_STATE.json')
        servo.reference = {int(key): float(value) for key, value in saved_interface['finger_encoder_references'].items()}
        desired = np.asarray(c.read(cfg['original_tripod_plan'])['finger_target_rad'])
        runner._D_tripod_servo = servo; runner._D_tripod_desired = desired
        initial_object = runner.cyl_pos().copy(); lost = None; raw = mujoco.mj_step
        def step(model, data, *args, **kwargs):
            nonlocal first_error, lost
            if tr.n >= steps: raise WindowComplete()
            telemetry = servo.apply(model, data, desired)
            tr.append('finger_governor/physics_row', tr.n); tr.append('finger_governor/control', telemetry)
            if first_error is None:
                first_error = float(np.max(abs(data.ctrl - expected)))
                assert first_error < 1e-7, 'saved_carry_interface_mismatch'
            raw(model, data, *args, **kwargs)
            if tr.max_penetration > .01 or loaded_forbidden(model, data):
                raise p.EpisodeAborted('D_carry_actual_contact_limit')
            geometry = contact_geometry(model, data, runner.cyl_bid)
            if geometry['rank'] == 6 and geometry['digits'] == ['index', 'middle', 'thumb']:
                lost = None
            elif lost is None: lost = float(data.time)
            elif data.time - lost >= (.8 if getattr(runner, '_D_reacquiring', False) else .04): raise p.EpisodeAborted('D_carry_actual_wrench_rank_lost')
        mujoco.mj_step = step
        runner.step_once()  # Exact saved controller/servo command before new motion.
        selected = c.read(cfg['tripod_carry_plan'])['selected']
        palm, _ = runner.palm_pose()
        desired_palm = p.ep.pelvis_to_world(d, selected['palm_pelvis_local_m'])
        goal = np.asarray(saved_interface['object_goal_xyz'])
        c.write(work / 'SAVED_INTERFACE_STATE.json', {'source_row': start, 'finger_encoder_references': servo.reference,
                'first_command_error': first_error, 'object_goal_xyz': goal.tolist()})
        runner.move_tag = 'D_measured_upright_carry'
        ObjectPoseMotion(p).move(runner, goal); reached = True
        while tr.n < steps: runner.step_once()
        completed = True
    except WindowComplete: completed = True
    except BaseException as exc:
        if 'p' in locals() and isinstance(exc, p.EpisodeAborted): abort = str(exc); completed = True
        else: error = traceback.format_exc(); print(error, flush=True)
    finally: summary = tr.close()
    result = {'outcome': 'engineering_failure' if error else 'success', 'engineering_error': error,
              'scientific_window_abort': abort, 'window_completed': completed, 'carry_goal_reached': reached,
              'first_command_error': first_error, 'summary': summary,
              'recontact_count': getattr(runner, '_D_recontact_count', 0) if 'runner' in locals() else 0,
              'final_tilt_deg': runner.cyl_tilt_deg() if 'runner' in locals() else None,
              'final_grasp': contact_geometry(m, d, runner.cyl_bid) if 'runner' in locals() else None,
              'full_task': False, 'production_accepted': False, 'new_complete_task_attempts': 0}
    c.write(work / 'DIAGNOSTIC.json', result); finish(result, tr.usage)


if __name__ == '__main__': main(sys.argv[1])
