"""Respect both released controller effort and actual native actuator command range."""
import numpy as np


def native_torque(raw,official_effort,native_range):
    limits=np.asarray(native_range)
    return np.clip(raw,np.maximum(-np.asarray(official_effort),limits[:,0]),np.minimum(np.asarray(official_effort),limits[:,1]))
