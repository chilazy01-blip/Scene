from pathlib import Path
import hashlib,json
import numpy as np
import h5py

SCHEMA='embodied-native-trajectory/v1'
A_NAMES=['forward','turn','lift','arm_extend','wrist_yaw','grip','head_pan','head_tilt']
A_POSITION_UNITS=['rad','rad','m','m','rad','m','rad','rad']
A_ACTION_UNITS=['N*m','N*m','m','m','rad','m','rad','rad']

def require(ok,reason):
 if not ok:raise ValueError(reason)

def reference(path):
 p=Path(path);return dict(path=str(p.resolve()),sha256=hashlib.sha256(p.read_bytes()).hexdigest())

def bound(ref):
 p=Path(ref['path']);require(hashlib.sha256(p.read_bytes()).hexdigest()==ref['sha256'],'source_hash:'+p.name);return p

def read(ref):return json.loads(bound(ref).read_text())

def arrays(ref):
 with np.load(bound(ref),allow_pickle=False) as f:return {k:f[k].copy() for k in f.files}

def failure_class(failures):
 mapping={'extra_compression':'grasp.closure.extra_displacement','xy_drift':'body.horizontal_drift','tilt':'body.tilt','contacts':'contact.unexpected','joint_speed':'joint.speed','joint_limits':'joint.range'}
 return [mapping.get(x,'unmapped:'+x) for x in failures]

def source(spec):
 result=read(spec['result']);bound(spec['model']);audit=read(spec['audit'])
 if spec['adapter']=='stretch_task_v2':
  read(spec['task']);chunks=[];phase_names=[]
  for phase in spec['phases']:
   a=arrays(phase['raw']);res=read(phase['result']);require(res['id']==phase['id'],'phase_identity')
   n=len(a['ctrl']);require(len(a['time'])==n+1 and n==res['steps'],'phase_length')
   if chunks:
    for k in ['time','qpos','qvel','actuator_length','actuator_velocity']:
     require(np.array_equal(chunks[-1][k][-1],a[k][0]),'phase_boundary:'+k)
   chunks.append(a);phase_names.extend([phase['id']]*n)
  def states(key):return np.concatenate([a[key] if i==0 else a[key][1:] for i,a in enumerate(chunks)])
  time=states('time');proprio=np.concatenate([states('actuator_length'),states('actuator_velocity')],axis=1)
  action=np.concatenate([a['ctrl'] for a in chunks]);actual=action.copy();qpos=states('qpos');qvel=states('qvel')
  failures=read(spec['phases'][-1]['result'])['failures'];require(result['status']=='physical_failure' and failures,'expected_physical_failure')
  meta=dict(embodiment='Stretch_Menagerie',action_names=A_NAMES,action_units=A_ACTION_UNITS,action_semantics=['native_motor_effort_pre_gear']*2+['position_reference']*6,action_frame='native_actuator',proprio_names=[n+'_actuator_length' for n in A_NAMES]+[n+'_actuator_velocity' for n in A_NAMES],proprio_units=A_POSITION_UNITS+[u+'/s' for u in A_POSITION_UNITS],proprio_note='MuJoCo transmission coordinates; first two lengths include gear=3 and fixed wheel tendon combinations; not mobile-base xyz or velocity',dt=.001,source_status=result['status'],task_success=False,scope='failed_complete_task_attempt',failures=failures,failure_classes=failure_class(failures),actual_control_names=A_NAMES,actual_control_units=A_ACTION_UNITS,reference_sample='command formed from pre-step state; position plan reference sampled at substep end; ctrl held during interval')
 elif spec['adapter']=='g1_native_v1':
  a=arrays(spec['raw']);b=read(spec['binding']);rows=b['joints'];require(audit['status']=='saved_audit_pass' and audit['verdict']==result['status'],'B_audit')
  time=a['time'];proprio=np.concatenate([a['qpos'][:,[r['qpos'] for r in rows]],a['qvel'][:,[r['qvel'] for r in rows]]],axis=1)
  action=a['target'];actual=a['ctrl'];qpos=a['qpos'];qvel=a['qvel'];phase_names=['left_hand' if i*.005<2 else 'right_hand' for i in range(len(action))];names=[r['name'] for r in rows]
  meta=dict(embodiment='G1_activated_3dex',action_names=names,action_units=['rad']*43,action_semantics=['position_reference']*43,action_frame='native_mjcf_joint',proprio_names=[n+'_q' for n in names]+[n+'_dq' for n in names],proprio_units=['rad']*43+['rad/s']*43,dt=.005,source_status=result['status'],task_success=False,scope='control_admission_only',failures=result['failures'],failure_classes=failure_class(result['failures']),actual_control_names=[r['name'] for r in sorted(rows,key=lambda x:x['actuator'])],actual_control_units=['N*m']*43,reference_sample='lower body policy at block-start 50Hz; hand reference at substep start; PD refreshed every 5ms')
 else:raise ValueError('unsupported_adapter')
 n=len(action);require(n>0 and len(time)==n+1 and len(proprio)==n+1,'trajectory_length')
 require(np.max(abs(np.diff(time)-meta['dt']))<1e-10,'time_alignment')
 require(action.shape==(n,len(meta['action_names'])) and proprio.shape==(n+1,len(meta['proprio_names'])),'channel_shape')
 require(len(set(meta['action_names']))==action.shape[1],'duplicate_names')
 for v in [time,proprio,action,actual,qpos,qvel]:require(np.isfinite(v).all(),'nonfinite_source')
 terminated=np.zeros(n,bool);truncated=np.zeros(n,bool)
 if meta['failures']:terminated[-1]=True
 else:truncated[-1]=True
 meta.update(schema=SCHEMA,id=spec['id'],split='development',transitions=n,camera_present=False,qualified_training=False,learning_effect='unknown',observation_timing='observation[i] precedes action[i], next observation[i+1] follows it',privileged_default=False)
 return meta,dict(time=time,proprio=proprio,action=action,actual_control=actual,qpos=qpos,qvel=qvel,terminated=terminated,truncated=truncated,phase=np.array(phase_names,dtype='S32'))

