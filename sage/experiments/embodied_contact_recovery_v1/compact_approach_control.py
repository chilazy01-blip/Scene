"""D planned compact arm posture before a single dynamic approach leg."""
import numpy as np
from .work import c
from .safe_approach_r3 import hand_bounds


def install(pipeline, config):
    import run, instrument
    plan = c.read(config['compact_approach_plan'])
    assert plan['static_endpoint_valid'] and plan['initial_pose_path_forbidden_free']
    old_overlay = run.G1Controller.arm_overlay
    def overlay(ctrl, target, proj_gravity=None):
        result = old_overlay(ctrl, target, proj_gravity)
        result[ctrl.joint_names.index('left_elbow_joint')] += getattr(ctrl, '_D_left_elbow_offset', 0.)
        return result
    run.G1Controller.arm_overlay = overlay
    old_walk = pipeline.base.walk_to_pose
    def walk(runner, goal_xy, goal_yaw, *args, **kwargs):
        if not getattr(runner, '_D_compact_approach_done', False):
            runner._D_compact_approach_done = True
            start = float(runner.data.time)
            def left_progress():
                runner.ctrl._D_left_elbow_offset = plan['left_elbow_offset_rad'] * min(1., (runner.data.time - start) / 2.)
                return False
            runner.move_tag = 'D_planned_compact_approach_pose'
            runner.ramp_to(np.asarray(plan['arm_target_rad']), rate=.004, settle=.15, sync=True, on_step=left_progress)
            runner.ctrl._D_left_elbow_offset = plan['left_elbow_offset_rad']
            lo, _ = hand_bounds(runner.model, runner.data)
            g = runner.model.geom('table_top').id
            top = runner.data.geom_xpos[g, 2] + runner.model.geom_size[g, 2]
            if lo[2] < top + .035:
                raise pipeline.EpisodeAborted('D_compact_actual_hand_clearance_failed')
            tr = instrument.ACTIVE_TRACE
            tr.append('compact_approach/physics_row', tr.n)
            tr.append('compact_approach/actual_hand_lower', lo)
            # Upstream hybrid navigation retains its own obstacle routing and yaw
            # handling, but receives the final goal exactly once.
        return old_walk(runner, goal_xy, goal_yaw, *args, **kwargs)
    pipeline.base.walk_to_pose = walk
    return {'static_plan': config['compact_approach_plan'], 'left_elbow_offset_rad': plan['left_elbow_offset_rad'],
            'single_first_approach_goal': True, 'runtime_state_writes': False, 'dynamic_validated': False}
