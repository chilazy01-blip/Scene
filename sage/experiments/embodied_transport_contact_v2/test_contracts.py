"""Retreat cannot reuse placement correction or introduce a wrist rotation."""
from types import SimpleNamespace
import numpy as np
from .task import Task


def test_retreat_uses_measured_rotation_and_declared_horizontal_vector():
    t=object.__new__(Task)
    t.stage="retract"
    t.model=SimpleNamespace(body=lambda n:SimpleNamespace(id=0))
    t.case={"retraction_vector_m":[-.1,0,0]}
    t.rotation_bias=np.ones(3)*.2
    t.bias=np.ones(3)*.04
    d=SimpleNamespace(xpos=np.array([[1.,2.,.9]]),xmat=np.array([np.eye(3).ravel()]))
    seen=[]
    t.cartesian_goal=lambda *args:seen.append(args)
    t.ik(10,d,np.zeros(3),np.eye(3),50)
    np.testing.assert_allclose(seen[0][2],[.9,2.,.9])
    np.testing.assert_array_equal(seen[0][3],np.eye(3))
    np.testing.assert_array_equal(t.rotation_bias,0)
    np.testing.assert_array_equal(t.bias,0)