FIELDS={'observation/time':'time','observation/proprio':'proprio','action':'action','outcome/terminated':'terminated','outcome/truncated':'truncated','audit/actual_control':'actual_control','audit/qpos':'qpos','audit/qvel':'qvel','audit/phase':'phase'}

def export(spec,directory):
 directory=Path(directory);directory.mkdir(exist_ok=False);meta,a=source(spec)
 with h5py.File(directory/'episode.h5','x') as f:
  f.attrs['metadata']=json.dumps(meta,sort_keys=True)
  for path,key in FIELDS.items():f.create_dataset(path,data=a[key],compression='gzip',shuffle=True)
 b=dict(schema=SCHEMA,source=spec,metadata=meta,hdf5=reference(directory/'episode.h5'),implementation=reference(__file__))
 (directory/'BINDING.json').write_text(json.dumps(b,indent=2));return reference(directory/'BINDING.json')

class TrajectoryDataset:
 """A map-style Dataset consumed by torch DataLoader, with strict source validation."""
 def __init__(self,binding,pin,purpose='proprio_development',required_modalities=('proprio',)):
  require(purpose in ['inspection','proprio_development'],'purpose_not_qualified')
  b=read(dict(path=str(binding),sha256=pin));require(b['schema']==SCHEMA,'schema');bound(b['implementation'])
  meta,expected=source(b['source']);require(meta==b['metadata'],'metadata_source_mismatch')
  require(tuple(required_modalities)==('proprio',),'camera_or_modality_missing')
  with h5py.File(bound(b['hdf5']),'r') as f:
   require(json.loads(f.attrs['metadata'])==meta,'hdf5_metadata')
   for path,key in FIELDS.items():require(np.array_equal(f[path][:],expected[key]),'saved_mismatch:'+path)
   require('rgb' not in f['observation'],'unexpected_camera')
   loaded={key:f[path][:] for path,key in FIELDS.items() if key in ['time','proprio','action','terminated','truncated']}
  self.metadata=meta;self.data=loaded
 def __len__(self):return self.metadata['transitions']
 def __getitem__(self,index):
  if not isinstance(index,(int,np.integer)) or not 0<=index<len(self):raise IndexError(index)
  a=self.data
  return dict(time=a['time'][index],proprio=a['proprio'][index].copy(),action=a['action'][index].copy(),next_time=a['time'][index+1],next_proprio=a['proprio'][index+1].copy(),terminated=a['terminated'][index],truncated=a['truncated'][index])
