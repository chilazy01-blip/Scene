import argparse,json
from .dataset import TrajectoryDataset

def main():
 parser=argparse.ArgumentParser(description='Read a pinned real development trajectory; no production admission.')
 parser.add_argument('--binding',required=True);parser.add_argument('--sha256',required=True)
 parser.add_argument('--purpose',default='proprio_development');parser.add_argument('--modality',default='proprio')
 args=parser.parse_args()
 try:
  ds=TrajectoryDataset(args.binding,args.sha256,args.purpose,(args.modality,))
 except (ValueError,OSError,KeyError) as exc:
  print(json.dumps(dict(status='rejected',reason=str(exc)),ensure_ascii=False));return 2
 print(json.dumps(dict(status='accepted',metadata=ds.metadata,first_time=float(ds[0]['time']),last_time=float(ds[len(ds)-1]['next_time'])),ensure_ascii=False));return 0
if __name__=='__main__':raise SystemExit(main())
