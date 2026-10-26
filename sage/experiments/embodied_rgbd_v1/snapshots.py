"""Export audited static camera observations without inventing action transitions."""
from pathlib import Path
import hashlib
import json
import h5py
import numpy as np


def reference(path):
    path = Path(path).resolve()
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def checked(ref):
    if reference(ref['path']) != ref:
        raise ValueError('snapshot source hash mismatch')
    return Path(ref['path'])


def export_snapshots(raw_path, geometry_path, audit_path, directory):
    audit = json.loads(Path(audit_path).read_text())
    if not audit.get('admitted') or not audit.get('metric_depth_aligned'):
        raise ValueError('camera geometry not admitted')
    raw, geometry = np.load(raw_path), np.load(geometry_path)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    metadata = dict(schema='embodied-static-rgbd/v1', source_time=float(raw['time']),
                    snapshots=2, transitions=0, qualified_training=False,
                    task_executed=False, depth_unit='m',
                    pixel_convention='integer indices are pixel centers',
                    pose_convention='optical (+x right,+y down,+z forward) to world',
                    invalid_depth='explicit valid mask; no hole filling')
    with h5py.File(directory/'snapshots.h5', 'x') as file:
        file.attrs['metadata'] = json.dumps(metadata, sort_keys=True)
        for name in ['cam_d405', 'cam_d435i']:
            values = dict(rgb=raw[name+'_rgb'], depth_m=geometry[name+'_aligned_depth_m'],
                          valid=geometry[name+'_valid'], source_pixel=geometry[name+'_depth_source_pixel'],
                          K=geometry[name+'_rgb_K'], optical_to_world=geometry[name+'_rgb_optical_to_world'])
            if values['rgb'].dtype != np.uint8 or values['depth_m'].dtype != np.float32:
                raise ValueError('camera dtype mismatch')
            if values['depth_m'].shape != values['rgb'].shape[:2]:
                raise ValueError('unaligned shape')
            if not np.array_equal(values['valid'], values['source_pixel'] >= 0):
                raise ValueError('missing validity provenance')
            for key, value in values.items():
                file.create_dataset(name+'/'+key, data=value, compression='gzip')
    record = dict(metadata=metadata, raw=reference(raw_path), geometry=reference(geometry_path),
                  audit=reference(audit_path), hdf5=reference(directory/'snapshots.h5'),
                  implementation=reference(__file__))
    (directory/'BINDING.json').write_text(json.dumps(record, indent=2))
    return reference(directory/'BINDING.json')


class SavedRGBDSnapshots:
    def __init__(self, binding, purpose='inspection'):
        if purpose != 'inspection':
            raise ValueError('static snapshots are not qualified task training episodes')
        record = json.loads(checked(binding).read_text())
        for name in ['raw', 'geometry', 'audit', 'implementation', 'hdf5']:
            checked(record[name])
        self.metadata = record['metadata']
        if self.metadata['transitions'] != 0 or self.metadata['qualified_training']:
            raise ValueError('static snapshot labels changed')
        with h5py.File(record['hdf5']['path'], 'r') as file:
            if json.loads(file.attrs['metadata']) != self.metadata:
                raise ValueError('metadata mismatch')
            self.frames = [{key: file[name][key][:] for key in file[name]}
                           for name in ['cam_d405', 'cam_d435i']]

    def __len__(self):
        return len(self.frames)

    def __getitem__(self, index):
        return {key: value.copy() for key, value in self.frames[index].items()}
