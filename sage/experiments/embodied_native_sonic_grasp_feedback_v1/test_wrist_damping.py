import numpy as np
from .wrist_damping import DampedReference
from sage.experiments.embodied_native_sonic_transport_v1.reference_feedback import ReferenceFeedback

def test_velocity_feedback_opposes_motion_and_keeps_reference_bounds():
    f=DampedReference(ReferenceFeedback());f.update([0,0,0],[0,0,0],0);f.velocity=np.array([.1,0,0]);p,r=f.update([0,0,0],[0,0,0],.1);assert p[0]<0 and np.linalg.norm(p)<=.01
    for _ in range(200):p,r=f.update([1,1,1],[1,1,1],.1)
    assert np.linalg.norm(p)<=.060000000001 and np.linalg.norm(r)<=.300000000001

def test_initial_transition_preserves_existing_bias():
    old=ReferenceFeedback();old.position=np.array([.01,0,0]);old.rotation=np.array([.03,0,0]);f=DampedReference(old);p,r=f.update([.01,0,0],[.1,0,0],0);assert np.allclose(p,old.position) and np.allclose(r,old.rotation)
