import numpy as np
import pytest
from .wrist_smooth import SmoothReference
from sage.experiments.embodied_native_sonic_transport_v1.reference_feedback import ReferenceFeedback

def test_bumpless_conversion_and_zero_dt():
    old=ReferenceFeedback();old.position=np.array([.01,-.02,.003]);old.rotation=np.array([.08,0,-.02])
    f=SmoothReference(old);f.velocity=np.array([.1,-.1,0]);f.angular_velocity=np.array([0,0,1.])
    p,r=f.update([.01,0,.01],[.05,.02,0],.1)
    assert np.array_equal(p,old.position) and np.array_equal(r,old.rotation)
    p2,r2=f.update([1,1,1],[1,1,1],0)
    assert np.array_equal(p,p2) and np.array_equal(r,r2)

@pytest.mark.parametrize('dt',[.005,.02,.1])
def test_time_scaled_slew_and_original_magnitude_envelope(dt):
    f=SmoothReference(ReferenceFeedback());f.update([0,0,0],[0,0,0],0)
    for i in range(200):
        p,r=f.position.copy(),f.rotation.copy()
        f.velocity=np.ones(3)*(1 if i%2 else -1)
        f.angular_velocity=np.ones(3)*(2 if i%2 else -2)
        q,s=f.update([.1,.2,.3],[.3,.2,.1],dt)
        assert np.linalg.norm(q-p)<=.020*dt+1e-12
        assert np.linalg.norm(s-r)<=.120*dt+1e-12
        assert np.linalg.norm(q)<=.06+1e-12 and np.linalg.norm(s)<=.30+1e-12

def test_velocity_filter_response_and_opposing_correction():
    f=SmoothReference(ReferenceFeedback());f.update([0,0,0],[0,0,0],0);f.velocity=np.array([.1,0,0]);f.update([0,0,0],[0,0,0],.02)
    assert 0<f.filtered_v[0]<.1 and f.position[0]<0

@pytest.mark.parametrize('dt',[-.1,.2,np.nan])
def test_invalid_interval_rejected(dt):
    with pytest.raises(ValueError):SmoothReference(ReferenceFeedback()).update([0,0,0],[0,0,0],dt)
