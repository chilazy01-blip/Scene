"""Analytical wrench equilibria and the actual falsely accepted grasp trigger."""
from pathlib import Path
import numpy as np
import pytest
from .friction import capacity


def contact(side,normal_n=1.,x=0.):
    n=np.array([0.,-side,0.]);t=np.array([0.,0.,1.]);D=np.array([n,t,np.cross(n,t)])
    return dict(dim=3,friction=[1.,1.,0,0,0],frame=D.reshape(-1).tolist(),object_sign=1.,position_m=[x,side*.05,0],normal_n=normal_n,role='thumb' if side>0 else 'middle')

def test_symmetric_two_finger_pinch_supports_two_mu_n():
    r=capacity([contact(1),contact(-1)],2.,np.zeros(3))
    assert r['maximum_weight_multiple']==pytest.approx(1.)

def test_smaller_preload_limits_balanced_pair():
    r=capacity([contact(1,1.),contact(-1,.5)],2.,np.zeros(3))
    assert r['maximum_weight_multiple']==pytest.approx(.5)

def test_lift_force_without_torque_balance_is_rejected():
    r=capacity([contact(1,x=.1),contact(-1,x=.1)],2.,np.zeros(3))
    assert r['maximum_weight_multiple']==pytest.approx(0.,abs=1e-8)

def test_actual_prelift_trigger_lacks_even_optimistic_static_margin():
    from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
    root=Path('/data/wsj/main/scene_runs/codex_trellis_v2/embodied_native_sonic_grasp_diagnosis_20261022_v1')
    j=read_bound_json(root/'FRICTION_RECONSTRUCTION.json');row=min(j['rows'],key=lambda a:abs(a['time_s']-23.56))
    cc=[c for c in row['contacts'] if c['role'] in ['thumb','index','middle','palm'] and c['normal_n']>.00001]
    r=capacity(cc,row['weight_n'],np.array(row['cup_com_m']),True)
    assert r['optimizer_success'] and r['maximum_weight_multiple']<1.
    assert r['maximum_weight_multiple']==pytest.approx(.871395154990569,rel=1e-6)
