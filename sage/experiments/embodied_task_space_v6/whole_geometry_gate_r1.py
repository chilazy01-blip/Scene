"""Read-only bridge from the full matrix to later native coverage.

This validates sealed whole-path audit evidence. It cannot grant physical
admission, run a policy, seal evidence, or extend a resource authorization.
"""
from pathlib import Path
import hashlib,json

CASES=('nominal','xminus','xplus','yminus','yplus','yawminus','yawplus','body_low','body_high','tracking_min','tracking_max')
STAGES=('settle','clear_arms','approach','stop_source','lower_source','reach','close','rise_lift','carry','stop_target','lower_place','release','retract','rise_empty','settle_final')
class GeometryNotAdmitted(RuntimeError):pass

def require(value,reason):
    if not value:raise GeometryNotAdmitted(reason)

def read(path):
    try:return json.loads(Path(path).read_text())
    except (OSError,ValueError) as exc:raise GeometryNotAdmitted('missing_or_invalid:'+str(path)) from exc

def digest(path):
    h=hashlib.sha256()
    try:
        with Path(path).open('rb') as f:
            for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    except OSError as exc:raise GeometryNotAdmitted('missing_bound_file:'+str(path)) from exc
    return h.hexdigest()

def validate(root,execution,manifest='GEOMETRY_BINDING.json'):
    root=Path(root).resolve();freeze=root/manifest;binding=read(freeze);files=binding.get('files',{})
    require(binding.get('scope')=='complete_local_geometry_and_audits' and isinstance(files,dict) and files,'geometry_binding_required')
    for name,h in files.items():require(Path(name).is_absolute() and digest(name)==h,'geometry_bound_bytes_changed:'+name)
    def bound(path):
        path=Path(path).resolve();require(str(path) in files,'geometry_file_not_bound:'+str(path));return read(path)
    summary=bound(root/'geometry/RESULT.json')
    require(summary.get('passed') is True and summary.get('status')=='all_geometry_and_audits_passed','matrix_not_passed')
    require(summary.get('nonpass_cases')==0 and summary.get('unrun_cases')==[],'matrix_incomplete')
    require([r.get('case') for r in summary.get('cases',[])]==list(CASES),'case_denominator_or_order')
    selected=[]
    for case,row in zip(CASES,summary['cases']):
        folder=root/'geometry/cases'/case
        require(row.get('geometry_passed') is True and row.get('independent_audit_passed') is True,'case_not_passed:'+case)
        require(Path(row['result']).resolve()==folder/'RESULT.json' and Path(row['audit']).resolve()==folder/'AUDIT.json','case_source_redirected:'+case)
        result=bound(folder/'RESULT.json');audit=bound(folder/'AUDIT.json');choice=bound(folder/'SELECTED.json');path=Path(choice['path']).resolve()
        require(path.is_relative_to(folder/'paths') and path.name=='PATH.pathz','whole_case_path_required:'+case)
        require(choice.get('whole_path') is True and files.get(str(path))==choice.get('sha256'),'selected_path_not_bound:'+case)
        require(result.get('passed') is True and audit.get('passed') is True and audit.get('selected_verified') is True,'selected_audit_not_passed:'+case)
        require(result.get('execution_admission')==execution and audit.get('execution_admission')==execution,'execution_identity_changed:'+case)
        require(audit.get('independent_refinement_and_anchor_verified') is True and audit.get('physics_steps')==0 and audit.get('policy_forwards')==0,'independent_static_audit_required:'+case)
        reports=[r for r in audit.get('paths',[]) if r.get('path')==str(path)]
        require(len(reports)==1 and reports[0].get('sha256')==choice['sha256'] and reports[0].get('claimed_pass') is True,'selected_whole_report_missing:'+case)
        phases=reports[0].get('phases',[])
        require([r.get('stage') for r in phases]==list(STAGES) and all(r.get('passed') is True and r.get('current_bad')==0 and r.get('stop_bad')==0 for r in phases),'phase_identity_or_contact_failure:'+case)
        require(sum(r['states'] for r in phases)==7450 and audit.get('saved_states',0)>=7450,'complete_reference_clock_required:'+case)
        # Include every evaluated candidate, source, hard row and certificate;
        # the selected output alone cannot replace the independent audit input.
        for file in folder.rglob('*'):
            if file.is_file():require(str(file.resolve()) in files,'unsealed_case_evidence:'+str(file))
        selected.append(dict(case=case,path=str(path),sha256=choice['sha256'],states=7450))
    return dict(passed=True,cases=selected,reference_states=81950,geometry_binding_sha256=digest(freeze),physics_admitted=False,full_task_admitted=False)
