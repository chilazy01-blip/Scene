"""No arm action override: only legal-range projection of all29 SONIC targets."""
import numpy as np
from sage.experiments.embodied_native_object_transport_v1.protocol_v4 import project_target


def body_target(sonic, previous, lower, upper, maximum_step):
    return project_target(np.asarray(sonic),previous,lower,upper,maximum_step)


def feedforward(actual_body_bias,active):
    return np.zeros(29) if active else np.asarray(actual_body_bias).copy()
