"""Deterministic scoped retrieval and independent-evidence promotion gates.

Retrieval is advisory. No memory record can directly deploy strategy code.
"""
from pathlib import Path
from .common import read_bound_json, check, _file_binding, safe_save

COMMON=('robot','body_control','hand_control','loaded_reference_ratio','solver_schedule','object_asset')


def retrieve(catalog, query, purpose='diagnosis'):
    if purpose not in ('diagnosis','complete_skill'): raise ValueError('invalid purpose')
    accepted=[];rejected=[]
    for record in catalog['records']:
        scope=record['applicability'];why=[]
        for key in COMMON:
            if key not in query or query[key]!=scope.get(key):why.append('scope:'+key)
        for key in ('mass_assumption_kg','grasp_region','initial_pose','left_hand_object_contact_allowed'):
            if key in scope and query.get(key)!=scope[key]:why.append('scope:'+key)
        evidence=record.get('evidence',[])
        matching=[e for e in evidence if e['physical_model']['sha256']==query.get('model_sha256') and e['case_id']==query.get('case_id')]
        if not matching:why.append('exact_model_and_case_not_in_evidence')
        qualified=[e for e in matching if e.get('task_passed')]
        if purpose=='complete_skill' and (not qualified or record['status']!='project_validated_in_listed_development_cases'):
            why.append('not_independently_complete_skill')
        if why:
            rejected.append(dict(id=record['id'],reasons=why));continue
        # Fail closed on stale physical/source/evidence bindings.
        for e in matching:
            for key in ('physical_model','report','measurements','verification','strategy'):check(e[key])
        if record.get('proposed_code'):check(record['proposed_code'])
        if record.get('time_order_diagnosis'):check(record['time_order_diagnosis'])
        accepted.append(dict(id=record['id'],status=record['status'],purpose=purpose,
            repair_intent=record.get('repair_intent'),failure_signature=record.get('failure_signature'),
            allowed_usage=record['allowed_usage'],automatic_deployment_approved=False,
            matching_evidence=matching,proposed_code=record.get('proposed_code'),
            scope_limit=record.get('scope_limit'),hypothesis_requires_actual_trial=record['status']=='untested_hypothesis'))
    return dict(schema='scoped-retrieval/v1',query=query,purpose=purpose,matches=accepted,rejected=rejected,
                automatic_deployment_approved=False,new_physics_steps=0)


def promotion_gate(verifications, required_cases):
    """Require current independently bound verification for every declared case."""
    reasons=[];seen=set();strategies=set()
    for v in verifications:
        for key in ('report','strategy','protocol','audit','force','replay'):
            if key not in v:reasons.append('missing_binding:'+key)
            else:check(v[key])
        case=v.get('case_id');seen.add(case)
        if v.get('strategy'):strategies.add(v['strategy']['sha256'])
        if not v.get('independently_qualified'):reasons.append('not_qualified:'+str(case))
        if not v.get('full_video_decoded') or not v.get('main_agent_visual_reviewed'):reasons.append('missing_visual_review:'+str(case))
        if v.get('numerical_warning_count')!=0:reasons.append('numerical_warning:'+str(case))
        if v.get('dataset_split')!='unassigned' or v.get('source_role')!='development_validation':reasons.append('wrong_development_scope:'+str(case))
    if set(required_cases)!=seen:reasons.append('required_cases_incomplete')
    if len(strategies)!=1:reasons.append('not_one_frozen_strategy')
    if not required_cases:reasons.append('empty_scope')
    return dict(eligible=not reasons,reasons=reasons,automatic_deployment_approved=False,
                qualified_scope=sorted(seen-{None}) if not reasons else [],
                no_generalization_or_learning_claim=True)
