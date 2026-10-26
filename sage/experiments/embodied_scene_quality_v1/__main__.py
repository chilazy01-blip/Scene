"""CPU-only sidecar assessment and a real gated, non-stepping model preflight."""
import argparse
import json
import sys

from .contracts import PROFILES, Rejected, read
from .quality import create_record, load_admitted, validate_record, write_sidecar


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('assess', 'validate', 'preflight'):
        p = sub.add_parser(name)
        p.add_argument('--package', required=True)
        p.add_argument('--output', required=True)
        if name == 'assess':
            p.add_argument('--sources', required=True, help='JSON mapping layout/request/context keys to evidence paths')
        else:
            p.add_argument('--record', required=True)
            p.add_argument('--record-sha256', required=True, help='Pin supplied by the calling run protocol')
            if name == 'preflight':
                p.add_argument('--use', choices=PROFILES, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'assess':
            output = create_record(args.package, read(args.sources))
        elif args.command == 'validate':
            findings, _ = validate_record(args.package, args.record, args.record_sha256)
            output = dict(valid_record=True, qualification=findings['qualification'])
        else:
            model, receipt = load_admitted(args.package, args.record, args.record_sha256, purpose=args.use)
            output = dict(receipt=receipt, loaded_model=dict(nbody=int(model.nbody), ngeom=int(model.ngeom),
                                                           nq=int(model.nq), nv=int(model.nv)),
                          physics_steps=0, data_allocated=False)
        write_sidecar(args.package, args.output, output)
        print(json.dumps(dict(command=args.command, output=args.output, completed=True)))
        return 0
    except (Rejected, KeyError, TypeError, ValueError, OSError) as exc:
        print(json.dumps(dict(admitted=False, reason=type(exc).__name__ + ':' + str(exc))), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
