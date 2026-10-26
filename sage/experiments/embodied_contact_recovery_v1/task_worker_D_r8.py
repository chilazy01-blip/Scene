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
    os.environ['CONTACT_NAMED_INITIAL']='1'
    os.environ['CONTACT_STOW_JOINT']=case['stow_joint']
    os.environ['CONTACT_STOW_OFFSET']=str(case['stow_offset_rad'])
    if case.get('model_xml'):os.environ['CONTACT_MODEL_XML']=case['model_xml']
    req=c.read(work/'REQUEST.json')
    assert c.evidence_ok(req['inputs'])
    c.write(work/'USAGE.json',{k:0 for k in req['reservation']})
    sys.path.insert(0,str(R/'tools'))
    sys.path.insert(0,str(R/'branches/A/source'))
    from . import trace_r4
    sys.modules['instrument']=trace_r4
    from .trace_r4 import Trace,compare_traces
    trace=Trace(work/'episode',mode)
    trace.install()
    result={};error=None
    try:
        from .target_adapter_r4 import install as target_install
        target_install('A','gain_translation',work/'episode')
        from ik import pipeline as p
        from ik import sim
        from .tripod_task_control_r7 import install
        from .common_control import install as common_install
        from .compact_approach_control import install as approach_install
        sim.OUT_DIR=work/'episode/native_output'
        sim.OUT_DIR.mkdir(exist_ok=True)
        p.GRASP_DZ_MAX=.032
        c.write(work/'COMMON_CONTROL.json',common_install(case))
        c.write(work/'APPROACH_CONTROL.json',approach_install(p,case))
        method=install(p,case)
        c.write(work/'METHOD.json',method)
        from .d_corrective_navigation import install as corrective_install
        c.write(work/'CORRECTIVE_NAVIGATION.json',corrective_install(p,case))
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
        if result.get('error'):error=result['error']
    except BaseException:
        error=traceback.format_exc()
        print(error,flush=True)
    finally:
        summary=trace.close()
    research_pass=bool(result.get('success'))
    observed_quality=summary['max_penetration_m']<=.01
    quality=None
    if summary['physics_steps']:
        try:
            from .quality_core import evaluate
            quality=evaluate(work/'episode');c.write(work/'RECORDED_QUALITY.json',quality)
            observed_quality=all(quality['gates'].values())
        except BaseException:
            error=(error or '')+'\nquality audit error:\n'+traceback.format_exc()
    scientific_cap=bool(error and 'external_300s_limit' in error and summary['physics_steps']>=119999)
    if scientific_cap:
        result['abort']='simulation_300s_cap';result['success']=False;error=None
    outcome='engineering_failure' if error else ('success' if research_pass and observed_quality else 'scientific_failure')
    report={'method':case['method'],'mode':mode,'source_result':result,'trace_summary':summary,
            'research_task_passed':research_pass,'observed_penetration_gate':summary['max_penetration_m']<=.01,'all_recorded_research_quality_gates':observed_quality,'recorded_quality':quality,
            'production_accepted':False,'outcome':outcome,'engineering_error':error,
            'scientific_failure_reason':None if research_pass and observed_quality else {'task_success':research_pass,'recorded_quality_passed':observed_quality},
            'physical_validation_remaining':['full quality and calibrated physics contract','generator layouts','independent audit','RGB-D and real reader']}
    if mode=='audit':
        audit=compare_traces(Path(reference)/'episode',work/'episode')
        c.write(work/'AUDIT.json',audit)
        report['independent_audit']=audit
        report['outcome']='success' if audit['passed'] and not error else 'engineering_failure'
    finish(report,trace.usage)
    # A complete bound failure receipt preserves actual zero-integration accounting.


if __name__=='__main__':main(*sys.argv[1:])
