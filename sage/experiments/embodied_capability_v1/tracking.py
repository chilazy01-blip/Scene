"""Learn clock/geometry conditioned references with fixed encoder tracking.

The failed raw velocity-copying learner remains unchanged. This representation
learns feedforward references AND wheel encoder trajectories from the same
source data. Its fixed common/differential feedback gains match the existing
expert drive controller (1/s and 2/s); no live object state or expert action is
used. It does not learn perception or claim hardware transfer.
"""
import numpy as np
from .learning import features as original_features, RidgeImitation


def features(time,position,velocity,context):
    # Encoder/velocity values are not regression inputs, so copying current
    # velocity cannot minimize the regression loss. Encoders enter feedback.
    return original_features(time,position,velocity,context)[:,:273]


def tracked_reference(prediction,wheel_position):
    prediction=np.asarray(prediction,dtype=float)
    if prediction.shape!=(12,) or not np.isfinite(prediction).all():raise ValueError('invalid_prediction')
    reference=prediction[:10].copy();error=prediction[10:12]-wheel_position
    common=.5*(error[0]+error[1]);differential=.5*(error[1]-error[0])
    reference[:2]+=np.array([common-2*differential,common+2*differential])
    return reference
