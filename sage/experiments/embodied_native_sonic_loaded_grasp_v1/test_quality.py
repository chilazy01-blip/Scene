import numpy as np
import pytest
from .quality import required_preload
from sage.experiments.embodied_native_sonic_grasp_diagnosis_v1.test_capacity import contact,test_actual_prelift_trigger_lacks_even_optimistic_static_margin

def test_required_preload_balances_gravity_and_torque():
    a=required_preload([contact(1),contact(-1)],2.,np.zeros(3),1.5)
    assert a['feasible'] and a['total_normal_n']==pytest.approx(3.)
    assert a['required_group_normal_n']['thumb']==pytest.approx(1.5)
def test_contact_count_cannot_replace_torque_balance():
    assert not required_preload([contact(1,x=.1),contact(-1,x=.1)],2.,np.zeros(3))['feasible']
def test_finite_preload_cap_rejects_heavy_load():
    assert not required_preload([contact(1),contact(-1)],20.,np.zeros(3))['feasible']
def test_empty_grasp_is_not_ready():
    assert not required_preload([],1.,np.zeros(3))['feasible']
