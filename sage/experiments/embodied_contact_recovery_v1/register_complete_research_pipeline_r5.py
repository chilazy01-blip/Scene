"""Idempotent staged export of an audited complete failed development episode."""
import copy,json,re,sys,math
from pathlib import Path
from .work import E,c
from .dispatch import job,MOD
from . import controller_recovery_v4 as controller

def main(source_job,prefix):
 assert re.fullmatch(r'[CD]_development_\d{2}',source_job) and re.fullmatch(r'[CD]\d+',prefix)
 source=E/'jobs'/source_job;result=c.read(source/'RESULT.json');assert result['trace_summary']['physics_steps']>0 and not result['research_task_passed']
 audit=E/'jobs'/(source_job+'_audit');assert c.read(audit/'AUDIT.json')['passed']
 frames=(result['trace_summary']['physics_steps']+15)//16;shards=(frames+249)//250;reads=(frames+499)//500
 s=c.read(E/'STATE.json');defs=s['additional_jobs'];additions={}
 def rename(value):return json.loads(json.dumps(value).replace('D_development_03',source_job).replace('D3_',prefix+'_'))
 def ready(k):return s['jobs'].get(k,{}).get('status')=='succeeded'
 def clone(template,key,cfg,artifacts,passes=0):
  if key in s['jobs']:return
  old=defs[template];case=E/'cases'/(key+'.json')
  if case.exists():assert c.read(case)==cfg
  else:c.write(case,cfg)
  new=copy.deepcopy(old);new['argv'][-1]=str(case)
  # Reuse immutable code/runtime provenance, bind only this episode's artifacts.
  files=[Path(p) for p in old['inputs'] if not Path(p).is_relative_to(E)]
  files.extend([case,*map(Path,artifacts)])
  assert all(p.is_file() for p in files),[str(p) for p in files if not p.is_file()]
  new['inputs']={str(p):c.sha(p) for p in files}
  if passes:
   new['reservation']['render_passes']=passes
   new['timeout_seconds']=min(old['timeout_seconds'],max(180,math.ceil(passes*.6+30)))
   new['reservation']['service_seconds']=new['timeout_seconds']+5
  if frames<=1100 and ('_full_RGBD_export_' in key or '_full_RGBD_read_' in key):
   new['timeout_seconds']=180
   new['reservation']['service_seconds']=185
  if not passes and '_full_RGBD_' in key:
   new['kind']='seal'
   new['pool']='export_seal'
  additions[key]=new
 source_files=[source/'REQUEST.json',source/'RESULT.json',source/'episode/MODEL.mjb',source/'episode/TRACE.h5',audit/'REQUEST.json',audit/'AUDIT.json']
 numeric=prefix+'_complete_numeric_export_01';quality=prefix+'_contact_quality_frame_index_01'
 for template,key in [('D3_complete_numeric_export_01',numeric),('D3_contact_quality_frame_index_01',quality)]:
  clone(template,key,rename(c.read(defs[template]['argv'][-1])),source_files)
 if ready(numeric):
  numeric_file=E/'jobs'/numeric/'numeric_frames.h5'
  for i in range(shards):
   first,stop=i*250,min((i+1)*250,frames);key=f'{prefix}_clean_RGBD_shard_{i:04d}'
   cfg={'source_episode':str(source/'episode'),'numeric_source':str(numeric_file),'first_frame':first,'stop_frame':stop}
   clone('D3_clean_RGBD_shard_0000',key,cfg,[*source_files,numeric_file],4*(stop-first))
  assembly=prefix+'_clean_full_RGBD_assembly_01'
  if prefix+'_clean_full_RGBD_assembly_seal_01' in s['jobs']:assembly=prefix+'_clean_full_RGBD_assembly_seal_01'
  export=prefix+'_clean_full_RGBD_export_01';shardkeys=[f'{prefix}_clean_RGBD_shard_{i:04d}' for i in range(shards)]
  if all(ready(k) for k in shardkeys):
   cfg={'source_episode':str(source/'episode'),'numeric_source':str(numeric_file),'source_audit_job':str(audit),'shard_jobs':[str(E/'jobs'/k) for k in shardkeys],'expected_rows':frames,'complete_source_episode':True}
   files=[*source_files,numeric_file,*[E/'jobs'/k/n for k in shardkeys for n in ['REQUEST.json','SHARD_BINDING.json','shard.h5']]]
   clone('D3_clean_full_RGBD_assembly_01',assembly,cfg,files)
  if ready(assembly) and ready(quality):
   cfg=rename(c.read(defs['D3_clean_full_RGBD_export_01']['argv'][-1]));cfg=json.loads(json.dumps(cfg).replace(prefix+'_clean_full_RGBD_assembly_01',assembly));root=E/'jobs'/assembly/'assembled'
   files=[root/'BINDING.json',root/'canonical.h5',*[root/'chunks'/f'{i:04d}.h5' for i in range(shards)],E/'PHYSICAL_PARAMETER_EVIDENCE.json',E/(prefix+'_CONTACT_QUALITY_FRAME_INDEX.json'),E/'jobs'/quality/'contact_quality_index.h5']
   clone('D3_clean_full_RGBD_export_01',export,cfg,files)
  if ready(export):
   root=E/'jobs'/export/'dataset';files=[p for p in root.rglob('*') if p.is_file()]
   for i in range(reads):
    key=f'{prefix}_clean_full_RGBD_read_{i:02d}';cfg={'dataset_root':str(root),'first_row':i*500,'stop_row':min((i+1)*500,frames)}
    clone('D3_clean_full_RGBD_read_00',key,cfg,files)
  readkeys=[f'{prefix}_clean_full_RGBD_read_{i:02d}' for i in range(reads)]
  if all(ready(k) for k in readkeys):
   root=E/'jobs'/export/'dataset';cfg={'dataset_root':str(root),'read_jobs':[str(E/'jobs'/k) for k in readkeys],'output':prefix+'_CLEAN_FULL_RGBD_RESEARCH_DATASET_ACCEPTANCE.json'}
   files=[p for p in root.rglob('*') if p.is_file()]
   files.extend(p for k in readkeys for p in (E/'jobs'/k).glob('*.json'))
   clone('D3_clean_full_RGBD_acceptance_01',prefix+'_clean_full_RGBD_acceptance_01',cfg,files)
 if additions:
  result=controller.extend_jobs(E,additions,'Complete audited failed '+source_job+' through standard site-free RGBD pipeline with immutable actual-stage bindings')
  print({'registered':list(additions),'frames':frames,'decision':result['action']})
 else:print({'registered':[],'frames':frames,'awaiting_bound_predecessor':True})

if __name__=='__main__':main(*sys.argv[1:])
