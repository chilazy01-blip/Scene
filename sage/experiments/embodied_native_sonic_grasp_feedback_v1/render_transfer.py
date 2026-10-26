import argparse,os,resource
from pathlib import Path
from .visualize_transfer import run

if __name__=='__main__':
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);ap.add_argument('--episode',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();run(a.root,a.output,a.episode)
