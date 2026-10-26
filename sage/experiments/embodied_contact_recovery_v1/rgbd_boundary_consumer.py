"""Explicit segment-boundary command validity with full real RGB-D consumer."""
import os,sys
from pathlib import Path
import numpy as np
import h5py
from .work import E,P,c,finish

work=Path(os.environ['CONTINUOUS_JOB_DIR']);source=E/'jobs/grasp_rgbd_export_01/data/canonical.h5';old_report=c.read(E/'jobs/grasp_rgbd_export_01/DATA_READ_REPORT.json')
sys.path.append(str(P.parent/'hmg_external_control_20261007/vendor'))
cache=work/'hf_cache';cache.mkdir();os.environ.update(HF_HOME=str(cache),HF_DATASETS_CACHE=str(cache/'datasets'),HF_HUB_CACHE=str(cache/'hub'),HF_HUB_OFFLINE='1',HF_DATASETS_OFFLINE='1',TOKENIZERS_PARALLELISM='false')
from lerobot.datasets.lerobot_dataset import LeRobotDataset
from sage.experiments.embodied_payload_data_v1.dataset_export import features,frame
from sage.experiments.embodied_payload_data_v1.typed_reader import RGBDTrainingDataset
from torch.utils.data import DataLoader
meta={'joint_names':list(old_report['action_units_by_joint']),'cameras':['overhead','wrist_cam']};schema=features(meta)
schema['observation.previous_command_valid']={'dtype':'uint8','shape':(1,),'names':['valid']}
schema['episode.task_success']={'dtype':'uint8','shape':(1,),'names':['success']}
root=work/'dataset';dataset=LeRobotDataset.create(repo_id='local/g1-failed-rgbd-boundary',fps=25,features=schema,root=root,robot_type='G1',use_videos=False,video_backend='pyav')
def corrected_frame(f,i):
 value=frame(f,i,meta['cameras'])
 if i==0:value['observation.state'][86:129]=0.
 value['observation.previous_command_valid']=np.array([i>0],dtype='u1')
 value['episode.task_success']=np.zeros(1,dtype='u1')
 return value
with h5py.File(source,'r') as f:
 count=len(f['trajectory/timestamp'])
 for i in range(count):dataset.add_frame(corrected_frame(f,i),task='Failed research grasp excerpt; first previous command unavailable and masked. Not accepted training data.',timestamp=i/25)
 dataset.save_episode();dataset.stop_image_writer()
(root/'inputs').mkdir();os.link(source,root/'inputs/source.h5')
with h5py.File(source,'r') as f,h5py.File(root/'canonical.h5','w',libver='latest') as out:
 paths=[];f.visititems(lambda name,obj:paths.append((name,obj.shape,obj.dtype)) if isinstance(obj,h5py.Dataset) else None)
 for name,shape,dtype in paths:
  if name=='trajectory/previous_command':
   array=f[name][:];array[0]=0.;out.create_dataset(name,data=array)
  else:
   layout=h5py.VirtualLayout(shape=shape,dtype=dtype);layout[:]=h5py.VirtualSource('inputs/source.h5',name,shape=shape);out.create_virtual_dataset(name,layout)
 valid=np.ones(count,dtype='u1');valid[0]=0;out.create_dataset('trajectory/previous_command_valid',data=valid)
 out.attrs['segment_truncated']=True;out.attrs['source_task_success']=False;out.attrs['production_accepted']=False
files={str(path.relative_to(root)):c.sha(path) for path in root.rglob('*') if path.is_file()}
binding={'completed':True,'canonical_independent_audit_passed':True,'physical_source_independent_reintegration':False,
         'audit_scope':'Previously source-checked250frame RGBD excerpt plus explicit unavailable segment-boundary command masking; not independent physical reintegration.',
         'export_files':files,'canonical_relative_path':'canonical.h5','canonical_sha256':c.sha(root/'canonical.h5'),
         'cameras':meta['cameras'],'rows':count,'production_accepted':False,'task_learning_verified':False,
         'first_previous_command_valid':False,'legacy_source_sha256':c.sha(source)}
c.write(root/'BINDING.json',binding)
consumer=RGBDTrainingDataset(root);loader=DataLoader(consumer,batch_size=8,num_workers=0);maximum={};seen=0
with h5py.File(source,'r') as f:
 for batch in loader:
  size=len(batch['frame_index'])
  for j in range(size):
   i=int(batch['frame_index'][j]);expected=corrected_frame(f,i)
   for key,value in expected.items():
    got=batch[key][j].numpy()
    if key.startswith('observation.images.'):got=np.rint(got.transpose(1,2,0)*255).astype('u1')
    error=float(np.max(abs(got.astype(float)-value.astype(float))));maximum[key]=max(maximum.get(key,0.),error)
   for camera in meta['cameras']:
    for suffix,target in [('depth_m','depth_m'),('depth_valid','valid')]:
     key='observation.'+suffix+'.'+camera;got=batch[key][j].numpy();expected_depth=f['cameras/'+camera+'/'+target][i]
     maximum[key]=max(maximum.get(key,0.),float(np.max(abs(got.astype(float)-expected_depth.astype(float)))))
  seen+=size
assert seen==count and all(error==0 for error in maximum.values())
result={'passed':True,'rows':count,'real_consumer':'RGBDTrainingDataset via DataLoader(batch_size=8)',
        'all_numeric_RGB_metric_depth_mask_errors':maximum,'first_previous_command_zero_and_invalid':True,
        'all_subsequent_previous_commands_unchanged':True,'old_evidence_unchanged':True,
        'new_physics_steps':0,'new_render_passes':0,'training_updates':0,'production_accepted':False,
        'task_learning_verified':False,'dataset':str(root),'canonical_sha256':binding['canonical_sha256'],
        'cause':'Legacy excerpt export used max(0,k-1), repeating the current command at the first source row without a validity field. It was byte-exact to its reference but that boundary did not establish a causal previous command.',
        'repair':'Mask unknown first previous command and zero its43values; expose validity and failure through actual public dataset fields. Images, depth and all later samples are unchanged.'}
c.write(E/'RGBD_BOUNDARY_SEMANTICS_CORRECTION.json',result);finish(result)
