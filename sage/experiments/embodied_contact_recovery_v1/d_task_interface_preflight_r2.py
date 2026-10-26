"""Exercise installed D interfaces and route geometry without integration."""
import os
import sys
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import h5py
import mujoco
from .work import E, R, c, finish


def main(config_file):
    work = Path(os.environ['CONTINUOUS_JOB_DIR']); cfg = c.read(config_file)
    os.environ.update(NP_ROOT=str(R), NP_JOB=str(work))
    sys.path.insert(0, str(R / 'tools')); sys.path.insert(0, str(R / 'branches/A/source'))
    records = []
    dummy = SimpleNamespace(n=0, max_penetration=0., job=work,
                            append=lambda key, value: records.append([key, np.asarray(value).tolist()]))
    sys.modules['instrument'] = SimpleNamespace(ACTIVE_TRACE=dummy)
    def reject(*args, **kwargs): raise AssertionError('static_preflight_must_not_integrate')
    mujoco.mj_step = reject
    from .target_adapter_r4 import install as adapter
    adapter('A', 'gain_translation', work / 'static_interface')
    from ik import pipeline as p
    from .common_control import install as common
    from .compact_approach_control import install as compact
    from .tripod_task_control_r6 import install, loaded_forbidden
    common(cfg); compact(p, cfg); report = install(p, cfg)
    folder = E / 'jobs/D_tripod_window_01/episode'
    m = mujoco.MjModel.from_binary_path(str(folder / 'MODEL.mjb')); d = mujoco.MjData(m)
    with h5py.File(folder / 'TRACE.h5', 'r') as f:
        mujoco.mj_setState(m, d, f['substep/integration_after'][-1], mujoco.mjtState.mjSTATE_INTEGRATION)
    mujoco.mj_forward(m, d)
    assert loaded_forbidden(m, d) is None
    geo = p.scene_geometry(m); initial_xy = d.qpos[:2].copy()
    waypoint_calls = []
    # Only this planning fixture is moved to requested waypoints. No actual
    # physical state or dynamic episode is created by this static route check.
    def walk(runner, xy, goal_yaw=None, timeout=None):
        waypoint_calls.append({'from': d.qpos[:2].tolist(), 'goal': np.asarray(xy).tolist(), 'yaw': goal_yaw})
        d.qpos[:2] = xy
        return 0.
    p.ep.walk_to = walk
    runner = SimpleNamespace(model=m, data=d, ctrl=SimpleNamespace(lin_vel_x=0., lin_vel_y=0., ang_vel_z=0.), run=lambda seconds: None, cyl_pos=lambda: d.xpos[m.body('red_block').id].copy())
    route_error = None
    try: route_result = p.walk_to_pose_around(runner, [0., 0.], 0., geo, tag='transport')
    except p.EpisodeAborted as exc: route_error = str(exc); route_result = None
    wrist = np.eye(3); first, second, roll = p.cradle_frame(wrist, 30.)
    assert np.array_equal(first, wrist) and np.array_equal(second, wrist) and roll == 0.
    result = {'physics_steps': 0, 'policy_calls': 0, 'method': report,
              'actual_compact_stop_base_xy': initial_xy.tolist(),
              'actual_geometry': {k: np.asarray(geo[k]).tolist() for k in ['brown_center', 'brown_half', 'blue_center', 'blue_half', 'brown_top_z', 'blue_top_z']},
              'route_waypoints': waypoint_calls, 'route_result': route_result, 'route_error': route_error,
              'planned_upright_wrist_preserved_by_carry_interface': True,
              'passed': route_error is None, 'dynamic_route_qualified': False, 'production_accepted': False}
    c.write(E / 'D_TASK_INTERFACE_PREFLIGHT_R2.json', result); finish(result)


if __name__ == '__main__': main(sys.argv[1])
