"""Explicit, replayable contact-solver calibration; no forces or state changes."""
def apply(model, protocol, completed_steps):
    schedule=protocol.get('solver_schedule')
    if schedule is None:return
    active=completed_steps>=schedule['activation_step']
    model.opt.noslip_iterations=int(schedule['noslip_iterations'] if active else 0)
