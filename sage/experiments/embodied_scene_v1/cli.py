"""Explicit build/run/render entry points. Run heavy jobs under the project guard."""
import argparse
import json
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    b=sub.add_parser('build');b.add_argument('--source',required=True);b.add_argument('--output',required=True);b.add_argument('--stretch-model-dir',required=True)
    r=sub.add_parser('run');r.add_argument('--package',required=True);r.add_argument('--output',required=True);r.add_argument('--task',choices=['navigate','pick_place'],required=True);r.add_argument('--variant',choices=['baseline','repaired'],default='repaired');r.add_argument('--reference',action='store_true');r.add_argument('--physics-only',action='store_true')
    v=sub.add_parser('render');v.add_argument('--episode',required=True);v.add_argument('--output',required=True)
    i=sub.add_parser('inspect');i.add_argument('--episode',required=True)
    a=p.parse_args()
    if a.command=='build':
        from .package import export_package
        export_package(a.source,a.output,a.stretch_model_dir)
    elif a.command=='run':
        from .runner import run
        result=run(a.package,a.output,a.task,a.variant,a.reference,a.physics_only)
        if not result['success']:raise SystemExit(2)
    elif a.command=='render':
        from .render import render_episode
        render_episode(a.episode,a.output)
    else:
        result=json.loads((Path(a.episode)/'result.json').read_text())
        print(json.dumps(result,indent=2,ensure_ascii=False))


if __name__=='__main__':main()
