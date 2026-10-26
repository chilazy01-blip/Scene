import argparse,json


def main():
    parser=argparse.ArgumentParser();commands=parser.add_subparsers(dest='command',required=True)
    construct=commands.add_parser('construct');construct.add_argument('--config',required=True);construct.add_argument('--protocol',required=True)
    resume=commands.add_parser('resume-conversion');resume.add_argument('--config',required=True);resume.add_argument('--protocol',required=True)
    inspect=commands.add_parser('load');inspect.add_argument('--binding',required=True);inspect.add_argument('--sha256',required=True)
    inspect.add_argument('--purpose',required=True);inspect.add_argument('--request-id',required=True)
    args=parser.parse_args()
    if args.command=='resume-conversion':
        from .pipeline import resume_conversion
        result=resume_conversion(args.config,args.protocol);return 0 if result['status']=='constructed' else 1
    if args.command=='construct':
        from .pipeline import run
        result=run(args.config,args.protocol);return 0 if result['status']=='constructed' else 1
    from .entry import load
    try:
        model,result=load(args.binding,args.sha256,args.purpose,args.request_id)
        print(json.dumps(dict(loaded=True,ngeom=model.ngeom,verification=result)));return 0
    except (ValueError,OSError,KeyError) as exc:print(json.dumps(dict(loaded=False,reason=str(exc))));return 2


if __name__=='__main__':raise SystemExit(main())
