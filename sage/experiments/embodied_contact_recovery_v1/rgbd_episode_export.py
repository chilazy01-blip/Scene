"""Export one complete portable RGB-D episode; actual reading is a separate bounded job."""
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
    physical = c.read(cfg['actuator_contract_file'])
    units = {row['joint']: row['control_unit'] for row in physical['actuator_contract']}
    assert set(units) == set(evidence['joint_names']) and len(units) == 43
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
    task_instruction = 'Pick up the red cylinder from the brown table, walk to the other table, and place the cylinder upright.'
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
        terminal_time = float(f.attrs['source_terminal_time_s'])
        final_frame_duration = terminal_time - float(f['trajectory/timestamp'][-1])
        for i in range(count):
            dataset.add_frame(public_frame(f, i),
                              task=task_instruction,
                              timestamp=i / 25)
            if i % 50 == 0:
                c.write(work / 'PROGRESS.json', {'phase': 'export', 'rows': i, 'total': count})
        dataset.save_episode(); dataset.stop_image_writer()
    # Moving the virtual canonical file and its relative chunk tree to a new
    # dataset root is itself a real portability exercise, not a path assertion.
    shutil.copytree(assembled / 'chunks', root / 'chunks', copy_function=os.link)
    os.link(assembled / 'canonical.h5', root / 'canonical.h5')
    quality = c.read(cfg['contact_quality_report'])
    assert quality['passed'] and quality['source_trace_sha256'] == evidence['source_trace_sha256']
    assert quality['RGBD_frames'] == count and evidence['complete_physical_task_record']
    assert c.sha(cfg['contact_quality_index']) == quality['quality_index_sha256']
    (root / 'quality').mkdir()
    os.link(cfg['contact_quality_index'], root / 'quality/contact_quality_index.h5')
    c.write(root / 'quality/CONTACT_QUALITY_BINDING.json', quality)
    files = {str(path.relative_to(root)): c.sha(path)
             for path in root.rglob('*') if path.is_file()}
    binding = {**evidence, 'export_files': files, 'canonical_relative_path': 'canonical.h5',
               'assembly_binding_sha256': c.sha(assembled / 'BINDING.json'),
               'physical_source_independent_reintegration': True,
               'source_task_success': False, 'production_accepted': False,
               'task_instruction': task_instruction,
               'task_instruction_contains_no_future_outcome_label': True,
               'task_learning_verified': False, 'training_updates': 0,
               'action_units_by_joint': units,
               'actuator_contract_evidence_sha256': c.sha(cfg['actuator_contract_file']),
               'privileged_quality_sidecar': 'quality/contact_quality_index.h5',
               'quality_sidecar_is_not_actor_input': True,
               'action_semantics': 'Actual actuator commands:29body motor torques and14finger position references; joint order explicitly bound.',
               'temporal_sampling': {'RGBD_and_observation_hz': 25, 'action_samples_per_frame': 2,
                                     'action_sample_spacing_s': .02, 'source_physics_and_control_hz': 400,
                                     'source_terminal_time_s': terminal_time,
                                     'final_frame_observed_duration_s': final_frame_duration,
                                     'action_valid_means_sample_timestamp_exists': True,
                                     'source_all400Hz_substeps_retained_in_separate_hashed_TRACE': True,
                                     'public_action_chunk_is_not_lossless400Hz_command_replay': True},
               'full_duration_claim': 'All25Hz samples covering the source task duration; full400Hz authoritative trace is separately archived and hashed.'}
    c.write(root / 'BINDING.json', binding)
    result = {'passed': True, 'dataset': str(root), 'exported_rows': count,
              'actual_consumer_pending': True, 'source_independent_audit_passed': True,
              'complete_source_episode': evidence['complete_physical_task_record'],
              'episode_task_success': False, 'production_accepted': False,
              'new_physics_steps': 0, 'new_render_passes': 0, 'training_updates': 0,
              'dataset_binding_sha256': c.sha(root / 'BINDING.json')}
    c.write(work / 'EXPORT_REPORT.json', result)
    finish(result)


if __name__ == '__main__':
    main(sys.argv[1])
