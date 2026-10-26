import argparse
import hashlib
import json
from pathlib import Path
import mujoco

from .control import ClosureContract
from .verification import write, check_contract, saved_regression
from .audit import audit_trace, native_checks, transmission_diagnostic


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('check', 'audit'))
    parser.add_argument('stage', type=Path)
    args = parser.parse_args(argv)
    r = args.stage.resolve()
    frozen = json.loads((r / 'protocol/SOFTWARE_FREEZE.json').read_text())['files']
    def verify():
        for name, digest in frozen.items():
            assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == digest, name
    verify()
    def forbidden(*unused, **kwargs):
        raise AssertionError('physics integration is outside this software stage')
    mujoco.mj_step = mujoco.mj_step1 = mujoco.mj_step2 = forbidden
    protocol = json.loads((r / 'protocol/PROTOCOL.json').read_text())
    result = []
    for cid, values in protocol['contracts'].items():
        c = ClosureContract(**values)
        if args.command == 'check':
            result.append(dict(id=cid, contract=check_contract(c, protocol['quality']),
                               saved=saved_regression(protocol['source_stage'], cid, c, r / 'evidence')))
        else:
            result.append(dict(id=cid, trace=audit_trace(r / 'evidence' / (cid + '_SAVED_INTERFACE_TRACE.json'), protocol['source_stage'], cid, c),
                               native=native_checks(protocol, cid, c),
                               transmission=transmission_diagnostic(protocol, cid)))
    output = dict(status='pass', scope='software only; native static forward and saved data are not a rollout',
                  combinations=result, new_physics_steps=0, new_replays=0, new_qualified_episodes=0,
                  dynamic_admission=False, learning='unknown')
    write(r / 'evidence' / ('SOFTWARE_RESULT.json' if args.command == 'check' else 'AUDIT.json'), output)
    verify()
    print(json.dumps(dict(status='pass', command=args.command, combinations=len(result), new_physics_steps=0)), flush=True)


if __name__ == '__main__':
    main()
