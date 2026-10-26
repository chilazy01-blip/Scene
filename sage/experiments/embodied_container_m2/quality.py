"""Common content checks plus geometric containment recomputed from saved states."""
from pathlib import Path
import h5py
import mujoco
import numpy as np
from sage.experiments.embodied_planner_m2_v2.quality import inspect_episode as inspect_common
from .cavity import containment


def inspect_episode(directory, env, protocol, record, registration):
    result = inspect_common(directory, env, protocol, record, registration)
    reasons = list(result['reasons'])
    with h5py.File(Path(directory)/'trajectory.h5') as h:
        if h.attrs.get('task') != 'place_in_container' or 'privileged/container_1khz' not in h:
            reasons.append('container_audit_missing')
        else:
            rows = h['privileged/container_1khz'][:]
            states = h['privileged/state'][:]
            if rows.shape != (len(h['action'])*50, 6) or not np.isfinite(rows).all():
                reasons.append('container_audit_invalid')
            else:
                tail = int(round(protocol['success']['stable_s']/.001))
                margin = protocol['success']['container_inner_margin_m']
                if (len(rows) < tail or not np.all(rows[-tail:, 1] == 1)
                        or not np.all(rows[-tail:, 2:5] >= margin)
                        or not np.all(rows[-tail:, 5] > 0)):
                    reasons.append('final_container_containment_or_bottom_support')
                error = 0.
                for i in range(1, len(states)):
                    mujoco.mj_setState(env.model, env.data, states[i], int(h.attrs['state_spec']))
                    value = containment(env.task, env.data.qpos[env.target_qi:env.target_qi+3],
                                        env.data.qpos[env.target_qi+3:env.target_qi+7])
                    actual = np.array([float(value['inside']), value['side_margin_m'], value['rim_margin_m'], value['bottom_margin_m']])
                    error = max(error, float(np.max(abs(actual-rows[i*50-1, 1:5]))))
                if error != 0:
                    reasons.append('container_state_audit_mismatch')
                result.update(max_container_state_audit_error=error,
                              final_side_margin_m=float(rows[-1, 2]), final_rim_margin_m=float(rows[-1, 3]),
                              final_bottom_margin_m=float(rows[-1, 4]), final_bottom_support_n=float(rows[-1, 5]))
    result.update(accepted=not reasons, reasons=sorted(set(reasons)))
    return result
