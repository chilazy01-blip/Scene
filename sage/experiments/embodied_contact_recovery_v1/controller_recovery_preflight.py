"""Existing continuation/accounting regression plus isolated per-method limit checks."""
import unittest,io
from . import controller_recovery_v4 as revised
from sage.experiments.embodied_continuous_v3 import test_controller,test_accounting
from .work import E,c,finish

test_controller.c=revised;test_accounting.c=revised
class MethodLimitTests(test_controller.ContinuationTests):
 def extension(self):
  job=self.physical();self.plan['methods']['B'].update(closed=False,scientific_failures=3)
  self.plan['method_scientific_failure_limits']={'B':5};return job
 def test_extended_method_fourth_failure_retains_history_and_stays_open(self):
  job=self.extension();state=self.install();self.assertNotIn('method_closed',revised.job_blockers(self.plan,state,'transfer',self.now))
  revised.record_result(self.plan,state,'transfer','scientific_failure',job['reservation'],{},self.now)
  self.assertEqual(state['methods']['B']['scientific_failures'],4);self.assertFalse(state['methods']['B']['closed']);self.assertEqual(state['methods']['A']['scientific_failures'],3);self.assertTrue(state['methods']['A']['closed'])
 def test_fifth_failure_closes_only_extended_method(self):
  job=self.extension();self.plan['methods']['B']['scientific_failures']=4;state=self.install();revised.record_result(self.plan,state,'transfer','scientific_failure',job['reservation'],{},self.now);self.assertEqual(state['methods']['B']['scientific_failures'],5);self.assertTrue(state['methods']['B']['closed'])
 def test_override_does_not_reopen_closed_flag(self):
  self.extension();self.plan['methods']['B']['closed']=True;state=self.install();self.assertIn('method_closed',revised.job_blockers(self.plan,state,'transfer',self.now))
 def test_unlisted_method_retains_global_limit(self):
  self.extension();self.assertEqual(revised.scientific_limit(self.plan,'A'),3);self.assertEqual(revised.scientific_limit(self.plan,'B'),5)
 def test_override_rejects_invalid_or_unrecognized_method(self):
  self.plan['method_scientific_failure_limits']={'unknown':5}
  with self.assertRaises(revised.AdmissionError):self.install()
 def test_holdout_still_closes_on_first_failure(self):
  job=self.physical(pool='holdout');self.plan['methods']['B'].update(closed=False,scientific_failures=0);self.plan['method_scientific_failure_limits']={'B':5};state=self.install();revised.record_result(self.plan,state,'transfer','scientific_failure',job['reservation'],{},self.now);self.assertTrue(state['methods']['B']['closed']);self.assertEqual(state['methods']['B']['closure_reason'],'production_first_failure')

loader=unittest.TestLoader();suite=unittest.TestSuite([loader.loadTestsFromModule(test_controller),loader.loadTestsFromModule(test_accounting),loader.loadTestsFromTestCase(MethodLimitTests)])
stream=io.StringIO();result=unittest.TextTestRunner(stream=stream,verbosity=1).run(suite)
report={'passed':result.wasSuccessful(),'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'log':stream.getvalue(),'current_authority_changed':False,'current_methods_reopened':False,'physics_steps':0,'scope':'Regression against temporary test fixtures only; preparing per-method capability does not authorize its use.'}
c.write(E/'D_RECOVERY_CONTROLLER_PREFLIGHT.json',report);finish(report)
assert result.wasSuccessful(),stream.getvalue()
