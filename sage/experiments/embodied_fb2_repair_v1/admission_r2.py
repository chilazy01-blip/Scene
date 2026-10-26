"""Explicit evidence gate between repair diagnostics and the FB2 task."""
from pathlib import Path
import hashlib,json


REQUIRED_BEFORE_FULL_TASK={
    'initialization_cache','native_actuator_equations','task_target_contract',
    'positive_clearance','native_contact_query_consistency','physical_limit_consumption','fixed_control_timing',
    'station_keeping_and_stopping','integrated_grasp_component','residual_friction_stop',
}


def require_full_task(recheck_path):
    path=Path(recheck_path);r=json.loads(path.read_text())
    issues={v['id']:v for v in r['findings']}
    unresolved=[key for key in sorted(REQUIRED_BEFORE_FULL_TASK)
                if key not in issues or issues[key]['status']!='validated']
    if unresolved:raise RuntimeError('unresolved_repair_findings:'+','.join(unresolved))
    for key in sorted(REQUIRED_BEFORE_FULL_TASK):
        records=issues[key].get('evidence',[])
        if not records:raise RuntimeError('missing_repair_evidence:'+key)
        for item in records:
            p=Path(item['path'])
            if hashlib.sha256(p.read_bytes()).hexdigest()!=item['sha256']:
                raise RuntimeError('repair_evidence_changed:'+str(p))
    component=issues['integrated_grasp_component']
    result=json.loads(Path(component['result_path']).read_text())
    audit=json.loads(Path(component['audit_path']).read_text())
    if result.get('mode')!='component' or result.get('passed') is not True:
        raise RuntimeError('complete_grasp_component_required')
    if audit.get('passed') is not True or audit.get('component_passed') is not True:
        raise RuntimeError('independent_grasp_component_audit_required')
    if audit.get('governor_audit_passed') is not True:
        raise RuntimeError('independent_stop_trim_governor_audit_required')
    if audit['input_sha256']!=hashlib.sha256((Path(component['result_path']).parent/'TRACE.npz').read_bytes()).hexdigest():
        raise RuntimeError('component_trace_changed')
    return dict(admitted=True,recheck_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
