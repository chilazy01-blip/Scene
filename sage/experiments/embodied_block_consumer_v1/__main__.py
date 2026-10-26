import argparse,json


def main():
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='command',required=True)
    cmd=sub.add_parser('load');cmd.add_argument('--binding',required=True);cmd.add_argument('--sha256',required=True);cmd.add_argument('--purpose',required=True);cmd.add_argument('--request-id',required=True)
    cmd=sub.add_parser('consume');cmd.add_argument('--binding',required=True);cmd.add_argument('--sha256',required=True);cmd.add_argument('--output',required=True)
    args=p.parse_args()
    if args.command=='load':
        from .entry import load
        try:
            model,dataset,score=load(args.binding,args.sha256,args.purpose,args.request_id)
            print(json.dumps(dict(loaded=True,nq=model.nq,blocks=len(dataset),verification=score)));return 0
        except (ValueError,OSError,KeyError) as exc:print(json.dumps(dict(loaded=False,reason=str(exc))));return 2
    from .execution import consume
    result=consume(args.binding,args.sha256,args.output)
    print(json.dumps(dict(status=result['status'],steps=result['new_physics_steps'],errors=result['maximum_errors'])));return 0

if __name__=='__main__':raise SystemExit(main())
