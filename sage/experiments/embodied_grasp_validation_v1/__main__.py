"""Public bounded-worker task entry; no work occurs at import time."""
import argparse
import hashlib
import json
from pathlib import Path
from .build import build, write


def verify(stage, label):
    frozen=json.loads((stage/'protocol'/label).read_text())
    for path,expected in frozen['files'].items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=expected:
            raise ValueError('frozen_input_changed:'+path)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['prepare','execute','audit']);p.add_argument('stage',type=Path)
    p.add_argument('--combination',choices=['G01','G02'])
    args=p.parse_args(argv);r=args.stage.resolve()
    freeze='PREPARE_FREEZE.json' if args.command=='prepare' else 'EXECUTION_FREEZE.json'
    verify(r,freeze)
    config=json.loads((r/'protocol/PROTOCOL.json').read_text());binding=json.loads(Path(config['source_binding']).read_text())
    if args.command=='prepare':
        import mujoco
        from .planner import plan
        from .verification import regression
        regression(config,r/'evidence/REGRESSION.json',mujoco.MjModel.from_xml_path(config['source_model']),binding)
        rows=[]
        for combination in config['combinations']:
            out=r/'combinations'/combination['id'];task=build(config,combination,out)
            result=plan(config,task,binding,out);rows.append(dict(id=combination['id'],status=result['status'],selected=result['selected'],configurations=result['static_configurations']))
            print(json.dumps(rows[-1]),flush=True)
        write(r/'evidence/PREPARATION.json',rows)
    elif args.command=='execute':
        from .execution import run
        if not args.combination:p.error('execute requires --combination')
        out=r/'combinations'/args.combination;task=json.loads((out/'TASK.json').read_text())
        result=json.loads((out/'PLAN_RESULT.json').read_text())
        if result['selected'] is None:
            write(out/'EXECUTION_SKIPPED.json',dict(status='skipped',reason='planning_rejected',physical_attempts=0,physics_steps=0))
        else:run(config,task,binding,json.loads((out/'SELECTED.json').read_text()),out)
    else:
        from .verification import audit
        results=[]
        for combination in config['combinations']:
            out=r/'combinations'/combination['id'];task=json.loads((out/'TASK.json').read_text())
            results.append(dict(id=combination['id'],**audit(config,task,binding,out)))
        write(r/'evidence/AUDIT.json',results);print(json.dumps(results),flush=True)
    verify(r,freeze)


if __name__=='__main__':main()
