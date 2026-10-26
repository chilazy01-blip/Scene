"""Independent final artifact checks; primary visual observations are explicit inputs."""
from pathlib import Path
import hashlib,json,sys,time
import numpy as np
R=Path(__file__).resolve().parents[1]
def bind(p):
 p=Path(p);return dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest(),size_bytes=p.stat().st_size)
def save(p,d):
 assert not p.exists(),p
 d['content_sha256_excluding_this_field']=hashlib.sha256(json.dumps(d,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
 p.write_text(json.dumps(d,ensure_ascii=False,indent=2,sort_keys=True)+'\n')
def read(p):return json.loads(p.read_text())
def bindings(d):
 if isinstance(d,dict):
  if 'path' in d and 'sha256' in d and isinstance(d['path'],str):
   assert bind(d['path'])['sha256']==d['sha256'],d['path']
  for v in d.values():bindings(v)
 elif isinstance(d,list):
  for v in d:bindings(v)
def run(name):
 t=R/'trials'/name;r=read(t/'full/REPORT.json');audit_path=next(t/('full/AUDIT_'+v+'.json') for v in ('v4','v3','v2') if (t/('full/AUDIT_'+v+'.json')).exists());a=read(audit_path);f=read(t/'FORCE_CHECK.json');m=read(t/'MEASUREMENTS.json')
 version=next(v for v in ('v6','v5','v4') if (t/((('delivery_' if r['task_passed'] else 'partial_delivery_')+v))/'REVIEW.json').exists());output=t/(('delivery_' if r['task_passed'] else 'partial_delivery_')+version);d=read(output/'REVIEW.json')
 observations=read(R/'PRIMARY_VISUAL_OBSERVATIONS.json')[name]
 assert observations['sampled_actual_frames_reviewed'] and not observations['claim_every_frame_manually_reviewed']
 reviewed=[bind(t/p) for p in observations['files']]
 assert d['all_decoded_frames']==(r['physics_steps']+3)//4
 assert a['executed_control_reconstruction_passed']
 assert max(f[k] for k in ['maximum_hand_and_desk_force_error_n','maximum_static_capacity_error','maximum_slip_error_m_s'])<1e-8
 for doc in [r,a,f,m,d]:bindings(doc)
 c=r['checkpoint_continuation']
 assert r['new_physics_steps']==r['physics_steps'] and c['fresh_original_initialization'] and c['exact_state_restore_count']==0 and c['prefix_physics_steps']==0 and c['prefix_active_ticks']==0
 npz_checks={};policy=Path(r['policy_io']['path'])
 with np.load(policy,allow_pickle=False) as x:
  assert set(x.files)=={'encoder_inputs','decoder_inputs','reference_qpos','reference_velocity'}
  for k in x.files:
   assert len(x[k])==r['active_ticks'] and np.isfinite(x[k]).all()
 positive=bool(d['mechanically_qualified'])
 if positive:
  assert r['task_passed'] and a['task_passed'] and all(r['gates'].values()) and m['additional_upright_quality_passed']
  replay=read(t/'continuous_replay/REPORT.json');bindings(replay)
  assert replay['passed'] and replay['no_numerical_warnings'] and replay['initializations']==1 and replay['intermediate_state_injections']==0
  assert replay['physics_steps']==r['physics_steps'] and max(replay['maximum_absolute_error'].values())==0
  assert not replay['actual_numerical_warning_events'] and all(x['number']==0 for x in replay['actual_numerical_warning_counters'])
  with np.load(output/'episode.npz',allow_pickle=False) as x:
   n=r['physics_steps'];expected={'qpos_before':57,'qpos_after':57,'qvel_before':55,'qvel_after':55,'qacc_warmstart_before':55,'qacc_warmstart_after':55,'ctrl':43,'body_target_rad':29,'hand_target_rad':14,'body_feedforward_nm':29,'object_position_m':3}
   for k in x.files:
    assert len(x[k])==n
    if x[k].dtype.kind in 'fiu':assert np.isfinite(x[k]).all(),k
    npz_checks[k]=list(x[k].shape)
   for k,w in expected.items():assert x[k].shape==(n,w)
   assert x['time_s'].shape==(n,) and np.max(np.abs(np.diff(x['time_s'])-.005))<1e-10
   for before,after in [('qpos_before','qpos_after'),('qvel_before','qvel_after'),('qacc_warmstart_before','qacc_warmstart_after')]:assert np.array_equal(x[before][1:],x[after][:-1]),before
 else:
  assert not list(t.glob('*/episode.npz')),name
 evidence={k:bind(t/p) for k,p in {'report':'full/REPORT.json','audit':str(audit_path.relative_to(t)),'force':'FORCE_CHECK.json','measurements':'MEASUREMENTS.json','delivery':str(output.relative_to(t)/'REVIEW.json'),'video':'actual_video_v3/MANIFEST.json'}.items()}
 if positive:evidence.update(episode=bind(output/'episode.npz'),replay=bind(t/'continuous_replay/REPORT.json'))
 result=dict(complete=True,positive=positive,source_role='development_validation',dataset_split='unassigned',numerically_quarantined=name in ['book_s02_v001','book_s03_v001'],new_physics_steps=0,primary_visual_observations=observations,reviewed_images=reviewed,all_video_frames_automatically_decoded=d['all_decoded_frames'],npz_shapes=npz_checks,evidence=evidence,implementation=bind(Path(__file__)),verified_epoch_utc=time.time())
 save(t/'FINAL_VERIFICATION.json',result)
 print(dict(trial=name,positive=positive,verified=True),flush=True)
if __name__=='__main__':
 for n in sys.argv[1:]:run(n)
