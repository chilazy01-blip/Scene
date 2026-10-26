"""Check upright carry geometry from the actual successful D tripod lift."""
import os
import sys
from pathlib import Path
import numpy as np
import h5py
import mujoco
from .work import E, R, c, finish


def main():
    work = Path(os.environ['CONTINUOUS_JOB_DIR'])
    os.environ.update(NP_ROOT=str(R), NP_JOB=str(work))
    sys.path.insert(0, str(R / 'tools')); sys.path.insert(0, str(R / 'branches/A/source'))
    from .target_adapter_r4 import install
    install('A', 'gain_translation', work / 'static_interface')
    import run
    from ik import pipeline as p, sim
    from .pose_planner_static_r4 import solve
    from .object_pose_receding import segment_clear
    from .planned_tripod import PlannedFingerServo as OriginalServo
    from .planned_tripod_r2 import PlannedFingerServo
    folder = E / 'jobs/D_tripod_window_01/episode'
    m = mujoco.MjModel.from_binary_path(str(folder / 'MODEL.mjb')); d = mujoco.MjData(m)
    with h5py.File(folder / 'TRACE.h5', 'r') as f:
        mujoco.mj_setState(m, d, f['substep/integration_after'][-1], mujoco.mjtState.mjSTATE_INTEGRATION)
    mujoco.mj_forward(m, d)
    ctrl = run.G1Controller(m, d, None, None, None, c.read(R / 'branches/A/source/model_config.json'))
    ik = sim.ArmIK6(m, ctrl)
    class Runner:
        model, data, cyl_bid = m, d, m.body('red_block').id
        def __init__(self): self.ik = ik
        def palm_pose(self): return d.site_xpos[ik.site_id].copy(), d.site_xmat[ik.site_id].reshape(3, 3).copy()
        def cyl_pos(self): return d.xpos[self.cyl_bid].copy()
    runner = Runner(); geo = p.scene_geometry(m)
    initial = d.qpos.copy(); velocity = d.qvel.copy(); cases = []
    palm, _ = runner.palm_pose()
    for local in [[.20, -.16, .18], [.23, -.20, .20], [.25, -.22, .20], [.30, -.22, .22]]:
        desired_palm = p.ep.pelvis_to_world(d, local)
        goal = runner.cyl_pos() + desired_palm - palm
        result = solve(runner, geo, goal[:2], target_xyz=goal)
        check = segment_clear(runner, np.asarray(result['variables'][:-2]), samples=81)
        cases.append({'palm_pelvis_local_m': local, 'object_goal_xyz': goal.tolist(),
                      'plan': result, 'path': check, 'valid': bool(result['valid'] and check['passed'])})
        assert np.array_equal(d.qpos, initial) and np.array_equal(d.qvel, velocity)
    # New release branch must preserve existing capture commands exactly.
    first, second = OriginalServo(m), PlannedFingerServo(m)
    command = d.ctrl.copy(); desired = d.qpos[first.qa].copy()
    a = first.apply(m, d, desired); original_ctrl = d.ctrl.copy()
    d.ctrl[:] = command; b = second.apply(m, d, desired)
    assert np.array_equal(a, b) and np.array_equal(d.ctrl, original_ctrl)
    second.release(); assert second.released and not second.reference
    second.apply(m, d, np.zeros(7)); assert not second.reference
    second.reclose(); assert not second.released
    valid = [x for x in cases if x['valid']]
    result = {'physics_steps': 0, 'policy_calls': 0, 'cases': cases,
              'selected': valid[0] if valid else None,
              'nominal_servo_exact_to_successful_diagnostic': True,
              'release_does_not_relatch_existing_contacts': True,
              'passed': bool(valid), 'dynamic_carry_qualified': False,
              'production_accepted': False}
    c.write(E / 'D_TRIPOD_CARRY_STATIC.json', result); finish(result)


if __name__ == '__main__':
    main()
