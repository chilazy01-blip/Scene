import numpy as np
from scipy.spatial.transform import Rotation
from .task_local import world_targets
from sage.experiments.embodied_native_sonic_transport_v1.teleop_reference_ordered import root_normalize

def test_reference_world_round_trip_with_asymmetric_transformed_root():
    p=np.arange(9).reshape(3,3)/10;q=Rotation.from_euler('xyz',[[.1,.2,.3],[.2,.3,-.4],[-.3,.2,.1]]).as_quat()[:,[3,0,1,2]];root=np.array([2.,3.,.76]);rq=Rotation.from_euler('xyz',[.08,-.1,1.2]).as_quat()[[3,0,1,2]]
    points,rots=world_targets(p,q,root,rq);back,backq=root_normalize(points,rots,root,rq)
    assert np.allclose(back,p.reshape(-1),atol=1e-12)
    assert np.allclose(backq,q.reshape(-1),atol=1e-12)
