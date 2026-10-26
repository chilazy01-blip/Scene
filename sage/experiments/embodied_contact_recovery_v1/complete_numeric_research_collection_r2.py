"""Export all audited full-task numeric records and read every public row."""
import os
import sys
import shutil
from pathlib import Path
import numpy as np
import h5py
from .work import E, P, c, finish


def numeric_frame(source, i):
    from sage.experiments.embodied_payload_data_v1.dataset_export import frame
    value = frame(source, i, [])
    value['observation.previous_command_valid'] = np.array(
        [source['trajectory/previous_command_valid'][i]], dtype='u1')
    return value


def main(config):
    cfg = c.read(config)
    work = Path(os.environ['CONTINUOUS_JOB_DIR'])
    sys.path.append(str(P.parent/'hmg_external_control_20261007/vendor'))
    cache = work/'hf_cache'
    cache.mkdir()
    os.environ.update(HF_HOME=str(cache), HF_DATASETS_CACHE=str(cache/'datasets'),
                      HF_HUB_CACHE=str(cache/'hub'), HF_HUB_OFFLINE='1',
                      HF_DATASETS_OFFLINE='1', TOKENIZERS_PARALLELISM='false')
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    from sage.experiments.embodied_payload_data_v1.dataset_export import features
    from sage.experiments.embodied_payload_data_v1.typed_reader import TypedLeRobotDataset
    first = c.read(cfg['episodes'][0]['numeric_report'])
    schema = features({'joint_names': first['joint_names'], 'cameras': []})
    schema['observation.previous_command_valid'] = {'dtype':'uint8', 'shape':(1,), 'names':['valid']}
    root = work/'dataset'
    old_root = Path(cfg['existing_export_root'])
    assert old_root.is_dir()
    shutil.copytree(old_root,root)
    assert all(c.sha(p) == c.sha(root/p.relative_to(old_root)) for p in old_root.rglob('*') if p.is_file())
    episodes = []
    offset = 0
    for episode_index, item in enumerate(cfg['episodes']):
        report = c.read(item['numeric_report'])
        result = c.read(item['task_result'])
        audit = c.read(item['task_audit'])
        assert report['passed'] and report['joint_names'] == first['joint_names']
        assert report['numeric_h5_sha256'] == c.sha(item['numeric_h5'])
        assert report['source_trace_sha256'] == c.sha(item['source_trace'])
        assert audit['passed'] and audit['independent_process_continuous_reintegration_and_policy_recompute']
        assert not result['research_task_passed'] and not result['production_accepted']
        steps = result['trace_summary']['physics_steps']
        with h5py.File(item['numeric_h5'], 'r') as f:
            count = len(f['trajectory/timestamp'])
            assert count == (steps+15)//16
        episodes.append({'key':item['key'], 'episode_index':episode_index, 'global_first_frame':offset,
            'global_stop_frame':offset+count, 'rows':count, 'source_physics_steps':steps,
            'numeric_source_sha256':report['numeric_h5_sha256'], 'source_trace_sha256':report['source_trace_sha256'],
            'source_task_result_sha256':c.sha(item['task_result']), 'source_audit_sha256':c.sha(item['task_audit']),
            'source_quality_sha256':c.sha(item['task_quality']), 'source_task_success':False,
            'production_accepted':False, 'split':'development_research_failure'})
        offset += count
    reader = TypedLeRobotDataset(root)
    assert len(reader) == offset
    errors = {}
    scalar_normalizations = {}
    for item, episode in zip(cfg['episodes'], episodes):
        with h5py.File(item['numeric_h5'], 'r') as f:
            for i in range(episode['rows']):
                index = episode['global_first_frame']+i
                actual = reader[index]
                assert int(actual['index']) == index
                assert int(actual['episode_index']) == episode['episode_index']
                assert int(actual['frame_index']) == i
                assert actual['task'] == cfg['task_instruction']
                for key, expected in numeric_frame(f, i).items():
                    got = actual[key].numpy()
                    assert got.dtype == expected.dtype, (key,got.dtype,expected.dtype)
                    if got.shape == () and expected.shape == (1,):
                        assert tuple(schema[key]['shape']) == (1,), key
                        got = got.reshape(1)
                        scalar_normalizations[key] = scalar_normalizations.get(key,0)+1
                    assert got.shape == expected.shape, (key,got.shape,expected.shape)
                    errors[key] = max(errors.get(key, 0.), float(np.max(np.abs(got.astype(float)-expected.astype(float)))))
    assert all(v == 0 for v in errors.values())
    info = c.read(root/'meta/info.json')
    assert info['total_episodes'] == len(episodes) and info['total_frames'] == offset
    assert all('quality' not in key and 'success' not in key for key in info['features'])
    files = {str(p.relative_to(root)):c.sha(p) for p in root.rglob('*') if p.is_file()}
    binding = {'completed':True, 'episodes':episodes, 'rows':offset, 'fps':25, 'cameras':[],
               'task_instruction':cfg['task_instruction'], 'export_files':files,
               'quality_metadata_excluded_from_actor_features':True, 'images_present':False,
               'depth_present':False, 'production_accepted':False, 'task_learning_verified':False,
               'scope':'Complete numeric-only failed research tasks. Labels/provenance are outside the actor schema; no visual-data or learning qualification.'}
    c.write(root/'RESEARCH_BINDING.json', binding)
    report = {'passed':True, 'complete_audited_task_episodes':len(episodes), 'actual_public_reader_rows':offset,
              'source_physics_steps':sum(e['source_physics_steps'] for e in episodes),
              'numeric_max_errors':errors, 'public_singleton_scalar_normalization_counts':scalar_normalizations, 'copied_completed_export_verified_filewise':True, 'retained_original_export_attempt':str(old_root.parent), 'actual_reader':type(reader).__name__, 'dataset_root':str(root),
              'binding_sha256':c.sha(root/'RESEARCH_BINDING.json'), 'episodes':episodes,
              'all_episode_and_frame_indices_verified':True, 'future_quality_labels_excluded_from_actor':True,
              'task_instruction_contains_no_failure_or_outcome_label':True, 'images_present':False,
              'depth_present':False, 'production_accepted':False, 'training_updates':0,
              'new_physics_steps':0, 'new_render_passes':0}
    c.write(E/cfg['output'], report)
    finish(report)


if __name__ == '__main__':
    main(sys.argv[1])
