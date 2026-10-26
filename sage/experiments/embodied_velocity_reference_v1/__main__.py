import argparse,json
from pathlib import Path


def main():
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='command',required=True)
    load=sub.add_parser('load');load.add_argument('--binding',required=True);load.add_argument('--sha256',required=True);load.add_argument('--purpose',required=True);load.add_argument('--request-id',required=True)
    execute=sub.add_parser('execute');execute.add_argument('--protocol',required=True)
    args=parser.parse_args()
    if args.command=='load':
        from .entry import load
        try:
            model,score=load(args.binding,args.sha256,args.purpose,args.request_id)
            print(json.dumps(dict(loaded=True,nq=model.nq,nu=model.nu,verification=score)));return 0
        except (ValueError,OSError,KeyError) as exc:print(json.dumps(dict(loaded=False,reason=str(exc))));return 2
    from sage.experiments.embodied_scene_quality_v2.contracts import read,write_new
    from .execution import episode,replay
    p=read(args.protocol);root=Path(args.protocol).parent.parent
    a=episode(p['source_config'],args.protocol,root/'episodes/episode');b=replay(p['source_config'],root/'episodes/episode',root/'episodes/replay')
    write_new(root/'evidence/EXECUTION.json',dict(episode=a,replay=b,new_physical_attempts=2,new_physics_steps=a['new_physics_steps']+b['new_physics_steps']))
    print(json.dumps(dict(episode_status=a['status'],replay_status=b['status'],new_physics_steps=a['new_physics_steps']+b['new_physics_steps'])));return 0


if __name__=='__main__':raise SystemExit(main())
