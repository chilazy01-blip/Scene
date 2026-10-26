"""Actual task and independent rerun entry, with complete observed substeps."""
import os
import sys
import importlib.util
import traceback
from pathlib import Path
from .work import R,E,finish
from sage.experiments.embodied_continuous_v2 import controller as c


def main(case_file, mode='task', reference=None):
    assert mode in ['task','audit']
    case=c.read(case_file)
    work=Path(os.environ['CONTINUOUS_JOB_DIR'])
    os.environ['NP_ROOT']=str(R)
    os.environ['NP_JOB']=str(work)
    req=c.read(work/'REQUEST.json')
    assert c.evidence_ok(req['inputs'])
    c.write(work/'USAGE.json',{k:0 for k in req['reservation']})
    sys.path.insert(0,str(R/'tools'))
    sys.path.insert(0,str(R/'branches/A/source'))
    from . import trace_r2
    sys.modules['instrument']=trace_r2
    from .trace_r2 import Trace,compare_traces
    trace=Trace(work/'episode',mode)
    trace.install()
    result={};error=None
    try:
        from target_adapter import install as target_install
        target_install('A','gain_translation',work/'episode')
        from ik import pipeline as p
        from ik import sim
        from .methods import install
        sim.OUT_DIR=work/'episode/native_output'
        sim.OUT_DIR.mkdir(exist_ok=True)
        p.GRASP_DZ_MAX=.032
        method=install(p,case)
        c.write(work/'METHOD.json',method)
        if case.get('landing_damping'):
            from .landing import damp_landing
            previous=__import__('mujoco').mj_step
            def damped(m,d,*a,**kw):
                corrections=damp_landing(m,d,case['landing_damping'])
                for row in corrections:
                    trace.append('landing/row',[trace.n,*row])
                return previous(m,d,*a,**kw)
            __import__('mujoco').mj_step=damped
        result=p.run_once(**case['kwargs'],video=None,snapshots=False,sim_limit=300.,wall_limit=850.)
    except BaseException:
        error=traceback.format_exc()
        print(error,flush=True)
    finally:
        summary=trace.close()
    research_pass=bool(result.get('success'))
    observed_quality=summary['max_penetration_m']<=.01
    outcome='engineering_failure' if error else ('success' if research_pass and observed_quality else 'scientific_failure')
    report={'method':case['method'],'mode':mode,'source_result':result,'trace_summary':summary,
            'research_task_passed':research_pass,'observed_penetration_gate':observed_quality,
            'production_accepted':False,'outcome':outcome,'engineering_error':error,
            'scientific_failure_reason':None if research_pass and observed_quality else {'task_success':research_pass,'penetration_passed':observed_quality},
            'physical_validation_remaining':['full quality and calibrated physics contract','generator layouts','independent audit','RGB-D and real reader']}
    if mode=='audit':
        audit=compare_traces(Path(reference)/'episode',work/'episode')
        c.write(work/'AUDIT.json',audit)
        report['independent_audit']=audit
        report['outcome']='success' if audit['passed'] and not error else 'engineering_failure'
    finish(report,trace.usage)
    if error:raise RuntimeError('worker exception retained in RESULT.json')


if __name__=='__main__':main(*sys.argv[1:])
