"""Seal contiguous actual public-reader coverage of one immutable RGB-D episode."""
import sys
from pathlib import Path
from .work import E, c, finish


def main(config_path):
    cfg = c.read(config_path); root = Path(cfg['dataset_root'])
    binding = c.read(root / 'BINDING.json'); digest = c.sha(root / 'BINDING.json')
    assert binding['complete_physical_task_record'] and not binding['segment_truncated']
    assert binding['physical_source_independent_reintegration']
    assert binding['canonical_independent_audit_passed']
    assert not binding['production_accepted'] and not binding['source_task_success']
    cursor = 0; reports = []; errors = {}
    for path in cfg['read_jobs']:
        folder = Path(path); result = c.read(folder / 'DATASET_READ_REPORT.json')
        assert result['passed'] and result['dataset'] == str(root)
        assert result['dataset_binding_sha256'] == digest
        assert result['first_row'] == cursor and result['stop_row'] > cursor
        assert result['complete_episode_rows'] == binding['rows']
        assert result['actual_public_RGBD_consumer_rows'] == result['stop_row'] - cursor
        assert result['task_instruction_checked_on_every_row'] == binding['task_instruction']
        assert not result['episode_task_success'] and not result['episode_segment_truncated']
        assert result['portable_relative_virtual_sources_read']
        assert c.read(folder / 'REQUEST.json')['inputs'][str(root / 'BINDING.json')] == digest
        for key, value in result['maximum_field_errors'].items():
            errors[key] = max(errors.get(key, 0.), value)
        cursor = result['stop_row']
        reports.append({'job': folder.name, 'first_row': result['first_row'], 'stop_row': cursor,
                        'report_sha256': c.sha(folder / 'DATASET_READ_REPORT.json'),
                        'request_sha256': c.sha(folder / 'REQUEST.json')})
    assert cursor == binding['rows'] and all(value == 0. for value in errors.values())
    for name, value in binding['export_files'].items():
        assert c.sha(root / name) == value, name
    meta = c.read(root / 'meta/info.json')
    assert meta['total_episodes'] == 1 and meta['total_frames'] == cursor and meta['fps'] == 25
    result = {'passed': True, 'dataset': str(root), 'dataset_binding_sha256': digest,
              'complete_episode_actual_public_reader_rows': cursor,
              'read_ranges_contiguous_without_duplicates_or_gaps': True,
              'read_reports': reports, 'maximum_field_errors': errors,
              'export_files_hashes_unchanged': True, 'one_episode_preserved': True,
              'full_source_reintegration_and_policy_recompute_passed': True,
              'complete25Hz_two_camera_256x256_RGBD': True,
              'all400Hz_source_substeps_preserved_separately': True,
              'source_task_success': False, 'source_task_failed_physical_quality': True,
              'production_accepted': False, 'task_learning_verified': False,
              'training_updates': 0, 'physics_steps': 0, 'render_passes': 0,
              'scope': 'Complete failed research episode, independent physical rerun, source/camera/depth audit, actual public reader on every frame. No successful task or learning claim.'}
    c.write(E / cfg['output'], result); finish(result)


if __name__ == '__main__': main(sys.argv[1])
