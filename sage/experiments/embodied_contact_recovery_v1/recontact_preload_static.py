"""Check unchanged default servo and isolated missing-digit command revision."""
import numpy as np
import h5py
import mujoco
from .work import E, c, finish
from .planned_tripod_r2 import PlannedFingerServo as Prior
from .planned_tripod_r3 import PlannedFingerServo as Candidate
from .plant_guard import PlantGuard


def main():
    folder = E / 'jobs/D_carry_window_01/episode'
    m = mujoco.MjModel.from_binary_path(str(folder / 'MODEL.mjb')); d = mujoco.MjData(m)
    with h5py.File(folder / 'TRACE.h5', 'r') as f:
        mujoco.mj_setState(m, d, f['substep/integration_before'][1056], mujoco.mjtState.mjSTATE_INTEGRATION)
    mujoco.mj_forward(m, d); guard = PlantGuard(m)
    initial_q, initial_v, initial_ctrl = d.qpos.copy(), d.qvel.copy(), d.ctrl.copy()
    desired = d.qpos[Candidate(m).qa].copy()
    old, new = Prior(m), Candidate(m)
    a = old.apply(m, d, desired); old_ctrl = d.ctrl.copy()
    d.ctrl[:] = initial_ctrl; b = new.apply(m, d, desired)
    assert np.array_equal(a, b) and np.array_equal(d.ctrl, old_ctrl)
    new.reference.clear()
    indices = [i for i, name in enumerate(new.digits) if name == 'index']
    for i in indices: new.preload_by_aid[int(new.aids[i])] = .05
    d.ctrl[:] = initial_ctrl; revised = new.apply(m, d, desired)
    others = [i for i in range(m.nu) if i not in new.aids[indices]]
    assert np.array_equal(d.ctrl[others], old_ctrl[others])
    differences = (d.ctrl[new.aids[indices]] - d.qpos[new.qa[indices]])
    assert np.max(abs(differences - .05)) < 1e-12
    assert np.array_equal(d.qpos, initial_q) and np.array_equal(d.qvel, initial_v)
    guard.check(m)
    result = {'passed': True, 'physics_steps': 0, 'default_capture_servo_exact': True,
              'only_replanned_index_commands_changed': True,
              'index_command_errors_rad': differences.tolist(),
              'plant_sha256': guard.sha256, 'physical_model_unchanged': True,
              'dynamic_effect_unverified': True, 'production_accepted': False}
    c.write(E / 'D_RECONTACT_PRELOAD_STATIC.json', result); finish(result)


if __name__ == '__main__': main()
