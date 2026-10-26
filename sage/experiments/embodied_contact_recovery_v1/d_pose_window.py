"""Prepared D saved-state window; execution requires the window amendment receipt."""
import os, sys, traceback
from pathlib import Path
import numpy as np
import h5py
import mujoco
from .work import E, R, c, finish
from . import trace_r4
from .leg_interpolation import LegInterpolation
from .contact_finger_hold import MeasuredFingerHold

class WindowComplete(BaseException): pass

def main(case_file):
    approval = c.read(E / 'DIAGNOSTIC_WINDOW_REPLAN_APPROVAL.json')
    assert approval['approved'] and approval['proposal_sha256'] == c.sha(E / 'DIAGNOSTIC_WINDOW_REPLAN_PROPOSAL.json')
    cfg = c.read(case_file)
    work = Path(os.environ['CONTINUOUS_JOB_DIR'])
    folder = Path(cfg['source_folder'])
    start, steps = int(cfg['start_row']), int(cfg['saved_steps'])
    assert start % 8 == 0 and 0 < steps <= 4000
    os.environ.update(NP_ROOT=str(R), NP_JOB=str(work))
    sys.path.insert(0, str(R / 'tools'))
    sys.path.insert(0, str(R / 'branches/A/source'))
    sys.modules['instrument'] = trace_r4
    c.write(work / 'USAGE.json', {k: 0 for k in c.read(work / 'REQUEST.json')['reservation']})
    tr = trace_r4.Trace(work / 'episode', 'diagnostic')
    tr.install()
    error, bounded, abort, aligned = None, False, None, False
    try:
        from .target_adapter_r4 import install as target_install
        target_install('A', 'gain_translation', work / 'episode')
        import run
        from ik import pipeline as p, sim
        from .common_control import install as common_install
        from .object_pose_receding import RecedingObjectPosePlace
        from .methods_r6 import observe
        m = mujoco.MjModel.from_binary_path(str(folder / 'MODEL.mjb'))
        d = mujoco.MjData(m)
        with h5py.File(folder / 'TRACE.h5', 'r') as f:
            initial = f['substep/integration_before'][start]
            mujoco.mj_setState(m, d, initial, mujoco.mjtState.mjSTATE_INTEGRATION)
            previous = f['interpolation/applied'][start - 1]
            requested = f['interpolation/requested'][start - 1]
            policy = f['policy/walker_onnx']
            index = int(np.searchsorted(policy['physics_row'][:], start))
            assert int(policy['physics_row'][index]) == start
            last = policy['input'][next(iter(policy['input']))][index].reshape(-1)[-32:-3]
        mujoco.mj_forward(m, d)
        source = R / 'branches/A/source'
        policies = [run.ONNXPolicy(str(source / (name + '.onnx'))) for name in ['walker', 'croucher', 'rotator']]
        ctrl = run.G1Controller(m, d, *policies, c.read(source / 'model_config.json'))
        ctrl.last_action = last.copy()
        ctrl.lin_vel_x = ctrl.lin_vel_y = ctrl.ang_vel_z = 0.
        ids = [i for i, name in enumerate(ctrl.joint_names) if any(x in name for x in ['hip', 'knee', 'ankle'])]
        ctrl._contact_leg_interpolation = LegInterpolation(ids, 8)
        ctrl._contact_leg_interpolation.apply(previous)
        common_install(cfg)
        sim.OUT_DIR = work / 'episode/native_output'
        sim.OUT_DIR.mkdir(exist_ok=True)
        ik = sim.ArmIK6(m, ctrl)
        runner = p.HybridRunner(m, d, ctrl, ik, video=None, snapshots=False, sim_limit=300., wall_limit=210.)
        runner.q_cmd = requested[ctrl.right_arm_indices].copy()
        runner.grip_alpha = runner.grip_alpha_f = 1.
        runner.grip_cap = None
        governor = MeasuredFingerHold(m)
        # Establish the candidate from measured contacts and the saved physical
        # position command. No saved future control is used to construct it.
        for ct in d.contact:
            bodies = [int(m.geom_bodyid[g]) for g in [ct.geom1, ct.geom2]]
            if governor.obj in bodies and ct.dist <= 0:
                governor.latched.update(m.body(b).name.split('_')[2] for b in bodies if m.body(b).name.startswith('right_hand'))
        governor.hold(m, d)
        active = {'enabled': True, 'governor': governor}
        place = RecedingObjectPosePlace(p, cfg, active)
        before = observe(runner)
        raw_step = mujoco.mj_step
        def step(model, data, *args, **kwargs):
            if tr.n >= steps:
                raise WindowComplete()
            telemetry = governor.apply(model, data)
            tr.append('finger_governor/control', telemetry)
            tr.append('finger_governor/physics_row', tr.n)
            return raw_step(model, data, *args, **kwargs)
        mujoco.mj_step = step
        geo = p.scene_geometry(m)
        center, half = np.asarray(geo['blue_center'][:2]), np.asarray(geo['blue_half'][:2])
        target = np.clip(runner.cyl_pos()[:2], center - half + .08, center + half - .08)
        c.write(work / 'SAVED_INTERFACE_STATE.json', {'source_row': start, 'time': float(d.time),
                'last_action': last.tolist(), 'held_references': governor.reference,
                'initial_integration_sha256': __import__('hashlib').sha256(initial.tobytes()).hexdigest()})
        try:
            place.align(runner, geo, target)
            aligned = True
        except p.EpisodeAborted as exc:
            abort = str(exc)
        if abort is None:
            while tr.n < steps:
                runner.step_once()
        bounded = True
    except WindowComplete:
        bounded = True
    except BaseException:
        error = traceback.format_exc()
        print(error, flush=True)
    finally:
        summary = tr.close()
    report = {'outcome': 'engineering_failure' if error else 'success', 'window_completed': bounded,
              'D_alignment_reached': aligned, 'scientific_window_abort': abort,
              'before': before if 'before' in locals() else None,
              'after': observe(runner) if 'runner' in locals() else None,
              'summary': summary, 'engineering_error': error, 'full_task': False,
              'new_complete_task_attempts': 0, 'production_accepted': False}
    c.write(work / 'DIAGNOSTIC.json', report)
    finish(report, tr.usage)

if __name__ == '__main__': main(sys.argv[1])
