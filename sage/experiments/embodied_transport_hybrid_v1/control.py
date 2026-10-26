"""Explicitly scoped arm position control and declared gravity compensation."""

import numpy as np
from sage.experiments.embodied_transport_v1.kinematics import ARM_NAMES
from sage.experiments.embodied_data_stability_v1.sonic_shadow import (
    SONIC_BODY_JOINT_ORDER,
)

ARM = np.array([list(SONIC_BODY_JOINT_ORDER).index(n) for n in ARM_NAMES], dtype=int)
SONIC = np.array([i for i in range(29) if i not in ARM], dtype=int)


def compose(sonic, reference, active):
    target = np.array(sonic, copy=True)
    if active:
        target[ARM] = np.asarray(reference)[ARM]
    return target


def feedforward(bias, active):
    value = np.array(bias, copy=True)
    if active:
        value[SONIC] = 0
    return value
