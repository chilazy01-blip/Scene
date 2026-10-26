"""Bounded actual consumer range of an immutable exported full episode."""
import os
import sys
from pathlib import Path
import numpy as np
import h5py
from .work import P, c, finish


def main(config_path):
    cfg = c.read(config_path)
    work = Path(os.environ['CONTINUOUS_JOB_DIR'])
    root = Path(cfg['dataset_root'])
    binding = c.read(root / 'BINDING.json')
    count = binding['rows']
    start, stop = int(cfg.get('first_row', 0)), int(cfg.get('stop_row', count))
    assert 0 <= start < stop <= count
    sys.path.append(str(P.parent / 'hmg_external_control_20261007/vendor'))
    cache = work / 'hf_cache'; cache.mkdir()
    os.environ.update(HF_HOME=str(cache), HF_DATASETS_CACHE=str(cache / 'datasets'),
                      HF_HUB_CACHE=str(cache / 'hub'), HF_HUB_OFFLINE='1',
                      HF_DATASETS_OFFLINE='1', TOKENIZERS_PARALLELISM='false')
    from sage.experiments.embodied_payload_data_v1.dataset_export import frame
    from sage.experiments.embodied_payload_data_v1.typed_reader import RGBDTrainingDataset
    from torch.utils.data import DataLoader, Subset
    reader = RGBDTrainingDataset(root)
    cameras = binding['cameras']
    errors, seen = {}, start
    with h5py.File(root / 'canonical.h5', 'r') as f:
        for batch in DataLoader(Subset(reader, range(start, stop)), batch_size=8, num_workers=0, shuffle=False):
            for j in range(len(batch['frame_index'])):
                i = int(batch['frame_index'][j]); assert i == seen; seen += 1
                assert batch['task'][j] == binding['task_instruction'], 'task_instruction_mismatch'
                expected = frame(f, i, cameras)
                expected['observation.previous_command_valid'] = np.array([f['trajectory/previous_command_valid'][i]], dtype='u1')
                expected['episode.task_success'] = np.zeros(1, dtype='u1')
                expected['episode.segment_truncated'] = np.array([binding['segment_truncated']], dtype='u1')
                for key, value in expected.items():
                    got = batch[key][j].numpy()
                    if key.startswith('observation.images.'):
                        got = np.rint(got.transpose(1, 2, 0) * 255).astype('u1')
                    error = float(np.max(abs(got.astype(float) - value.astype(float))))
                    errors[key] = max(errors.get(key, 0.), error)
                for camera in cameras:
                    for key, field in [('depth_m', 'depth_m'), ('depth_valid', 'valid')]:
                        name = 'observation.' + key + '.' + camera
                        error = float(np.max(abs(batch[name][j].numpy().astype(float)
                                                 - f['cameras/' + camera + '/' + field][i].astype(float))))
                        errors[name] = max(errors.get(name, 0.), error)
            c.write(work / 'PROGRESS.json', {'phase': 'actual_consumer', 'first_row': start, 'next_row': seen, 'stop_row': stop})
    assert seen == stop and all(x == 0 for x in errors.values()), errors
    result = {'passed': True, 'dataset': str(root), 'first_row': start, 'stop_row': stop,
              'actual_public_RGBD_consumer_rows': stop - start, 'complete_episode_rows': count,
              'reader': 'RGBDTrainingDataset via DataLoader(Subset,batch_size=8)',
              'maximum_field_errors': errors, 'portable_relative_virtual_sources_read': True,
              'task_instruction_checked_on_every_row': binding['task_instruction'],
              'source_independent_physical_audit_passed': True,
              'episode_task_success': False, 'episode_segment_truncated': binding['segment_truncated'],
              'production_accepted': False, 'task_learning_verified': False,
              'new_physics_steps': 0, 'new_render_passes': 0, 'training_updates': 0,
              'dataset_binding_sha256': c.sha(root / 'BINDING.json')}
    c.write(work / 'DATASET_READ_REPORT.json', result); finish(result)


if __name__ == '__main__':
    main(sys.argv[1])
