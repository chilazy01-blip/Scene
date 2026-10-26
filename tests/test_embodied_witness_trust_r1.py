"""Engineering regressions for prepared trust updates; no robot execution."""
import ast,importlib.util,unittest,time
from pathlib import Path
from types import SimpleNamespace
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
V7=ROOT/'sage/experiments/embodied_task_space_v7'
spec=importlib.util.spec_from_file_location('trust_policy',V7/'witness_trust_r1.py');policy=importlib.util.module_from_spec(spec);spec.loader.exec_module(policy)

class TrustTests(unittest.TestCase):
    def test_rejected_contacts_reach_next_model_before_shrink(self):
        self.assertEqual(policy.update_radius(.25,True,.25,3,.25,.0078125)[0],.25)
        self.assertEqual(policy.update_radius(.25,False,None,3,.25,.0078125)[0],.25)
    def test_no_new_evidence_retains_original_finite_backoff(self):
        self.assertEqual(policy.update_radius(.25,False,None,0,.25,.0078125)[0],.125)
        self.assertEqual(policy.update_radius(.25,True,.25,0,.25,.0078125)[0],.0625)
        self.assertEqual(policy.update_radius(.0078125,False,None,0,.25,.0078125)[0],.00390625)
        self.assertEqual(policy.update_radius(.25,True,1.,0,.25,.0078125)[0],.25)
    def test_invalid_inputs_cannot_bypass_limits(self):
        for args in [(.26,True,1.,1,.25,.0078125),(.25,True,.9,1,.25,.0078125),(.25,True,1.,-1,.25,.0078125),(.25,True,1.,True,.25,.0078125)]:
            with self.assertRaises(ValueError):policy.update_radius(*args)
    def harness(self,accept_ids=(),numeric=True):
        source=ast.parse((V7/'witness_compiler_r4.py').read_text());klass=next(x for x in source.body if isinstance(x,ast.ClassDef));calls=[]
        def solver(*args):calls.append(1);return (np.zeros(2),np.zeros(2),{'passed':numeric})
        namespace=dict(Base=object,np=np,time=time,update_radius=policy.update_radius,solve_qp=solver,accept_step=lambda old,new,hard,tol:dict(accepted=new['arrays']['id'] in accept_ids),measures=lambda current:(1.,current['meta']['merit']))
        exec(compile(ast.Module(body=[klass],type_ignores=[]),'prepared_solve','exec'),namespace)
        class Harness:
            solve=namespace['Compiler'].solve
            def __init__(self):
                self.map=SimpleNamespace(n=1,size=1,offsets=np.array([0,1]),residual=lambda x:0.)
                self.spec=dict(search_stride=40,trust_rad=.25,min_trust_rad=.0078125,max_iterations=2,audit_reserve_seconds=0,lp_seconds=1,step_scales=[1.,.5],contact_tolerance=1e-10)
                self.contact_witnesses=SimpleNamespace(current_ticks=set(),stopping_states=set());self.eval_ids=[];self.radii=[];self.linearized=[]
            def evaluate(self,x):
                i=len(self.eval_ids);self.eval_ids.append(i)
                if i==1:self.contact_witnesses.stopping_states.add((0,1))
                return dict(meta=dict(passed=False,merit=1.),vector=np.array([1.]),arrays=dict(id=i),bad=[],worst=set())
            def check_time(self,*args):pass
            def linearize_hierarchy(self,*args):self.linearized.append(set(self.contact_witnesses.stopping_states));return {}
            def problem(self,x,linear,trust):self.radii.append(trust);return np.zeros(2),None,None,None
            def hessian(self,*args):return np.ones(2)
            def predict_vector(self,*args):return np.array([.5])
        class Callback:
            def __init__(self):self.records=[];self.trials=[]
            def __call__(self,i,record,arrays):
                if i!='initial':self.records.append(record)
            def problem(self,*args):pass
            def trial(self,i,scale,meta,arrays,decision):self.trials.append((arrays['id'],decision['accepted']))
        return Harness(),Callback(),calls
    def test_loop_preserves_rejections_and_relinearizes_at_retained_radius(self):
        c,cb,calls=self.harness(accept_ids={2});result,arrays=c.solve(np.zeros(1),cb,float('inf'))
        self.assertEqual(c.radii,[.25,.25]);self.assertEqual(c.linearized,[set(),{(0,1)}]);self.assertEqual(cb.trials,[(1,False),(2,True),(3,False),(4,False)])
        self.assertEqual(arrays['id'],2);self.assertFalse(result['passed']);self.assertEqual(len(calls),2);self.assertEqual(cb.records[-1]['trust_update']['after'],.125)
    def test_new_witness_never_admits_an_unsafe_trial_or_extra_iteration(self):
        c,cb,calls=self.harness();result,arrays=c.solve(np.zeros(1),cb,float('inf'))
        self.assertEqual(arrays['id'],0);self.assertEqual(len(calls),2);self.assertEqual(len(cb.trials),4);self.assertTrue(all(not accepted for i,accepted in cb.trials));self.assertFalse(result['passed'])
    def test_uncertified_qp_stops_before_trial(self):
        c,cb,calls=self.harness(numeric=False);result,arrays=c.solve(np.zeros(1),cb,float('inf'))
        self.assertEqual(c.eval_ids,[0]);self.assertEqual(cb.trials,[]);self.assertEqual(result['reason'],'numerical_subproblem_not_admitted')

if __name__=='__main__':unittest.main(argv=['test_embodied_witness_trust_r1'],verbosity=2)
