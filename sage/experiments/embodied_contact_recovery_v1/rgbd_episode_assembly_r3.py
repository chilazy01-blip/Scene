"""Full source-model/renderer provenance on top of the validated shard assembly."""
import os
import sys
from pathlib import Path
from .work import c, finish
from . import rgbd_episode_assembly as assembly


def main(config_path):
    cfg = c.read(config_path)
    source = Path(cfg['source_episode'])
    model_path = source / 'MODEL.mjb'
    renderer_path = Path(__file__).with_name('rgbd_shards_r2.py')
    model_hash, renderer_hash = c.sha(model_path), c.sha(renderer_path)
    trace_hash = c.sha(source / 'TRACE.h5')
    lineage = []
    for name in cfg['shard_jobs']:
        folder = Path(name)
        request = c.read(folder / 'REQUEST.json')
        assert c.read(folder / 'SHARD_BINDING.json')['diagnostic_sites_visible'] is False
        assert request['inputs'][str(model_path)] == model_hash
        assert request['inputs'][str(renderer_path)] == renderer_hash
        assert request['inputs'][str(source / 'TRACE.h5')] == trace_hash
        assert 'LP_NUM_THREADS=4' in request['argv']
        lineage.append({'job': folder.name, 'request_sha256': c.sha(folder / 'REQUEST.json'),
                        'shard_binding_sha256': c.sha(folder / 'SHARD_BINDING.json')})
    audit_request = c.read(Path(cfg['source_audit_job']) / 'REQUEST.json')
    assert audit_request['inputs'][str(model_path)] == model_hash
    # Defer the final completed receipt until both the original independent
    # audit and the additional provenance checks have been written.
    assembly.finish = lambda report: None
    assembly.main(config_path)
    root = Path(os.environ['CONTINUOUS_JOB_DIR']) / 'assembled'
    binding = c.read(root / 'BINDING.json')
    binding.update(source_model_sha256=model_hash, renderer_source_sha256=renderer_hash,
                   source_scene_kind='native_development_not_generated_or_holdout',
                   render_job_lineage=lineage, render_CPU_profile='serial4CPU_LP_NUM_THREADS4',
                   source_model_matches_independent_physics_audit=True,
                   diagnostic_sites_visible=False, physical_geometry_and_render_quality_unchanged=True,
                   render_scene_option='All diagnostic site groups disabled; model geom groups,256x256,25Hz,2cameras,4samples and separate RGB/depth passes unchanged')
    c.write(root / 'BINDING.json', binding); finish(binding)


if __name__ == '__main__':
    main(sys.argv[1])
