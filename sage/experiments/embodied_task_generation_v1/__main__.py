import argparse,json
from .evidence import open_task
from sage.experiments.embodied_scene_quality_v1.contracts import Rejected


def main(argv=None):
    parser=argparse.ArgumentParser(description='Recompute surface task evidence before native model loading.')
    parser.add_argument('--evidence',required=True);parser.add_argument('--sha256',required=True)
    parser.add_argument('--purpose',required=True);parser.add_argument('--request-id',required=True)
    args=parser.parse_args(argv)
    try:
        model,result=open_task(args.evidence,args.sha256,args.purpose,args.request_id)
    except Rejected as exc:
        print(json.dumps(dict(qualified=False,reason=str(exc))));return 2
    print(json.dumps(dict(qualified=True,request_id=result['request_id'],purpose=args.purpose,nq=model.nq,nv=model.nv)))
    return 0


if __name__=='__main__':raise SystemExit(main())
