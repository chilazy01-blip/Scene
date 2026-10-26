"""Preserve scene text verbatim; keep motion quantities in a typed task field."""
from copy import deepcopy
from pathlib import Path
import math
from sage.experiments.embodied_scene_quality_v2.contracts import read,require,write_new,reference
from sage.experiments.embodied_task_scene_v1.semantic import prepare,validate_roles
from sage.experiments.codex_trellis_scene_v2.brief import build_baseline_brief
from sage.experiments.codex_trellis_scene_v2.furnishing_groups import ground_groups
from sage.experiments.codex_trellis_scene_v2.assets import resolve_assets


def separate(scene_description,task_spec):
    require(isinstance(scene_description,str) and bool(scene_description.strip()),'missing_scene_description')
    require(task_spec['kind']=='orientation_preserving_translation' and task_spec['translation_frame']=='support_local','unsupported_task_spec')
    offset=task_spec['goal_offset_xy_m'];require(len(offset)==2 and all(isinstance(x,(int,float)) and math.isfinite(x) for x in offset),'invalid_task_distance')
    require(task_spec['preserve_source_orientation'] is True,'orientation_contract')
    return dict(schema='separated-scene-task-request/v1',scene_description=scene_description,task_spec=deepcopy(task_spec))


def prepare_request(library,request,policy,contract):
    value=prepare(library,request,policy);separated=separate(contract['scene_description'],contract['task_spec'])
    value['prompt']=separated['scene_description'];value['separated_request']=separated
    brief=build_baseline_brief(value['prompt'],request['room_type']);ground_groups(brief,{},value['furnishing'])
    validate_roles(brief['objects'],value['roles'],value['expected_counts'])
    require(len(brief['objects'])==sum(value['expected_counts'].values()),'unexpected_object_count')
    value['brief']=brief;return value


def preview(config,brief,protocol):
    config=Path(config);output=config/'asset_preview';output.mkdir(exist_ok=False)
    report=resolve_assets(deepcopy(brief),output,mode='plan',manifest_path=config/'library.json',
        trellis_url='',seed=protocol['requests'][0]['seed'],timeout=1.,steps=1,texture_size=512,
        decimation_target=10000,pipeline_type='512',preprocess_image=False,max_new_assets=0,scene_dna_multiview=False)
    require(read(output/'asset_resolution.json')==report,'public_preview_artifact_mismatch')
    return finish_preview(config,brief,report)


def finish_preview(config,brief,report):
    config=Path(config);output=config/'asset_preview'
    require(read(output/'asset_resolution.json')==report,'public_preview_artifact_mismatch')
    passed=bool(report['component_resolution_ok'] and report['generated_count']==0 and report['missing_count']==0
        and len(report['results'])==len(brief['objects']) and all(r['status']=='reused' and r['dimension_resolution']['accepted'] for r in report['results']))
    result=dict(passed=passed,report=reference(output/'asset_resolution.json'),scene_prompt=reference(config/'prompt.txt'),library=reference(config/'library.json'),
        task_spec=reference(config/'separated_request.json'),objects=[{k:r[k] for k in ['object_id','category','asset_id','status','dimension_policy','dimension_resolution']} for r in report['results']],
        new_generation_attempts=0,new_visual_assets=0,new_physics_steps=0,
        scope='same public resolver in plan mode for every declared object; layout and architecture still require full generation')
    require(not list(output.rglob('*.glb')),'preview_wrote_mesh')
    write_new(config/'ASSET_PREVIEW.json',result);return result


def validate_config(config,protocol):
    config=Path(config);record=read(config/'separated_request.json');expected=separate(protocol['request_contract']['scene_description'],protocol['request_contract']['task_spec'])
    require(record==expected,'separated_request_mismatch')
    require((config/'prompt.txt').read_text()==record['scene_description'],'scene_text_changed')
    task=record['task_spec'];request=read(config/'request.json')
    require(task['goal_offset_xy_m']==protocol['translation']['goal_offset_support_xy_m'],'task_distance_changed')
    require(task['target_asset_id'] in request['target_pool'] and task['support_category']==request['support_category'],'task_asset_changed')
    require(read(config/'ASSET_PREVIEW.json')['passed'],'public_asset_preview_failed')
    return record


def compare_generation(config):
    config=Path(config);preview=read(config/'ASSET_PREVIEW.json');actual=read(config/'generator/asset_resolution.json')
    lookup={r['object_id']:r for r in actual['results']};rows=[]
    require(set(lookup)=={r['object_id'] for r in preview['objects']},'preview_generation_object_set')
    for row in preview['objects']:
        generated=lookup[row['object_id']]
        for k in ['category','asset_id','status','dimension_policy','dimension_resolution']:require(generated[k]==row[k],'preview_generation_mismatch:'+row['object_id']+':'+k)
        rows.append(dict(object_id=row['object_id'],asset_id=row['asset_id'],passed=True))
    result=dict(passed=True,objects=rows,actual_report=reference(config/'generator/asset_resolution.json'),preview=reference(config/'ASSET_PREVIEW.json'))
    write_new(config/'ASSET_PREVIEW_VERIFIED.json',result);return result
