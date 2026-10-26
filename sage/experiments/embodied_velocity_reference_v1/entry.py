"""Bind a new controller trial to unchanged, previously verified scene evidence."""
from pathlib import Path
from sage.experiments.embodied_scene_quality_v2.contracts import read,read_ref,bound,reference,require,write_new
from sage.experiments.embodied_translation_task_v2.entry import load as source_load


def create_binding(protocol_path,path):
    protocol_path=Path(protocol_path);p=read(protocol_path)
    value=dict(schema='velocity-reference-binding/v1',request_id=p['request_id'],protocol=reference(protocol_path),
        source_binding=p['source_binding'],implementation={str(f):reference(f) for f in sorted(Path(__file__).parent.glob('*.py'))},
        qualification='single_controller_development_trial',qualified_collection=False,qualified_export=False)
    write_new(path,value);return value


def load(path,pin,purpose,request_id):
    require(purpose in ['inspection','controller_evaluation'],'unsupported_purpose:'+purpose)
    record=read(bound(path,pin));require(record['schema']=='velocity-reference-binding/v1','binding_schema')
    require(record['qualification']=='single_controller_development_trial' and not record['qualified_collection'] and not record['qualified_export'],'production_scope_changed')
    p=read_ref(record['protocol']);require(request_id==record['request_id']==p['request_id'],'request_identity')
    for ref in record['implementation'].values():bound(ref['path'],ref['sha256'])
    require(record['source_binding']==p['source_binding'],'source_binding_changed')
    source_protocol=read_ref(p['source_protocol']);source=read_ref(record['source_binding'])
    require(source['config']==p['source_config'] and source['request']['id']==p['source_request_id'],'source_identity')
    for key in ['execution','robot','selection','translation']:require(p[key]==source_protocol[key],'inherited_condition_changed:'+key)
    for key in ['baseline_episode','baseline_raw','physical_model','fixed_plan','task']:bound(p[key]['path'],p[key]['sha256'])
    bound(p['controller']['source']['path'],p['controller']['source']['sha256'])
    require(p['controller']['kp']==[400,400,400,400,200,100,80] and p['controller']['kd']==[45,45,45,45,25,15,12],'controller_gains_changed')
    require(p['controller']['formula']=='kp*(q_ref-q)+kd*(qdot_ref-qdot)+qfrc_bias' and p['controller']['velocity_units']=='rad/s','controller_contract_changed')
    require(p['physical_model']['path']==str(Path(p['source_config'])/'package/robot_mounted.xml'),'model_identity')
    require(read_ref(p['fixed_plan'])['passed'],'source_plan_failed')
    model,score=source_load(record['source_binding']['path'],record['source_binding']['sha256'],'robot_execution',p['source_request_id'])
    require(score['ready_for_execution'],'source_prerequisites_failed')
    return model,dict(controller_evaluation_admitted=True,source_request=p['source_request_id'],source_prerequisites=score,
        task_success_not_inferred=True,qualified_collection=False,qualified_export=False)
