from pathlib import Path
import numpy as np
from sage.experiments.embodied_scene_quality_v2.contracts import read,read_ref,bound,require,reference,write_new
from sage.experiments.embodied_temporal_dataset_v1.dataset import EpisodeDataset
from sage.experiments.embodied_velocity_reference_v1.entry import load as model_load
from .executor import validate_contract


def create_binding(protocol_path,path):
    p=read(protocol_path)
    value=dict(schema='data-block-consumer-binding/v1',request_id=p['request_id'],protocol=reference(protocol_path),dataset_binding=p['dataset_binding'],
        implementation={str(f):reference(f) for f in sorted(Path(__file__).parent.glob('*.py'))},
        scope='single_development_consumer_regression',qualified_collection=False,qualified_export=False)
    write_new(path,value);return value


def load(path,pin,purpose,request_id):
    require(purpose in ['inspection','consumer_evaluation'],'unsupported_purpose:'+purpose)
    b=read(bound(path,pin));require(b['schema']=='data-block-consumer-binding/v1','binding_schema')
    require(b['scope']=='single_development_consumer_regression' and not b['qualified_collection'] and not b['qualified_export'],'scope_changed')
    p=read_ref(b['protocol']);require(request_id==b['request_id']==p['request_id'],'request_identity');validate_contract(p['action_contract'])
    require(p['comparison']['atol']==1e-12 and p['comparison']['time_atol_s']==1e-9,'comparison_changed')
    require(p['budget']['max_blocks']==350 and p['budget']['max_physics_steps']==17500 and p['budget']['max_new_physical_attempts']==1 and p['budget']['max_replays']==0,'execution_budget_changed')
    for ref in b['implementation'].values():bound(ref['path'],ref['sha256'])
    require(b['dataset_binding']==p['dataset_binding'],'dataset_binding_changed')
    for key in ['dataset_protocol','dataset_result','dataset_seal','dataset_prepared','dataset_file','source_controller_binding','source_controller_protocol','reference_episode','reference_raw','physical_model','task']:
        ref=p[key];bound(ref['path'],ref['sha256'])
    dp=read_ref(p['dataset_protocol']);db=read_ref(p['dataset_binding']);dr=read_ref(p['dataset_result']);seal=read_ref(p['dataset_seal'])
    require(dr['development_dataset_qualified'] and dr['data_contract_passed'] and dr['reader_roundtrip_passed'] and seal['seal_passed'] and seal['all_services_stopped_mainpid_zero'],'dataset_not_qualified')
    require(db['protocol']==p['dataset_protocol'] and db['hdf5']==p['dataset_file'] and db['prepared']==p['dataset_prepared'],'dataset_identity')
    require(dp['source_controller_protocol']==p['source_controller_protocol'] and dp['source_binding']==p['source_controller_binding'] and dp['source_raw']==p['reference_raw'] and dp['source_episode']==p['reference_episode'] and dp['physical_model']==p['physical_model'] and dp['task']==p['task'],'reference_identity')
    vp=read_ref(p['source_controller_protocol']);require(vp['controller']==p['controller'] and vp['execution']['replay_atol']==p['comparison']['atol'],'controller_or_threshold_changed')
    require(p['scope']['split']=='development' and p['scope']['independent_validation_combinations']==0 and not p['scope']['production_qualified'],'protocol_scope_changed')
    dataset=EpisodeDataset(p['dataset_binding']['path'],p['dataset_binding']['sha256'],'development_dataset','O01')
    model,source=model_load(p['source_controller_binding']['path'],p['source_controller_binding']['sha256'],'controller_evaluation','V01')
    return model,dataset,dict(consumer_evaluation_admitted=True,development_only=True,dataset_verification=dataset.verification,
        source_controller_admission=source,execution_success_not_inferred=True,qualified_collection=False,qualified_export=False)
