"""Pause the arm, replan a missing finger contact, then resume object planning."""
import numpy as np
from .tripod_recontact import plan_recontact
from .planned_tripod_r3 import GROUPS, contact_geometry


def restore_tripod(runner, pipeline):
    import instrument
    m, d = runner.model, runner.data
    geometry = contact_geometry(m, d, runner.cyl_bid)
    if geometry['rank'] == 6 and geometry['digits'] == ['index', 'middle', 'thumb']:
        return
    if len(geometry['digits']) < 2:
        raise pipeline.EpisodeAborted('D_recontact_insufficient_remaining_grasp')
    count = getattr(runner, '_D_recontact_count', 0)
    if count >= 2:
        raise pipeline.EpisodeAborted('D_recontact_count_bound')
    planned = plan_recontact(m, d, runner.cyl_bid)
    if not planned['valid']:
        raise pipeline.EpisodeAborted('D_measured_recontact_plan_infeasible')
    servo, desired = runner._D_tripod_servo, runner._D_tripod_desired
    tr = instrument.ACTIVE_TRACE
    tr.append('recontact/physics_row', tr.n)
    tr.append('recontact/finger_target_rad', planned['finger_target_rad'])
    runner._D_recontact_count = count + 1
    # Hold a measured ARM reference through the existing actuators. This does
    # not set physical joint positions or disable physical body motion.
    runner.q_cmd = d.qpos[runner.ik.qpos_idx].copy()
    target = np.asarray(planned['finger_target_rad'])
    for digit in planned['missing_digits']:
        for index in GROUPS[digit]:
            servo.preload_by_aid[int(servo.aids[index])] = .05
            servo.reference.pop(int(servo.aids[index]), None)
            desired[index] = target[index]
    runner._D_reacquiring = True
    started = float(d.time); stable = 0
    try:
        while d.time - started < .8:
            runner.step_once()
            geometry = contact_geometry(m, d, runner.cyl_bid)
            good = geometry['rank'] == 6 and geometry['digits'] == ['index', 'middle', 'thumb']
            stable = stable + 1 if good and runner.cyl_tilt_deg() <= 15. else 0
            if stable * m.opt.timestep >= .1:
                tr.append('recontact/complete', [tr.n, d.time - started, runner.cyl_tilt_deg()])
                return
        raise pipeline.EpisodeAborted('D_measured_recontact_time_bound')
    finally:
        runner._D_reacquiring = False
