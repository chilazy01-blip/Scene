"""Scope hardening: exact task content and frozen controller inputs/sources.

V1 remains bound to the pilot proposal. V2 additionally prevents a changed target
or controller checkpoint from borrowing a success label under the same case ID.
"""
from pathlib import Path
from .common import read_bound_json, check, canonical
from .experience import retrieve as base_retrieve


def identity(protocol_binding, case_binding):
    check(protocol_binding);check(case_binding)
    p=read_bound_json(Path(protocol_binding['path']))
    assert p['case']['sha256']==case_binding['sha256']
    # Expert task/reference/runner packages intentionally vary per intervention.
    # The inherited native plant/control dependencies and inference inputs do not.
    sources={k:v['sha256'] for k,v in p['dependencies'].items()
             if not k.startswith(('expert_branch1_v1/','generated_grasp_v1/'))}
    return dict(case_sha256=case_binding['sha256'],controller_fingerprint=canonical(dict(
        inputs={k:v['sha256'] for k,v in p['inputs'].items()},base_sources=sources,
        solver_schedule=p['solver_schedule'])))


def retrieve(catalog,query,purpose='diagnosis'):
    result=base_retrieve(catalog,query,purpose)
    required=('case_sha256','controller_fingerprint')
    accepted=[]
    for record in result['matches']:
        matching=[]
        for evidence in record['matching_evidence']:
            report=read_bound_json(Path(evidence['report']['path']))
            actual=identity(report['protocol'],report['case'])
            if all(query.get(k)==actual[k] for k in required):matching.append(evidence)
        if matching:
            record['matching_evidence']=matching
            record['identity_verified']=True;accepted.append(record)
        else:
            result['rejected'].append(dict(id=record['id'],reasons=['exact_task_or_controller_identity_missing_or_changed']))
    result['matches']=accepted;result['schema']='scoped-retrieval/v2'
    return result
