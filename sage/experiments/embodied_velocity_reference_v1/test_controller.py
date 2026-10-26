import unittest
import numpy as np
from types import SimpleNamespace
from .controller import cubic_reference,cubic_step,VelocityReferenceController
from sage.experiments.embodied_simdata_v0.controller import PandaController


class ReferenceTests(unittest.TestCase):
    def test_step_position_is_bit_identical_to_original_schedule(self):
        a=np.arange(7.)/10;b=a[::-1]
        for k in range(2001):
            u=k/2000;old=a+(b-a)*(u*u*(3-2*u))
            np.testing.assert_array_equal(cubic_step(a,b,k,2000,.001)[0],old)

    def test_exact_endpoints_and_zero_boundary_velocity(self):
        a=np.arange(7.)/10;b=a[::-1]
        q,v=cubic_reference(a,b,0.,2.);np.testing.assert_array_equal(q,a);np.testing.assert_array_equal(v,np.zeros(7))
        q,v=cubic_reference(a,b,2.,2.);np.testing.assert_allclose(q,b,rtol=0,atol=1e-15);np.testing.assert_array_equal(v,np.zeros(7))

    def test_velocity_agrees_with_central_difference(self):
        a=np.arange(7.)/10;b=a[::-1];h=1e-6
        for t in [.1,.6,1.3,1.9]:
            q,v=cubic_reference(a,b,t,2.)
            finite=(cubic_reference(a,b,t+h,2.)[0]-cubic_reference(a,b,t-h,2.)[0])/(2*h)
            np.testing.assert_allclose(v,finite,atol=1e-9,rtol=0)

    def test_duration_sets_velocity_units(self):
        q,v=cubic_reference([0.],[1.],1.,2.)
        q2,v2=cubic_reference([0.],[1.],2.,4.)
        np.testing.assert_allclose(q,q2);np.testing.assert_allclose(v,2*v2)

    def test_invalid_inputs_are_rejected(self):
        for t,d in [(0.,0.),(-1.,2.),(3.,2.)]:
            with self.assertRaises(ValueError):cubic_reference([0.],[1.],t,d)
        with self.assertRaises(ValueError):cubic_reference([0.],[float('nan')],1.,2.)


class ForceTests(unittest.TestCase):
    def controller(self):
        c=object.__new__(VelocityReferenceController)
        c.qi=np.arange(7);c.vi=np.arange(7);c.ai=np.array([6,4,2,0,1,3,5]);c.fi=[7,8]
        c.kp=np.array([400,400,400,400,200,100,80.]);c.kd=np.array([45,45,45,45,25,15,12.])
        c.m=SimpleNamespace(actuator_ctrlrange=np.tile([-80.,80.],(9,1)))
        c.d=SimpleNamespace(qpos=np.arange(7)/100,qvel=np.arange(7)/200,qfrc_bias=np.arange(7)/10,ctrl=np.zeros(9))
        return c

    def test_zero_velocity_reduces_to_original_controller(self):
        c=self.controller();q=c.d.qpos+.001;PandaController.action(c,q,.03);old=c.d.ctrl.copy()
        c.action(q,.03,np.zeros(7));np.testing.assert_allclose(c.d.ctrl,old,rtol=0,atol=1e-12)

    def test_nontrivial_actuator_order_and_gripper_sign(self):
        c=self.controller();q=c.d.qpos.copy();v=c.d.qvel+np.arange(7)/100
        c.action(q,.02,v);np.testing.assert_allclose(c.d.ctrl[c.ai],c.kd*(v-c.d.qvel)+c.d.qfrc_bias)
        np.testing.assert_array_equal(c.d.ctrl[c.fi],[.02,-.02])

    def test_native_limits_are_respected(self):
        c=self.controller();c.action(c.d.qpos+100.,.04,np.ones(7)*100.)
        np.testing.assert_array_equal(c.d.ctrl[c.ai],np.ones(7)*80.)
