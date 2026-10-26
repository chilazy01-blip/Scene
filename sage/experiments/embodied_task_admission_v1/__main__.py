"""Public post-generation task handoff. All outputs use exclusive creation."""
import argparse
import json

from .intake import (USES, Rejected, bound, open_task, prepare_task, read,
                     reference, write_intake, write_new)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prepare = commands.add_parser('prepare')
    prepare.add_argument('--request', required=True)
    prepare.add_argument('--request-sha256', required=True)
    prepare.add_argument('--output', required=True)
    load = commands.add_parser('open')
    load.add_argument('--intake', required=True)
    load.add_argument('--intake-sha256', required=True)
    load.add_argument('--combination-id', required=True)
    load.add_argument('--use', choices=USES, required=True)
    load.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'prepare':
            request = read(bound(args.request, args.request_sha256))
            result = prepare_task(**request)
            write_intake(args.output, result)
            print(json.dumps(dict(status='registered_not_qualified', output=reference(args.output),
                combination_id=result['combination_id'], qualification=result['qualification']), ensure_ascii=False))
        else:
            model, receipt = open_task(args.intake, args.intake_sha256, purpose=args.use,
                                      expected_combination_id=args.combination_id)
            receipt['native_model'] = dict(nq=model.nq, nv=model.nv, ngeom=model.ngeom)
            # Receipt output must also stay outside the generator/package/evidence.
            current = read(bound(args.intake, args.intake_sha256))
            write_intake(args.output, dict(inputs=current['inputs'], **receipt))
            print(json.dumps(dict(status='admitted', purpose=args.use, output=reference(args.output)), ensure_ascii=False))
        return 0
    except (Rejected, KeyError, TypeError, ValueError, OSError) as exc:
        print(json.dumps(dict(status='rejected', reason=str(exc)), ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
