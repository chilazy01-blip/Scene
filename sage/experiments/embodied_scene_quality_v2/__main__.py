import argparse
import json
import sys
from pathlib import Path
from .contracts import Rejected, write_new
from .evidence import assess, load_admitted


def main(argv=None):
    parser = argparse.ArgumentParser(description='Scoped contact primitive evidence and admission; never runs physics.')
    sub = parser.add_subparsers(dest='command', required=True)
    a = sub.add_parser('assess'); a.add_argument('--protocol-sha256', required=True); a.add_argument('--bundle-sha256', required=True)
    b = sub.add_parser('admit'); b.add_argument('--record', required=True); b.add_argument('--record-sha256', required=True)
    b.add_argument('--scope-sha256', required=True)
    b.add_argument('--use', choices=['candidate_inspection', 'isolated_release_cases', 'qualified_collection', 'qualified_export'], required=True)
    for p in (a, b):
        p.add_argument('--root', required=True); p.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'assess':
            result = assess(args.root, args.protocol_sha256, args.bundle_sha256)
        else:
            model, receipt = load_admitted(args.root, args.record, args.record_sha256,
                purpose=args.use, expected_scope_sha256=args.scope_sha256)
            result = dict(receipt=receipt, loaded_model_geoms=int(model.ngeom), data_created=False, new_physics_steps=0)
        write_new(args.output, result)
        print(json.dumps(dict(completed=True, output=args.output))); return 0
    except (Rejected, ValueError, KeyError, TypeError, OSError) as exc:
        print(json.dumps(dict(admitted=False, reason=type(exc).__name__+':'+str(exc))), file=sys.stderr); return 2


if __name__ == '__main__':
    sys.exit(main())
