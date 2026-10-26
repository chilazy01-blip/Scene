"""Reconcile only schedule metadata against frozen engine and full causal audit.
No integration; preserve every original physical and control gate.
"""
import ast
from pathlib import Path
import numpy as np
from .common import read_bound_json, safe_save, _file_binding, check

def run(root):
 episode=root/'full';basepath=episode/'AUDIT_v3.json'
 base=read_bound_json(basepath);report=read_bound_json(episode/'REPORT.json')
 check(base['implementation']);check(base['base_full_independent_audit']);check(report['engine']);check(report['trace'])
 assert base['report']==_file_binding(episode/'REPORT.json')
 assert all(v for k,v in base['gates'].items() if k not in ('bounded_complete_episode','causal_observation_metadata'))
 tree=ast.parse(Path(report['engine']['path']).read_text())
 # Verify the observed schedule and zero warmup hand latch from actual frozen source.
 warm=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='physical' and len(n.args)==5 and isinstance(n.args[3],ast.Constant) and n.args[3].value=='warmup']
 assert len(warm)==1 and ast.unparse(warm[0].args[4])=='tick - 10'
 assert any(isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='held_hands' for t in n.targets) and ast.unparse(n.value)=='np.zeros(14)' for n in ast.walk(tree))
 trace=read_bound_json(Path(report['trace']['path']));mismatches=[];legacy=[];total=0
 assert len(trace['warmup_substeps'])==40
 for i,s in enumerate(trace['warmup_substeps']):
  expected=i//4-10
  if s['tick']!=-1:legacy.append(dict(substep=i,recorded_tick=s['tick'],old_auditor_expected_tick=-1,correct_tick=expected))
  if not(s['tick']==expected and s['active'] is False and s['stage']=='warmup' and np.array_equal(s['hand_target_rad'],np.zeros(14))):mismatches.append(('warmup',i))
  total+=1
 for i,row in enumerate(trace['records']):
  assert row['tick']==i
  for j,s in enumerate(row['substeps']):
   # Stage and hand equality to task-generated commands are already independently
   # established by base causal_reference; metadata schedule is reconstructed here.
   if not(s['tick']==i and s['active'] is True and s['stage']==row['stage']):mismatches.append(('active',i,j))
   total+=1
 assert total==report['physics_steps']
 gates=dict(base['gates']);gates['causal_observation_metadata']=not mismatches
 out=dict(base);out.pop('content_sha256_excluding_this_field',None)
 out.update(schema='native-independent-audit-metadata-reconciliation/v4',gates=gates,control_passed=all(gates.values()),executed_control_reconstruction_passed=all(v for k,v in gates.items() if k!='bounded_complete_episode'),task_passed=all(gates.values()) and report['task_passed'],previous_full_audit=_file_binding(basepath),implementation=_file_binding(Path(__file__)),metadata_substeps_checked=total,metadata_mismatches=mismatches,legacy_warmup_mismatch_diagnosis=legacy,new_physics_steps=0,correction='Only old warmup tick assumption -1 replaced by frozen engine tick-10, four substeps per warmup frame. All original physical/control/causal gates retained. Negative completion gate stays false.')
 safe_save(episode/'AUDIT_v4.json',out)
 print(dict(root=str(root),executed_control_reconstruction_passed=out['executed_control_reconstruction_passed'],failed=[k for k,v in gates.items() if not v],corrected_warmup_substeps=len(legacy),new_physics_steps=0),flush=True)

if __name__=='__main__':
 import argparse
 ap=argparse.ArgumentParser();ap.add_argument('--root',required=True,type=Path);run(ap.parse_args().root)
