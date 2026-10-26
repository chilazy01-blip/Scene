"""Reference-loop behavior under a persistent tracker offset and extreme errors."""
import numpy as np
import pytest
from .reference_feedback import ReferenceFeedback


def test_persistent_tracking_offset_is_compensated():
    feedback=ReferenceFeedback();offset=np.array([.025,.006,-.007]);rot=np.array([.08,0,-.04])
    for _ in range(40):
        actual=feedback.position+offset;orientation=feedback.rotation+rot
        feedback.update(-actual,-orientation,.1)
    assert np.linalg.norm(feedback.position+offset)<.001
    assert np.linalg.norm(feedback.rotation+rot)<.001


def test_reference_bias_is_bounded_and_rate_limited():
    feedback=ReferenceFeedback();p,r=feedback.update([10,0,0],[10,0,0],.1)
    assert np.linalg.norm(p)<=.01000001 and np.linalg.norm(r)<=.04000001
    for _ in range(100):p,r=feedback.update([10,10,10],[10,10,10],.1)
    assert np.linalg.norm(p)<=.06000001 and np.linalg.norm(r)<=.30000001


def test_invalid_feedback_does_not_enter_references():
    with pytest.raises(ValueError):ReferenceFeedback().update([np.nan,0,0],[0,0,0],.1)
