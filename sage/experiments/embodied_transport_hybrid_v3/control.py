"""Guard every consumed SONIC joint and all actually applied mixed targets."""

import numpy as np
from sage.experiments.embodied_transport_hybrid_v1.control import (
    ARM,
    SONIC,
    compose,
    feedforward,
)
from sage.experiments.embodied_data_stability_v1.sonic_supported_shadow import (
    guard_candidate,
)
from sage.experiments.embodied_data_stability_v1 import (
    sonic_native_dynamic_shadow as native,
)
from sage.experiments.embodied_data_stability_v1.sonic_shadow import (
    SONIC_BODY_JOINT_ORDER,
)


def guard_sonic_candidate(candidate, previous, lower, upper, *, active):
    if not active:
        return guard_candidate(candidate, previous, lower, upper)
    delta = np.abs(candidate[SONIC] - previous[SONIC])
    index = int(np.argmax(delta))
    out = (candidate[SONIC] < lower[SONIC]) | (candidate[SONIC] > upper[SONIC])
    return {
        "finite": bool(np.isfinite(candidate).all()),
        "in_range": bool(not np.any(out)),
        "step_safe": bool(delta[index] <= native.MAX_CANDIDATE_STEP_RAD),
        "max_step_rad": float(delta[index]),
        "max_step_joint": SONIC_BODY_JOINT_ORDER[SONIC[index]],
        "out_of_range_joints": [SONIC_BODY_JOINT_ORDER[i] for i in SONIC[out]],
        "scope": "consumed SONIC22 only; applied hybrid29 separately guarded",
    }
