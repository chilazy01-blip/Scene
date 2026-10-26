"""Check authoritative final bindings, retained source and archive readiness; no integration."""
from pathlib import Path
import ast,hashlib,json,time
B=Path(__file__).resolve().parents[1];repo=Path('/data/wsj/main/scene');cache={};checked={};failures=[]
def sha(p):
 p=Path(p);st=p.stat();key=(str(p),st.st_size,st.st_mtime_ns)
 if key not in cache:
  h=hashlib.sha256()
  with p.open('rb') as f:
   for part in iter(lambda:f.read(4*1024*1024),b''):h.update(part)
  cache[key]=h.hexdigest()
 return cache[key]
def walk(d,origin):
 if isinstance(d,dict):
  if isinstance(d.get('path'),str) and isinstance(d.get('sha256'),str):
   p=Path(d['path'])
   try:
    actual=sha(p);assert actual==d['sha256'];assert 'size_bytes' not in d or p.stat().st_size==d['size_bytes']
    checked[str(p)]=actual
   except Exception as e:failures.append(dict(origin=origin,path=str(p),error=repr(e)))
  for v in d.values():walk(v,origin)
 elif isinstance(d,list):
  for v in d:walk(v,origin)
roots=['FINAL_REVIEW.json','DATASET_MANIFEST.json','COST_FINAL_SNAPSHOT.json','EXPERIENCE_CATALOG_V2.json','EXPERIENCE_UPDATE_CHECK.json','EXPERT_ALL_CALLS_REVIEW.json','CHECKPOINT_BOUND_EVIDENCE_PROTECTION.json','OLD_SOURCE_PROTECTION_CHECK_FINAL.json','SESSION_CLOSEOUT.json','TEST_PREFLIGHT_RESULT.json','PROPOSAL_POINTER_RECONCILIATION.json','CUP_REGRESSION_COMPARISON.json']
for t in sorted((B/'trials').iterdir()):
 for n in ['FINAL_VERIFICATION.json','PHASE_FEEDBACK_V3.json','SPATIAL_FEEDBACK.json','PROTOCOL.json','FEEDBACK_STATE_ORDER_CHECK.json']:
  p=t/n;walk(json.loads(p.read_text()),str(p))
for n in roots:walk(json.loads((B/n).read_text()),n)
modules={}
for p in (repo/'sage/experiments/embodied_expert_branch1_v1').rglob('*.py'):
 ast.parse(p.read_text());modules[str(p)]=sha(p)
strategy_checks={}
for p in (repo/'sage/experiments/embodied_expert_branch1_v1/strategies').glob('bottle_branch1_v*.py'):
 q=B/'workbench/strategies'/p.name;strategy_checks[p.name]=sha(p)==sha(q)
assert len(strategy_checks)==4 and all(strategy_checks.values())
f=json.loads((B/'FINAL_REVIEW.json').read_text());assert f['new_native_physics_steps']==55548 and f['cumulative_native_physics_steps']==294686
assert f['new_unique_qualified_episodes']==0 and f['qualified_duplicate_regressions']==1 and f['all_reservations_settled']
assert all(json.loads((t/'JOB.json').read_text())['status']=='complete' for t in (B/'trials').iterdir())
assert json.loads((B/'SESSION_CLOSEOUT.json').read_text())['all_known_managed_jobs_exited']
result=dict(passed=not failures,checked_unique_source_bindings=len(checked),failures=failures,source_files=modules,strategy_copies_identical=strategy_checks,new_physics_steps=0,finished_epoch_utc=time.time(),scope='Authoritative final reports and exact source bindings; earlier superseded/preliminary artifacts retained and not silently treated as final. Full repository legacy diagnostics not certified.')
(B/'FINAL_ARTIFACT_CHECK.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(dict(passed=result['passed'],bindings=len(checked),failures=failures[:12],strategy_copies=strategy_checks))
assert result['passed']
