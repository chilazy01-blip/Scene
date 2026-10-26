"""Register independently read complete research episodes with a fail-closed production view."""
import os,sys
from pathlib import Path
import numpy as np,h5py
from .work import E,P,c,finish


def main(config_path):
    cfg=c.read(config_path);work=Path(os.environ['CONTINUOUS_JOB_DIR'])
    sys.path.append(str(P.parent/'hmg_external_control_20261007/vendor'))
    cache=work/'hf_cache';cache.mkdir()
    os.environ.update(HF_HOME=str(cache),HF_DATASETS_CACHE=str(cache/'datasets'),HF_HUB_CACHE=str(cache/'hub'),HF_HUB_OFFLINE='1',HF_DATASETS_OFFLINE='1',TOKENIZERS_PARALLELISM='false')
    from sage.experiments.embodied_payload_data_v1.typed_reader import RGBDTrainingDataset
    episodes=[];offset=0;schemas=[];samples=[]
    for item in cfg['episodes']:
        root=Path(item['dataset_root']);binding=c.read(root/'BINDING.json');acceptance=c.read(item['acceptance_report'])
        assert acceptance['passed'] and acceptance['dataset_binding_sha256']==c.sha(root/'BINDING.json')
        assert acceptance['complete_episode_actual_public_reader_rows']==binding['rows']
        assert acceptance['read_ranges_contiguous_without_duplicates_or_gaps']
        assert binding['complete_physical_task_record'] and not binding['segment_truncated']
        assert not binding['production_accepted'] and not binding['source_task_success']
        assert not acceptance['task_learning_verified'] and acceptance['training_updates']==0
        meta=c.read(root/'meta/info.json');assert meta['total_episodes']==1 and meta['fps']==25
        schemas.append(meta['features']);reader=RGBDTrainingDataset(root)
        with h5py.File(root/'canonical.h5','r') as f:
            for i in [0,len(reader)-1]:
                row=reader[i];assert int(row['frame_index'])==i
                assert row['task']==binding['task_instruction']
                for camera in binding['cameras']:
                    rgb=np.rint(row['observation.images.'+camera].numpy().transpose(1,2,0)*255).astype('u1')
                    assert np.array_equal(rgb,f['cameras/'+camera+'/rgb'][i])
                    assert np.array_equal(row['observation.depth_m.'+camera].numpy(),f['cameras/'+camera+'/depth_m'][i])
                    assert np.array_equal(row['observation.depth_valid.'+camera].numpy(),f['cameras/'+camera+'/valid'][i])
                assert np.array_equal(row['action.valid'].numpy(),f['trajectory/action_valid'][i])
                samples.append({'episode_key':item['key'],'local_frame':i,'collection_frame':offset+i,'actual_reader_boundary_checked':True})
        actor_keys=sorted({k for k in meta['features'] if k.startswith('observation.')} |
                          {'observation.'+field+'.'+camera for camera in binding['cameras'] for field in ['depth_m','depth_valid']})
        assert all(not k.startswith('episode.') and 'quality' not in k for k in actor_keys)
        episodes.append({'key':item['key'],'dataset_relative_path':str(root.relative_to(E)),
                         'dataset_binding_sha256':c.sha(root/'BINDING.json'),'acceptance_sha256':c.sha(item['acceptance_report']),
                         'source_model_sha256':binding['source_model_sha256'],'source_trace_sha256':binding['source_trace_sha256'],
                         'rows':binding['rows'],'global_first_frame':offset,'global_stop_frame':offset+binding['rows'],
                         'source_duration_s':binding['temporal_sampling']['source_terminal_time_s'],
                         'source_task_success':False,'production_accepted':False,'split':'development_research_failure',
                         'actor_observation_feature_keys':actor_keys,'task_instruction':binding['task_instruction'],
                         'quality_sidecar_excluded_from_actor':binding['quality_sidecar_is_not_actor_input'],
                         'diagnostic_sites_visible':binding.get('diagnostic_sites_visible',True),
                         'clean_actor_visual_candidate':binding.get('diagnostic_sites_visible') is False})
        offset+=binding['rows']
    assert episodes and all(s==schemas[0] for s in schemas)
    assert len({r['key'] for r in episodes})==len(episodes)
    production=[r for r in episodes if r['production_accepted'] and r['source_task_success']]
    assert not production,'this registry contains failed research sources only'
    report={'passed':True,'registry_root':str(E),'episodes':episodes,'total_complete_research_episodes':len(episodes),
            'total_RGBD_frames':offset,'site_free_visual_episode_count':sum(not x['diagnostic_sites_visible'] for x in episodes),
            'visual_site_contamination_review_sha256':c.sha(cfg['visual_site_contamination_review']),'common_public_feature_schema':True,'unique_physical_model_count':len({r['source_model_sha256'] for r in episodes}),
            'unique_source_trajectory_count':len({r['source_trace_sha256'] for r in episodes}),
            'actual_reader_boundary_samples':samples,'production_view_episode_count':len(production),'production_view_keys':[],
            'training_updates':0,'task_learning_verified':False,'new_physics_steps':0,'new_render_passes':0,
            'scope':'Source-bound complete failed development episodes, suitable for data-engineering review. Same native scene across controllers is not generated-scene diversity. Legacy diagnostic-site imagery remains identified as visually unqualified. Production/default accepted-data view remains empty.'}
    c.write(E/cfg['output'],report);finish(report)


if __name__=='__main__':main(sys.argv[1])
