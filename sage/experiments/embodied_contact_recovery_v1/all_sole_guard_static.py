"""Validate scratch isolation, bounded commands and optimizer cost on saved states."""
import numpy as np
import mujoco
import h5py
from .work import E, c, finish
from .all_sole_guard import AllSoleGuard

source = E / 'jobs/C_development_03/episode'
m = mujoco.MjModel.from_binary_path(str(source / 'MODEL.mjb'))
d = mujoco.MjData(m)
guard = AllSoleGuard(m)
records = []
mujoco.mj_step = lambda *a, **kw: (_ for _ in ()).throw(AssertionError('no_integration'))
with h5py.File(source / 'TRACE.h5', 'r') as f:
    for row in sorted(set([*range(6776, 6865, 8), 6831, 6839, 6847, 6851, 6855, 6860])):
        mujoco.mj_setState(m, d, f['substep/integration_before'][row], mujoco.mjtState.mjSTATE_INTEGRATION)
        d.ctrl[:] = f['substep/ctrl'][row]
        mujoco.mj_forward(m, d)
        state_before = np.r_[d.qpos, d.qvel, d.qacc, d.qacc_warmstart, d.qfrc_applied, d.xfrc_applied.ravel()].copy()
        original = d.ctrl.copy()
        result = guard.apply(d)
        state_after = np.r_[d.qpos, d.qvel, d.qacc, d.qacc_warmstart, d.qfrc_applied, d.xfrc_applied.ravel()]
        assert np.array_equal(state_before, state_after), 'scratch_query_modified_live_state'
        other = np.setdiff1d(np.arange(m.nu), guard.aids)
        assert np.array_equal(d.ctrl[other], original[other])
        assert np.max(abs(d.ctrl[guard.aids] - original[guard.aids])) <= 8. + 1e-8
        assert np.all(d.ctrl >= m.actuator_ctrlrange[:, 0] - 1e-8) and np.all(d.ctrl <= m.actuator_ctrlrange[:, 1] + 1e-8)
        records.append({'source_row': row, 'time': float(d.time), **result})
report = {'implementation_isolation_and_bounds_passed': True, 'physics_steps': 0, 'policy_calls': 0,
          'cases': records, 'controller_design_only': True, 'dynamic_admission': False,
          'production_accepted': False, 'failed_candidate_fallback': 'Original nominal motor command preserved when the bounded nonlinear barrier problem has no certified solution.'}
c.write(E / 'ALL_SOLE_GUARD_STATIC_PREFLIGHT.json', report)
finish(report)
