"""Explicit CLI for delivered scenes and data; never launches legacy queues."""
import argparse
import json
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__)
    commands=p.add_subparsers(dest='command',required=True)
    inspect=commands.add_parser('inspect');inspect.add_argument('--data',required=True);inspect.add_argument('--split',default='train')
    validate=commands.add_parser('validate');validate.add_argument('--data',required=True)
    collect=commands.add_parser('collect');collect.add_argument('--scene',required=True);collect.add_argument('--output',required=True)
    collect.add_argument('--seed',type=int,required=True);collect.add_argument('--split',default='development')
    train=commands.add_parser('train');train.add_argument('--data',required=True);train.add_argument('--output',required=True)
    train.add_argument('--epochs',type=int,default=40)
    evaluate=commands.add_parser('evaluate');evaluate.add_argument('--scene',required=True);evaluate.add_argument('--output',required=True)
    evaluate.add_argument('--seed',type=int,required=True);evaluate.add_argument('--checkpoint',required=True)
    evaluate.add_argument('--mode',choices=['learned','template_only','zero_rgb'],default='learned')
    a=p.parse_args()
    if a.command=='inspect':
        from .dataset import EpisodeDataset
        data=EpisodeDataset(a.data,a.split);row=data[0]
        print(json.dumps(dict(transitions=len(data),fields={k:list(v.shape) if hasattr(v,'shape') else type(v).__name__ for k,v in row.items()}),indent=2))
    elif a.command=='validate':
        from .dataset import validate_dataset
        print(json.dumps(validate_dataset(a.data),indent=2))
    elif a.command=='collect':
        from .dataset import collect
        print(collect(a.scene,a.output,a.seed,a.split))
    elif a.command=='train':
        from .learning import train
        train(a.data,a.output,a.epochs)
    elif a.command=='evaluate':
        from .learning import evaluate
        print(evaluate(a.scene,a.output,a.seed,a.checkpoint,a.mode))


if __name__=='__main__':main()
