"""One broker-approved immutable strategy trial with exact integration accounting."""
import argparse,json,os,subprocess,time,traceback
from pathlib import Path
from .common import ROOT,PYTHON,ENV37,safe_save,read_bound_json,_file_binding


def run(root):
    deadline=read_bound_json(ROOT/'AUTHORIZATION.json')['deadline_epoch_utc']
    env=os.environ.copy();env.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MUJOCO_GL='egl',PYTHONPATH='/data/wsj/main/scene:'+ENV37)
    summary={'trial':str(root),'status':'running','actions':[]}
    safe_save(root/'JOB.json',summary)
    try:
        for action in ('preview','engine','measure','feedback'):
            log=root/(action+'.log')
            with log.open('x') as out:
                p=subprocess.run([PYTHON,'-B','-m','sage.experiments.embodied_expert_branch1_v1.job_v5',action,'--root',str(root)],env=env,cwd='/data/wsj/main/scene',stdout=out,stderr=subprocess.STDOUT,timeout=max(1,deadline-time.time()))
            summary['actions'].append(dict(action=action,returncode=p.returncode,log=str(log)))
            if p.returncode:
                summary.update(status='engineering_failure',failed_action=action,log_tail=log.read_text()[-5000:]);break
        else:
            r=read_bound_json(root/'full/REPORT.json');m=read_bound_json(root/'MEASUREMENTS.json')
            summary.update(status='complete',original_task_passed=r['task_passed'],upright_quality_passed=m['additional_upright_quality_passed'],
                qualified_candidate=bool(r['task_passed'] and m['additional_upright_quality_passed']),new_physics_steps=r['new_physics_steps'],
                stop_reason=r['stop_reason'],engineering_error=r['error'],cup_upright=m['cup_upright_cosine'],goal_error_m=m['goal_error_m'],
                final_root_speed_margin_m_s=m['final_root_speed_margin_m_s'],stage=r['stage'],stage_metrics=m['stage_metrics'],
                phases=[e for e in r['events'] if 'stage' in e and 'kind' not in e],
                expert_events=[e for e in r['events'] if e.get('kind','').startswith(('expert','cup','release','pose','support'))][-18:],
                report=_file_binding(root/'full/REPORT.json'),measurements=_file_binding(root/'MEASUREMENTS.json'))
    except Exception as exc:
        summary.update(status='engineering_failure',error=type(exc).__name__+': '+str(exc),traceback=traceback.format_exc())
    safe_save(root/'JOB.json',summary)
    print(json.dumps(summary),flush=True)


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);run(ap.parse_args().root)
