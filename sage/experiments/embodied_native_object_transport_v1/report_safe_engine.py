"""Only JSON-boundary NumPy scalar conversion; identical frozen physical engine."""

import argparse
from pathlib import Path
import numpy as np
from . import engine
from sage.experiments.embodied_transport_hybrid_v1.prepare import save


def plain(value):
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    return value


def safe_save(path, value):
    save(path, plain(value))


def run(root, output, ticks, admission):
    engine.save = safe_save
    return engine.run(root, output, ticks, admission)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--ticks", type=int, required=True)
    ap.add_argument("--admission", type=Path)
    a = ap.parse_args()
    run(a.root, a.output, a.ticks, a.admission)
