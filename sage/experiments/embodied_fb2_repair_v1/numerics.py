"""Step-size comparison preserving baseline effective constraint softness.

MuJoCo 3.2.6 engine_forward.c / engine_core_constraint.c: constraint assembly
computes KBIP with refsafe's timestep clamp. Reassemble at baseline dt, then
integrate at the test dt. No contacts, forces, poses or velocity are injected.
"""
import mujoco


def preserve_baseline_constraint_parameters(model,data,baseline_dt=0.005):
    timestep=float(model.opt.timestep)
    if int(model.opt.enableflags)&int(mujoco.mjtEnableBit.mjENBL_ISLAND):
        raise ValueError('island_enabled_model_not_admitted')
    try:
        model.opt.timestep=baseline_dt
        mujoco.mj_makeConstraint(model,data)
        mujoco.mj_projectConstraint(model,data)
        mujoco.mj_fwdVelocity(model,data)
    finally:
        model.opt.timestep=timestep


def baseline_forward(model,data,baseline_dt=0.005):
    """No integration; same effective contact model as the split-step worker."""
    mujoco.mj_fwdPosition(model,data)
    preserve_baseline_constraint_parameters(model,data,baseline_dt)
    mujoco.mj_fwdActuation(model,data)
    mujoco.mj_fwdAcceleration(model,data)
    mujoco.mj_fwdConstraint(model,data)
