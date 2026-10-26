"""Refresh native body-controller state after the final initial-state restore."""
import numpy as np
import mujoco

BODY_PARTS = ('legs', 'torso', 'left', 'right')


def refresh_and_verify(base_env):
    model, data = base_env.sim.model._model, base_env.sim.data._data
    controllers = base_env.robots[0].composite_controller.part_controllers
    before = np.r_[data.time, data.qpos, data.qvel, data.ctrl, data.act]
    warm = data.qacc_warmstart.copy()
    goals = {part: None if controllers[part].goal_qpos is None else
             np.array(controllers[part].goal_qpos).copy() for part in BODY_PARTS}
    try:
        for part in BODY_PARTS:
            controllers[part].update(force=True)
    finally:
        data.qacc_warmstart[:] = warm
    if not np.array_equal(before, np.r_[data.time, data.qpos, data.qvel, data.ctrl, data.act]):
        raise RuntimeError('cache_refresh_changed_integration_state_or_input')
    matrix = np.zeros((model.nv, model.nv))
    mujoco.mj_fullM(model, matrix, data.qM)
    result = {}
    for part in BODY_PARTS:
        c = controllers[part]
        original_goal = goals[part]
        same_goal = c.goal_qpos is None if original_goal is None else np.array_equal(c.goal_qpos, original_goal)
        errors = dict(position=float(np.max(np.abs(c.joint_pos-data.qpos[c.qpos_index]))),
                      velocity=float(np.max(np.abs(c.joint_vel-data.qvel[c.qvel_index]))),
                      mass=float(np.max(np.abs(c.mass_matrix-matrix[np.ix_(c.qvel_index,c.qvel_index)]))))
        if not same_goal or max(errors.values()) > 1e-12:
            raise RuntimeError('stale_initial_controller_cache:'+part)
        result[part] = errors
    return dict(passed=True, errors=result, warmstart_preserved=np.array_equal(warm,data.qacc_warmstart),
                integration_state_and_input_preserved=True, goals_preserved=True)
