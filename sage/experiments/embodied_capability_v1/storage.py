"""Lossless HDF5 storage derivatives; never new observations or qualifications."""
from pathlib import Path
import json
import h5py
import numpy as np
from .dataset import sha


def _blocks(dataset, rows=12):
    if not dataset.shape:
        yield (), dataset[()]
    else:
        for start in range(0, len(dataset), rows):
            key = slice(start, min(start + rows, len(dataset)))
            yield key, dataset[key]


def _equal(a, b):
    if a.shape != b.shape or a.dtype != b.dtype:
        return False
    return all(np.array_equal(values, b[key]) for key, values in _blocks(a))


def pack_sequence(binding, destination):
    """Shuffle numeric bytes before gzip; alias raw depth only when exactly equal."""
    destination = Path(destination)
    if destination.exists():
        raise ValueError('destination_already_exists')
    if sha(binding['path']) != binding['sha256']:
        raise ValueError('source_hash_mismatch')
    paths, aliases = [], []
    with h5py.File(binding['path'], 'r') as source, h5py.File(destination, 'x') as packed:
        if json.loads(source.attrs['metadata']) != binding['metadata']:
            raise ValueError('source_metadata_mismatch')
        for key, value in source.attrs.items():
            packed.attrs[key] = value
        def collect(name, node):
            paths.append(name)
        source.visititems(collect)
        for name in sorted(paths):
            node = source[name]
            if isinstance(node, h5py.Group):
                created = packed.require_group(name)
            else:
                parent, _, leaf = name.rpartition('/')
                group = packed.require_group(parent)
                public = None
                if name.startswith('privileged/') and name.endswith('/raw_render_depth_m'):
                    camera = name.split('/')[1]
                    candidate = f'cameras/{camera}/depth_m'
                    if candidate in packed and _equal(node, source[candidate]):
                        public = candidate
                if public:
                    group[leaf] = packed[public]
                    created = packed[name]
                    aliases.append(dict(path=name,identical_to=public))
                else:
                    options = {}
                    if node.shape:
                        options = dict(chunks=node.chunks or True, compression='gzip', compression_opts=4, shuffle=node.dtype.itemsize > 1)
                    created = group.create_dataset(leaf, shape=node.shape, dtype=node.dtype, **options)
                    for key, values in _blocks(node):
                        created[key] = values
            for key, value in node.attrs.items():
                created.attrs[key] = value
    # Re-open both files and verify every named value, including aliased private paths.
    datasets = 0
    with h5py.File(binding['path'], 'r') as source, h5py.File(destination, 'r') as packed:
        if set(source.attrs) != set(packed.attrs) or any(not np.array_equal(source.attrs[k], packed.attrs[k]) for k in source.attrs):
            raise ValueError('root_attributes_changed')
        for name in paths:
            left, right = source[name], packed[name]
            if set(left.attrs) != set(right.attrs) or any(not np.array_equal(left.attrs[k], right.attrs[k]) for k in left.attrs):
                raise ValueError('node_attributes_changed')
            if isinstance(left, h5py.Dataset):
                if not _equal(left, right):
                    raise ValueError('lossless_value_check_failed:' + name)
                datasets += 1
    if sha(binding['path']) != binding['sha256']:
        raise ValueError('source_changed_during_copy')
    result = dict(path=str(destination.resolve()), sha256=sha(destination), metadata=binding['metadata'])
    return result, dict(source_sha256=binding['sha256'], packed_sha256=result['sha256'], source_bytes=Path(binding['path']).stat().st_size, packed_bytes=destination.stat().st_size, datasets_exact=datasets, aliases=aliases, physics_steps=0, new_observations=0, method='lossless byte shuffle+gzip; exact-equality-checked HDF5 depth hard links')
