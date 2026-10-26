"""Resolve category requirements to unique generated instances before assembly."""
from sage.experiments.embodied_scene_quality_v2.contracts import require
from sage.experiments.embodied_task_generation_v1.planner import select,generation_inputs
from sage.experiments.codex_trellis_scene_v2.brief import build_baseline_brief
from sage.experiments.codex_trellis_scene_v2.furnishing_groups import ground_groups


def validate_roles(objects,roles,expected_counts):
    ids=[o['id'] for o in objects];require(len(ids)==len(set(ids)),'duplicate_instance_id')
    for category,count in expected_counts.items():
        require(sum(o['category']==category for o in objects)==count,'category_count:'+category)
    lookup={o['id']:o for o in objects}
    require(roles['target_id'] in lookup and roles['support_id'] in lookup,'missing_role_instance')
    target,support=lookup[roles['target_id']],lookup[roles['support_id']]
    require(target['category']==roles['target_category'] and support['category']==roles['support_category'],'role_category')
    require(target.get('support_id')==support['id'],'support_edge')
    for o in objects:
        require(o.get('support_id') is None or o['support_id'] in lookup,'unresolved_support_edge')
    if 'asset_id' in target:
        require(target['asset_id']==roles['target_asset_id'] and support['asset_id']==roles['support_asset_id'],'role_asset_identity')
    return target,support


def prepare(library,request,policy):
    selection=select(library,request,policy)
    subset,config,prompt=generation_inputs(library,request,selection)
    brief=build_baseline_brief(prompt,request['room_type']);ground_groups(brief,{},config)
    link=config['attachments'][0]
    roles=dict(target_id=link['id'],support_id=link['parent_id'],target_category='single_book',support_category=request['support_category'],
        target_asset_id=selection['selected']['asset_id'],support_asset_id=selection['support_asset_id'])
    counts={c:1 for c in ['single_book','desk','office_chair','bookcase','floor_lamp',request['support_category']]}
    validate_roles(brief['objects'],roles,counts)
    require(len(brief['objects'])==sum(counts.values()),'unexpected_scene_object')
    return dict(selection=selection,library=subset,furnishing=config,prompt=prompt,roles=roles,expected_counts=counts)
