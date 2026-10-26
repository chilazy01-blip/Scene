"""Official-reader shard caches, with explicit episode boundaries and train-only stats."""
from pathlib import Path
import numpy as np
import torch
from sage.experiments.embodied_abc_v1.learning_data import CachedSamples, resize_rgb
from sage.experiments.embodied_scene_bridge.contracts import read


class Samples:
    def __init__(self, run, split, chunk_size):
        self.run = Path(run)
        self.entries = [e for e in read(self.run/'protocol/DATA_SPLIT.json')['episodes'] if e['split'] == split]
        self.shards = [CachedSamples(self.run/'cache'/str(e['seed']), chunk_size) for e in self.entries]
        self.starts = np.r_[0, np.cumsum([s.length for s in self.shards])]
        self.length = int(self.starts[-1])

    def batch(self, indices):
        indices = np.asarray(indices, dtype='i8')
        if np.any(indices < 0) or np.any(indices >= self.length):
            raise IndexError('sample_out_of_range')
        owners = np.searchsorted(self.starts[1:], indices, side='right')
        result = None
        for owner in np.unique(owners):
            positions = np.flatnonzero(owners == owner)
            batch = self.shards[owner].batch(indices[positions] - self.starts[owner])
            if result is None:
                result = {k: torch.empty((len(indices), *v.shape[1:]), dtype=v.dtype) for k, v in batch.items()}
            for key, value in batch.items():
                result[key][positions] = value
        return result

    def validation_indices(self):
        return np.concatenate([self.starts[i] + np.linspace(0, s.length-1, min(128, s.length), dtype=int)
                               for i, s in enumerate(self.shards)])


def stats(run):
    return {k: {name: np.asarray(value, dtype=np.float32) for name, value in v.items()}
            for k, v in read(Path(run)/'cache/TRAIN_STATS.json').items()}


def observation(proprio, images):
    sample = {'observation.state': torch.from_numpy(np.asarray(proprio, dtype='f4'))}
    for cam, pixels in images.items():
        sample['observation.images.' + cam] = resize_rgb(
            torch.from_numpy(pixels.copy()).permute(2, 0, 1).float()/255.).float()/255.
    return sample
