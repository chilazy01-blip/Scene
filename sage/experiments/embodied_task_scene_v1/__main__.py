import argparse,json
from .entry import open_scene
from sage.experiments.embodied_scene_quality_v1.contracts import Rejected


def main(argv=None):
    parser=argparse.ArgumentParser(description='Load a bound whole-scene start/goal model after independent pose verification.')
    for name in ['entry','sha256','request-id','state','purpose']:parser.add_argument('--'+name,required=True)
    args=parser.parse_args(argv)
    try:model,result=open_scene(args.entry,args.sha256,args.request_id,args.state,args.purpose)
    except Rejected as exc:
        print(json.dumps(dict(allowed=False,reason=str(exc)),ensure_ascii=False));return 2
    print(json.dumps(dict(allowed=True,request_id=args.request_id,state=args.state,purpose=args.purpose,nq=model.nq,nv=model.nv,ngeom=model.ngeom)))
    return 0


if __name__=='__main__':raise SystemExit(main())
