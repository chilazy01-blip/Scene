"""Append only independently reviewed pilot evidence; never deploy on retrieval."""
import copy
from pathlib import Path
from sage.experiments.embodied_expert_branch1_v1.common import ROOT,read_bound_json,safe_save,_file_binding
from sage.experiments.embodied_expert_branch1_v1.promotion import assess
from sage.experiments.embodied_expert_branch1_v1.experience_v2 import retrieve
parent=ROOT/'workbench/context/EXPERIENCE_CANDIDATES.json';catalog=read_bound_json(parent);catalog.pop('content_sha256_excluding_this_field',None)
catalog['parent_implementation']=catalog.pop('implementation');catalog['implementation']=_file_binding(Path(__file__));catalog['parent_catalog']=_file_binding(parent)
scope0=next(r['applicability'] for r in catalog['records'] if r['id']=='bottle_acquired_preload_during_probe_and_hover')
for t in sorted((ROOT/'trials').iterdir()):
 name=t.name;case=read_bound_json(t/'CASE.json')
 if case['object_id']!='bottle':continue
 r=read_bound_json(t/'full/REPORT.json');v=read_bound_json(t/'FINAL_VERIFICATION.json')
 gate=assess([t/'FINAL_VERIFICATION.json'],[case['case_id']]);scope=copy.deepcopy(scope0);scope['tested_layout']=case['scene_id']
 evidence=dict(case_id=case['case_id'],physical_model=r['model'],report=_file_binding(t/'full/REPORT.json'),measurements=_file_binding(t/'MEASUREMENTS.json'),verification=_file_binding(t/'FINAL_VERIFICATION.json'),strategy=_file_binding(t/'strategy.py'),task_passed=r['task_passed'],stop_reason=r['stop_reason'],source_role='development_validation',dataset_split='unassigned')
 complete=gate['eligible']
 record=dict(id='branch1_'+name,status='project_validated_in_listed_development_cases' if complete else 'independently_reviewed_partial_failure',applicability=scope,evidence=[evidence],automatic_deployment_approved=False,
   allowed_usage='Scoped verified strategy reference; revalidate changed assets/task/controller. No automatic deployment.' if complete else 'Diagnosis and phase planning only; never a qualified complete skill.',
   failure_signature=r['stop_reason'],repair_intent='Fixed acquired hover preload across airborne phases and separate release-entry quietness from persistent measured support/geometry.' if case['scene_id']=='S02' else 'Acquire and retain actual native contacts before probe; release-only repairs cannot solve this observed close failure.',
   scope_limit='Only this exact assumed200g empty-bottle model, upper neck/cap and case/controller identity; no cross-layout/object/generalization proof.',
   independent_promotion_result=gate,phase_feedback=_file_binding(t/'PHASE_FEEDBACK_V3.json'),spatial_feedback=_file_binding(t/'SPATIAL_FEEDBACK.json'))
 catalog['records'].append(record)
catalog.update(schema='branch1-scoped-experience-catalog/v2',implemented_skill_retrieval=True,implemented_independent_promotion_gate=True,implemented_automatic_promotion=False,new_physics_steps=0)
out=ROOT/'EXPERIENCE_CATALOG_V2.json';assert not out.exists();safe_save(out,catalog)
checks={}
for case in ['S02_bottle','S03_bottle']:
 q=read_bound_json(ROOT/f'{case}_IDENTITY_RETRIEVAL_V2.json')['query'];diagnosis=retrieve(catalog,q,'diagnosis');skills=retrieve(catalog,q,'complete_skill')
 safe_save(ROOT/f'{case}_FINAL_DIAGNOSIS_RETRIEVAL.json',diagnosis);safe_save(ROOT/f'{case}_FINAL_COMPLETE_SKILL_RETRIEVAL.json',skills)
 checks[case]=dict(diagnosis_ids=[r['id'] for r in diagnosis['matches']],complete_skill_ids=[r['id'] for r in skills['matches']])
assert not checks['S03_bottle']['complete_skill_ids']
safe_save(ROOT/'EXPERIENCE_UPDATE_CHECK.json',dict(passed=True,catalog=_file_binding(out),cases=checks,new_physics_steps=0,automatic_deployment_approved=False))
print(checks)
