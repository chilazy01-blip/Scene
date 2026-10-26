"""Local request broker outside the expert's writable workbench."""
import argparse,json,os,re,subprocess,time,traceback
from pathlib import Path
from .common import ROOT,PYTHON,ENV37,read_bound_json,safe_save


def run():
    bench=ROOT/'workbench';seen={p.name for p in (bench/'outbox').glob('*.json')};jobs={};auth=read_bound_json(ROOT/'AUTHORIZATION.json')
    env=os.environ.copy();env.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MUJOCO_GL='egl',PYTHONPATH='/data/wsj/main/scene:'+ENV37)
    (bench/'BROKER_READY').write_text('ready\n')
    try:
        while time.time()<auth['deadline_epoch_utc'] and not(ROOT/'STOP_BROKER').exists():
            for request in sorted((bench/'inbox').glob('*.json')):
                if request.name in seen:continue
                seen.add(request.name);response={}
                try:
                    args=json.loads(request.read_text());action=args['action']
                    if action=='status':
                        from .protocol import spent_steps
                        ledger=read_bound_json(ROOT/'COST.json')
                        response=dict(parent_notice=(ROOT/'PARENT_UPDATES.md').read_text() if (ROOT/'PARENT_UPDATES.md').exists() else '',status='ok',spent_or_reserved_physics=spent_steps(ledger),physics_cap=120000,seconds_left=auth['deadline_epoch_utc']-time.time(),jobs={})
                        for name in sorted(set(jobs)|{p.parent.name for p in (ROOT/'trials').glob('*/JOB.json')}):
                            p=ROOT/'trials'/name/'JOB.json'
                            response['jobs'][name]=read_bound_json(p) if p.exists() else dict(status='starting',process_returncode=jobs[name].poll() if name in jobs else None)
                    elif action=='trial':
                        from .prepare_v3 import run as prepare
                        active=[j.parent.name for j in (ROOT/'trials').glob('*/JOB.json') if read_bound_json(j).get('status')=='running']
                        if active:raise RuntimeError('a trial is already running: '+','.join(active))
                        strategy=bench/args['strategy'];case=args['case'];name=args['name']
                        trial=prepare(strategy,case,name)
                        log=(trial/'driver.log').open('x')
                        proc=subprocess.Popen([PYTHON,'-B','-m','sage.experiments.embodied_expert_branch1_v1.trial','--root',str(trial)],env=env,cwd='/data/wsj/main/scene',stdout=log,stderr=subprocess.STDOUT)
                        log.close();jobs[name]=proc
                        response=dict(status='started',name=name,trial=str(trial),pid=proc.pid)
                    elif action=='inspect':
                        from .inspect_state import run as inspect
                        response=dict(status='ok',observation=inspect(args['source'],args.get('stage','release'),args.get('sample','first'),args.get('tick'),args.get('goal'),args.get('rotation')))
                    else:raise ValueError('unknown broker action')
                except Exception as exc:
                    response=dict(status='error',error=type(exc).__name__+': '+str(exc),traceback=traceback.format_exc())
                safe_save(bench/'outbox'/request.name,response)
                print(dict(request=request.name,result=response.get('status')),flush=True)
            time.sleep(.4)
    finally:
        (bench/'BROKER_READY').unlink(missing_ok=True)
        # Trials carry their own fixed deadline and normal per-step accounting.
        for p in jobs.values():
            if p.poll() is None:p.wait(timeout=60)


if __name__=='__main__':
    import resource
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8]);run()
