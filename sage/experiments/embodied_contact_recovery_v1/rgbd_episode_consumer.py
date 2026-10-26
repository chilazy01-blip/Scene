"""Export and consume a portable bound RGB-D episode, preserving failure labels."""
import os
import sys
import shutil
from pathlib import Path
import numpy as np
import h5py
from .work import P, c, finish


def main(config_path):
    cfg = c.read(config_path)
    work = Path(os.environ['CONTINUOUS_JOB_DIR'])
    assembled = Path(cfg['assembled_root'])
    evidence = c.read(assembled / 'BINDING.json')
    assert evidence['completed'] and evidence['canonical_independent_audit_passed']
    assert c.sha(assembled / 'canonical.h5') == evidence['canonical_sha256']
    for record in evidence['chunks']:
        assert c.sha(assembled / record['relative_path']) == record['sha256']
    sys.path.append(str(P.parent / 'hmg_external_control_20261007/vendor'))
    cache = work / 'hf_cache'; cache.mkdir()
    os.environ.update(HF_HOME=str(cache), HF_DATASETS_CACHE=str(cache / 'datasets'),
                      HF_HUB_CACHE=str(cache / 'hub'), HF_HUB_OFFLINE='1',
                      HF_DATASETS_OFFLINE='1', TOKENIZERS_PARALLELISM='false')
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    from sage.experiments.embodied_payload_data_v1.dataset_export import features, frame
    from sage.experiments.embodied_payload_data_v1.typed_reader import RGBDTrainingDataset
    from torch.utils.data import DataLoader
    cameras = evidence['cameras']
    schema = features({'joint_names': evidence['joint_names'], 'cameras': cameras})
    schema['observation.previous_command_valid'] = {'dtype': 'uint8', 'shape': (1,), 'names': ['valid']}
    schema['episode.task_success'] = {'dtype': 'uint8', 'shape': (1,), 'names': ['success']}
    schema['episode.segment_truncated'] = {'dtype': 'uint8', 'shape': (1,), 'names': ['truncated']}
    def public_frame(f, i):
        value = frame(f, i, cameras)
        value['observation.previous_command_valid'] = np.array([f['trajectory/previous_command_valid'][i]], dtype='u1')
        value['episode.task_success'] = np.zeros(1, dtype='u1')
        value['episode.segment_truncated'] = np.array([evidence['segment_truncated']], dtype='u1')
        return value
    root = work / 'dataset'
    dataset = LeRobotDataset.create(repo_id='local/g1-contact-recovery-rgbd', fps=25,
                                   features=schema, root=root, robot_type='G1',
                                   use_videos=False, video_backend='pyav')
    with h5py.File(assembled / 'canonical.h5', 'r') as f:
        count = len(f['trajectory/timestamp'])
        for i in range(count):
            dataset.add_frame(public_frame(f, i),
                              task='Failed full-body research task: contact quality and object placement failed. Production acceptance false.',
                              timestamp=i / 25)
            if i % 50 == 0:
                c.write(work / 'PROGRESS.json', {'phase': 'export', 'rows': i, 'total': count})
        dataset.save_episode(); dataset.stop_image_writer()
    # Moving the virtual canonical file and its relative chunk tree to a new
    # dataset root is itself a real portability exercise, not a path assertion.
    shutil.copytree(assembled / 'chunks', root / 'chunks', copy_function=os.link)
    os.link(assembled / 'canonical.h5', root / 'canonical.h5')
    files = {str(path.relative_to(root)): c.sha(path)
             for path in root.rglob('*') if path.is_file()}
    binding = {**evidence, 'export_files': files, 'canonical_relative_path': 'canonical.h5',
               'assembly_binding_sha256': c.sha(assembled / 'BINDING.json'),
               'physical_source_independent_reintegration': True,
               'source_task_success': False, 'production_accepted': False,
               'task_learning_verified': False, 'training_updates': 0}
    c.write(root / 'BINDING.json', binding)
    reader = RGBDTrainingDataset(root)
    errors, seen = {}, 0
    with h5py.File(root / 'canonical.h5', 'r') as f:
        for batch in DataLoader(reader, batch_size=8, num_workers=0, shuffle=False):
            for j in range(len(batch['frame_index'])):
                i = int(batch['frame_index'][j]); assert i == seen; seen += 1
                for key, expected in public_frame(f, i).items():
                    got = batch[key][j].numpy()
                    if key.startswith('observation.images.'):
                        got = np.rint(got.transpose(1, 2, 0) * 255).astype('u1')
                    error = float(np.max(abs(got.astype(float) - expected.astype(float))))
                    errors[key] = max(errors.get(key, 0.), error)
                for camera in cameras:
                    for key, field in [('depth_m', 'depth_m'), ('depth_valid', 'valid')]:
                        name = 'observation.' + key + '.' + camera
                        error = float(np.max(abs(batch[name][j].numpy().astype(float)
                                                 - f['cameras/' + camera + '/' + field][i].astype(float))))
                        errors[name] = max(errors.get(name, 0.), error)
            c.write(work / 'PROGRESS.json', {'phase': 'real_consumer', 'rows': seen, 'total': count})
    assert seen == count and all(x == 0 for x in errors.values()), errors
    result = {'passed': True, 'dataset': str(root), 'actual_public_RGBD_consumer_rows': seen,
              'reader': 'RGBDTrainingDataset via DataLoader(batch_size=8)',
              'maximum_field_errors': errors, 'portable_relative_virtual_sources_read': True,
              'source_independent_physical_audit_passed': True,
              'complete_source_episode': evidence['complete_physical_task_record'],
              'episode_task_success': False, 'episode_segment_truncated': evidence['segment_truncated'],
              'production_accepted': False, 'task_learning_verified': False,
              'new_physics_steps': 0, 'new_render_passes': 0, 'training_updates': 0,
              'dataset_binding_sha256': c.sha(root / 'BINDING.json')}
    c.write(work / 'DATASET_READ_REPORT.json', result)
    finish(result)


if __name__ == '__main__':
    main(sys.argv[1])
