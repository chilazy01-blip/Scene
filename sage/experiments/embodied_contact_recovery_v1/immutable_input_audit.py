"""Rehash immutable input bindings of completed jobs from a frozen ledger."""
import sys
from pathlib import Path
from .work import E,c,finish

def main(config):
 cfg=c.read(config);s=c.read(cfg['state_snapshot']);p=c.read(cfg['plan_snapshot']);defs={**p['jobs'],**s.get('additional_jobs',{})};bound={};jobs=[]
 for name,state in s['jobs'].items():
  request=E/'jobs'/name/'REQUEST.json'
  if state['status'] not in ['succeeded','failed'] or not request.exists():continue
  actual=c.read(request);jobs.append(name)
  for path,digest in actual['inputs'].items():bound.setdefault(path,{}).setdefault(digest,[]).append(name)
 missing=[];mismatch=[];conflicts=[];checked=0;total=0
 for path,expected in sorted(bound.items()):
  f=Path(path)
  if not f.is_file():missing.append({'path':path,'expected_bindings':expected});continue
  digest=c.sha(f);checked+=1;total+=f.stat().st_size
  if len(expected)>1:conflicts.append({'path':path,'historical_bindings':expected,'current_sha256':digest})
  for old,names in expected.items():
   if digest!=old:mismatch.append({'path':path,'expected_sha256':old,'current_sha256':digest,'jobs':names})
 report={'complete':True,'passed':not missing and not mismatch,'completed_job_count':len(jobs),'unique_input_file_count':len(bound),'files_rehashed':checked,'bytes_rehashed':total,'missing':missing,'mismatches':mismatch,'multiple_historical_hashes':conflicts,'state_snapshot_sha256':c.sha(cfg['state_snapshot']),'plan_snapshot_sha256':c.sha(cfg['plan_snapshot']),'new_physics_steps':0,'production_accepted':False,'scope':'Independent current-byte verification against completed request bindings; any approved control-file evolution must be separately reconciled, never silently waived.'}
 c.write(E/cfg['output'],report);finish(report)
if __name__=='__main__':main(sys.argv[1])
