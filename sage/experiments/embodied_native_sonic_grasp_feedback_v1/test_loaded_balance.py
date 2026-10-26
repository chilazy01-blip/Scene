from types import SimpleNamespace
import numpy as np
import pytest
from scipy.spatial.transform import Rotation
from .balanced_preload import solve,ROLES
from .continuous_lift import make_path
from sage.experiments.embodied_native_object_transport_v1.task_v3 import Task

def contacts():
    rows=[]
    for role,a in zip(ROLES,[0,2*np.pi/3,4*np.pi/3]):
        radial=np.array([np.cos(a),np.sin(a),0]);n=-radial;t=np.array([0.,0.,1.]);D=np.array([n,t,np.cross(n,t)]);rows.append(dict(role=role,frame=D.ravel().tolist(),friction=[1.,1.],position_m=(radial*.05).tolist(),object_sign=1.))
    return rows

def test_loaded_preload_preserves_existing_group_support_and_equilibrium():
    minimum=dict(thumb=2.,index=1.5,middle=1.5);z=solve(contacts(),2.,np.zeros(3),minimum)
    assert z['feasible'] and z['equilibrium_error']<1e-8 and all(z['group_normals_n'][g]>=minimum[g]-1e-8 for g in ROLES)

def test_unachievable_loaded_pressure_is_rejected():
    assert not solve(contacts(),2.,np.zeros(3),dict(thumb=7.,index=1.,middle=1.))['feasible']

def test_lift_reference_does_not_jump_to_different_measured_pose():
    desired=np.array([.3,.2,.9]);R=Rotation.from_euler('xyz',[.1,.2,.3]).as_matrix();path=make_path(100,desired,R,desired+[0,0,.04],R);obj=SimpleNamespace(path=path)
    p,A=Task.desired(obj,100);assert np.array_equal(p,desired) and np.max(np.abs(A-R))<1e-14
    end,B=Task.desired(obj,160);assert np.max(np.abs(end-desired-[0,0,.04]))<1e-14 and np.max(np.abs(B-R))<1e-14
    psmall,_=Task.desired(obj,100.001);assert np.linalg.norm(psmall-desired)<1e-12
