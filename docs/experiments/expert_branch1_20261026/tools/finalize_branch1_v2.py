"""Reconcile exact native cost, independent qualification and cross-round dedup."""
from pathlib import Path
import ast,hashlib,json,time
import numpy as np
from sage.experiments.embodied_expert_branch1_v1.common import ROOT,read_bound_json,safe_save,_file_binding,check
R=ROOT

def digest(path):
 h=hashlib.sha256()
 with np.load(path,allow_pickle=False) as arrays:
  for key in ('ctrl','qpos_after','qvel_after'):
   x=np.ascontiguousarray(arrays[key]);h.update(key.encode());h.update(str(x.shape).encode());h.update(x.dtype.str.encode());h.update(x.tobytes())
 return h.hexdigest()

def run():
 assert (R/'EXPERIENCE_UPDATE_CHECK.json').exists()
 auth=read_bound_json(R/'AUTHORIZATION.json');cost=read_bound_json(R/'COST.json');settled=[]
 for x in cost['reservations']:
  path=Path(x['output'])/'REPORT.json';assert path.exists(),x
  n=read_bound_json(path)['physics_steps'];assert 0<=n<=x['maximum_steps']
  settled.append(dict(reservation=x,actual_native_steps=n,report=_file_binding(path)))
 new_steps=sum(x['actual_native_steps'] for x in settled);assert new_steps<=120000
 old=read_bound_json(R.parent/'embodied_generated_grasp_execution_20261026_v1/DATASET_MANIFEST.json')
 old_hashes={x['content_sha256'] for x in old['episodes']};all_positive=[];new_unique=[];regressions=[];trials=[];assessed=set()
 for t in sorted((R/'trials').iterdir()):
  job=read_bound_json(t/'JOB.json');assert job['status']=='complete'
  p=read_bound_json(t/'PROTOCOL.json');r=read_bound_json(t/'full/REPORT.json');v=read_bound_json(t/'FINAL_VERIFICATION.json');c=read_bound_json(t/'CASE.json');m=read_bound_json(t/'MEASUREMENTS.json')
  assert v['complete'] and (t/'FEEDBACK_STATE_ORDER_CHECK.json').exists() and (t/'SPATIAL_FEEDBACK.json').exists()
  for b in [p['authorization'],p['plan'],p['case'],p['candidate'],p['scene'],p['reference'],*p['inputs'].values(),*p['dependencies'].values(),*p['branch_one_evidence'].values()]:check(b)
  assert r['new_physics_steps']==r['physics_steps']==read_bound_json(t/'cost/REPORT.json')['physics_steps']==read_bound_json(t/'NATIVE_CALL_COUNT.json')['native_integrator_calls']
  assert p['prior_native_steps']==239138 and p['max_new_physics_steps']==120000 and p['deadline_epoch_utc']==auth['deadline_epoch_utc']
  assessed.add(c['case_id']);item=dict(trial=t.name,case_id=c['case_id'],object_id=c['object_id'],physics_steps=r['physics_steps'],qualified=v['positive'],stop_reason=r['stop_reason'],goal_error_m=r['goal_error_m'],object_orientation_cosine=m['object_orientation_cosine'],max_held_slip_m=r['max_held_slip_m'],strategy=p['candidate'],report=_file_binding(t/'full/REPORT.json'),verification=_file_binding(t/'FINAL_VERIFICATION.json'),phase_feedback=_file_binding(t/'PHASE_FEEDBACK_V3.json'),spatial_feedback=_file_binding(t/'SPATIAL_FEEDBACK.json'))
  trials.append(item)
  if v['positive']:
   path=next(t/('delivery_'+v+'/episode.npz') for v in ('v6','v5','v4') if (t/('delivery_'+v+'/episode.npz')).exists());h=digest(path);scene=read_bound_json(Path(p['scene']['path']))
   record=dict(item,content_sha256=h,episode=_file_binding(path),video=_file_binding(t/'actual_video_v3/motion.mp4'),model=r['model'],case=_file_binding(t/'CASE.json'),scene=p['scene'],generated_scene_sources=scene['sources'],asset_lineage_group_id=c['asset_lineage_group_id'],layout_source_group_id=c['layout_source_group_id'],source_role='development_validation',dataset_split='unassigned',leakage_group_id='generated_grasp_development_shared_assets_and_reference_templates')
   all_positive.append(record)
   if h in old_hashes:regressions.append(record)
   elif h not in {x['content_sha256'] for x in new_unique}:new_unique.append(record)
 assert assessed==set(read_bound_json(R/'PLAN.json')['cases'])
 source_checks={}
 for name,b in json.loads((R/'FORK_PROVENANCE.json').read_text()).items():source_checks[name]=_file_binding(Path(b['path']))['sha256']==b['sha256']
 assert all(source_checks.values())
 module_checks={}
 for p in Path('/data/wsj/main/scene/sage/experiments/embodied_expert_branch1_v1').rglob('*.py'):ast.parse(p.read_text());module_checks[str(p)]=_file_binding(p)
 safe_save(R/'COST_FINAL_SNAPSHOT.json',cost)
 safe_save(R/'OLD_SOURCE_PROTECTION_CHECK_FINAL.json',dict(passed=True,checks=source_checks,new_physics_steps=0))
 safe_save(R/'DATASET_MANIFEST.json',dict(schema='branch1-development-dataset/v1',episodes=new_unique,qualified_regression_archive=regressions,all_qualified_archive=all_positive,total_qualified_this_round=len(all_positive),new_unique_physical_trajectories=len(new_unique),new_physics_steps=new_steps,data_schema=_file_binding(R/'ROBOT_DATA_SCHEMA.json'),source_role='development_validation',dataset_split='unassigned',diversity_limit='Reused S02/S03 generated layouts and frozen assets/workcell templates; new bottle success is scoped to its verified case, not broad generalization.',leakage_policy='Keep shared assets/reference groups together; none are heldout evaluation or assigned training/test splits.',implementation=_file_binding(Path(__file__))))
 safe_save(R/'FINAL_REVIEW.json',dict(schema='expert-branch1-final-review/v1',round_complete=True,all_required_independent_reviews_complete=True,initial_matrix_cases_assessed=sorted(assessed),followup_scope='S02 release-entry/support semantics, bounded finger-opening pause and measured-wrench bounded wrist reference reseating; no completed bottle release',all_cases_successful=all(x['qualified'] for x in trials),trials=trials,qualified_current_episodes=len(all_positive),new_unique_qualified_episodes=len(new_unique),qualified_duplicate_regressions=len(regressions),prior_native_steps=239138,new_native_physics_steps=new_steps,cumulative_native_physics_steps=239138+new_steps,max_new_native_physics_steps=120000,reservations=settled,all_reservations_settled=True,new_native_steps_per_new_unique_episode=new_steps/len(new_unique) if new_unique else None,exit='Original latest-start cutoff (at least 60min independent QA headroom before 03:40:31 CST) reached following V004 launch; no additional raw trials admitted. Preserve unresolved S02 release and S03 acquisition as reviewed negatives.',finished_epoch_utc=time.time(),deadline_epoch_utc=auth['deadline_epoch_utc'],training_performed=False,heldout_evaluation_performed=False,generalization_proven=False,model_weights_self_evolved=False,actual_expert_calls=[_file_binding(p) for p in sorted(R.glob('expert_*/INVOCATION.json'))],experience_update=_file_binding(R/'EXPERIENCE_UPDATE_CHECK.json'),manifest=_file_binding(R/'DATASET_MANIFEST.json'),official_phase_feedback='v3/model-derived hand addresses/right wrist frame',new_modules=module_checks,implementation=_file_binding(Path(__file__))))
 print(dict(round_complete=True,new_native_steps=new_steps,cumulative=239138+new_steps,new_unique=len(new_unique),qualified_duplicates=len(regressions)))
if __name__=='__main__':run()
