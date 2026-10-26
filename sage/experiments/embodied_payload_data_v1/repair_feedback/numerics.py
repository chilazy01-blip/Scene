"""Diagnostic isolation of MuJoCo3.2.6 timestep-dependent refsafe parameters.

Contact parameters are combined by MuJoCo before constraint construction. To
retain the original5ms effective references, rebuild constraints with that
reference timestep and restore the real integration timestep immediately. This
does not change geometry, friction, poses, controls, or disable the safety flag.
It is a diagnostic intervention, not production authorization or calibration.

Source: google-deepmind/mujoco3.2.6 engine_core_constraint.c getsolparam and
engine_forward.c mj_fwdPosition. Constraint refsafe clamps positive timeconst
to twice the timestep during construction; timestep must be held fixed there
to distinguish changed contact dynamics from integration truncation error.
"""
import mujoco


def fixed_reference_step1(model,data,reference_timestep=.005,*,force_rebuild=False):
    if mujoco.__version__!='3.2.6':
        raise RuntimeError('unvalidated_mujoco_constraint_pipeline')
    if reference_timestep<=0 or model.opt.timestep>reference_timestep:
        raise ValueError('invalid_reference_timestep')
    if model.opt.disableflags & int(mujoco.mjtDisableBit.mjDSBL_REFSAFE):
        raise ValueError('refsafe_must_remain_enabled')
    mujoco.mj_step1(model,data)
    actual=model.opt.timestep
    if actual==reference_timestep and not force_rebuild:return
    try:
        model.opt.timestep=reference_timestep
        mujoco.mj_makeConstraint(model,data)
        if model.opt.enableflags & int(mujoco.mjtEnableBit.mjENBL_ISLAND):
            mujoco.mj_island(model,data)
        mujoco.mj_projectConstraint(model,data)
        mujoco.mj_referenceConstraint(model,data)
    finally:model.opt.timestep=actual
