import numpy as np
import pytest
from .preload_tracking import advance,ROLES
from sage.experiments.embodied_carry_v1.grasp import RIGHT_CLOSED

def test_preload_loss_closes_and_never_widens_original_envelope():
    names=('left_hand_index_0_joint',)+tuple(RIGHT_CLOSED);q=np.zeros(8)
    for _ in range(300):
        new,_=advance(q,names,dict.fromkeys(ROLES,0.),dict.fromkeys(ROLES,5.),dict.fromkeys(ROLES,0.))
        assert np.max(np.abs(new-q))<=.006+1e-12 and new[0]==0
        for i,n in enumerate(names[1:],1):
            cap=RIGHT_CLOSED[n]*.5
            assert min(0,cap)-1e-12<=new[i]<=max(0,cap)+1e-12
            assert new[i]*np.sign(cap)>=q[i]*np.sign(cap)-1e-12
        q=new
    assert np.array_equal(q[1:],np.array(list(RIGHT_CLOSED.values()))*.5)

def test_force_rebound_preserves_acquired_preload():
    names=tuple(RIGHT_CLOSED);q=np.array(list(RIGHT_CLOSED.values()))*.3
    out,_=advance(q,names,dict.fromkeys(ROLES,10.),dict.fromkeys(ROLES,3.),dict.fromkeys(ROLES,10.))
    assert np.array_equal(out,q)

def test_only_underloaded_group_closes():
    names=tuple(RIGHT_CLOSED);q=np.zeros(7);forces={'thumb':3.,'index':0.,'middle':3.}
    out,_=advance(q,names,forces,dict.fromkeys(ROLES,3.),forces)
    assert out[3]>0 and out[4]>0 and np.array_equal(out[[0,1,2,5,6]],np.zeros(5))

@pytest.mark.parametrize('bad',[{'thumb':1.,'index':1.},{'thumb':np.nan,'index':1.,'middle':1.},{'thumb':-1.,'index':1.,'middle':1.}])
def test_incomplete_or_invalid_force_rejected(bad):
    with pytest.raises(ValueError):advance(np.zeros(7),tuple(RIGHT_CLOSED),bad,dict.fromkeys(ROLES,3.),dict.fromkeys(ROLES,1.))
