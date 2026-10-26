import argparse,json
from pathlib import Path


def main():
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='command',required=True)
    for name in ['prepare','render']:
        command=sub.add_parser(name);command.add_argument('--protocol',required=True);command.add_argument('--root',required=True)
    command=sub.add_parser('load');command.add_argument('--binding',required=True);command.add_argument('--sha256',required=True);command.add_argument('--purpose',required=True);command.add_argument('--request-id',required=True)
    args=parser.parse_args()
    if args.command=='prepare':
        from .contract import prepare
        result=prepare(args.protocol,Path(args.root)/'evidence');print(json.dumps(dict(prepared=result['passed'],frames=351,physics_steps=0)));return 0
    if args.command=='render':
        from .render import render
        result=render(args.protocol,args.root);print(json.dumps(dict(complete=result['complete'],visibility_passed=result['passed'],failed_frames=len(result['failed_frames']),rgb_renders=result['rgb_renders'])));return 0
    from .dataset import EpisodeDataset
    try:
        dataset=EpisodeDataset(args.binding,args.sha256,args.purpose,args.request_id);samples=[]
        for k in [0,175,349]:
            row=dataset[k];samples.append(dict(index=k,fields=sorted(row),action_shape=list(row['action'].shape),rgb_shape=list(row['rgb'].shape),time=row['time'],next_time=row['next_time']))
        print(json.dumps(dict(loaded=True,verification=dataset.verification,samples=samples)));return 0
    except (ValueError,OSError,KeyError,IndexError) as exc:
        print(json.dumps(dict(loaded=False,reason=str(exc))));return 2

if __name__=='__main__':raise SystemExit(main())
