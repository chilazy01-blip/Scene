from types import SimpleNamespace
import numpy as np
import pytest
from .guard import GuardedTask,check_source


def fixture():
    opt=SimpleNamespace(**{k:0 for k in ('iterations','ls_iterations','noslip_iterations','tolerance','noslip_tolerance','solver','integrator','cone','enableflags','disableflags')},timestep=.005,gravity=np.array([0.,0.,-9.81]))
    model=SimpleNamespace(opt=opt,body_mass=np.array([.15]))
    data=SimpleNamespace(**{k:np.zeros(3) for k in ('qpos','qvel','qacc_warmstart','ctrl','qfrc_applied','xfrc_applied')},time=0.)
    mj=SimpleNamespace(mj_step=lambda *a:None)
    return model,data,mj,{'target':[2.6,2.2,.787]}


def test_reference_writes_allowed():
    model,data,mj,case=fixture()
    class Inner:
        def update(self,*a):self.reference=np.ones(4)
    inner=Inner();GuardedTask(inner,mj,model,case).update(1,data,{})
    assert np.array_equal(inner.reference,np.ones(4)) and np.array_equal(data.qpos,np.zeros(3))


@pytest.mark.parametrize('field',['qpos','qvel','qacc_warmstart','ctrl','qfrc_applied','xfrc_applied','time'])
def test_physical_state_writes_rejected(field):
    model,data,mj,case=fixture()
    class Inner:
        def update(self,*a):
            if field=='time':data.time=1
            else:getattr(data,field)[0]=1
    with pytest.raises(RuntimeError,match='physical state'):GuardedTask(Inner(),mj,model,case).update(1,data,{})


def test_model_and_case_writes_rejected():
    model,data,mj,case=fixture()
    class Mass:
        def update(self,*a):model.body_mass[0]=0
    with pytest.raises(RuntimeError,match='physical model'):GuardedTask(Mass(),mj,model,case).update(1,data,{})
    model,data,mj,case=fixture()
    class Target:
        def update(self,*a):case['target'][0]=0
    with pytest.raises(RuntimeError,match='task case'):GuardedTask(Target(),mj,model,case).update(1,data,{})


def test_hand_target_hook_retains_physical_state_guard():
    model,data,mj,case=fixture()
    class Inner:
        def update(self,*a):pass
        def hand_targets(self,*a):data.qpos[0]=1
    wrapper=GuardedTask(Inner(),mj,model,case);wrapper.update(1,data,{})
    with pytest.raises(RuntimeError,match='physical state'):wrapper.hand_targets([])


def test_hidden_integrator_rejected_and_binding_restored():
    model,data,mj,case=fixture();original=mj.mj_step
    class Inner:
        def update(self,*a):mj.mj_step(model,data)
    with pytest.raises(RuntimeError,match='unaccounted integration'):GuardedTask(Inner(),mj,model,case).update(1,data,{})
    assert mj.mj_step is original


@pytest.mark.parametrize('source',['import subprocess\nclass Task: pass','class Task:\n def f(self):\n  data.qpos[:]=0','class Task:\n def f(self):\n  mj.mj_step(m,d)'])
def test_source_rejects_io_physical_writes_and_integration(source):
    with pytest.raises(ValueError):check_source(source)
