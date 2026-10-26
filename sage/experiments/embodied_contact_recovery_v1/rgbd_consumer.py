"""Bind stored32-frame excerpt to audited physical source and use actual RGB-D dataset."""
import os,sys,shutil
from pathlib import Path
import numpy as np
import h5py
import mujoco
from .work import E,P,finish,c
work=Path(os.environ['CONTINUOUS_JOB_DIR']);cache=work/'hf_cache';cache.mkdir()
os.environ.update(HF_HOME=str(cache),HF_DATASETS_CACHE=str(cache/'datasets'),HF_HUB_CACHE=str(cache/'hub'),HF_HUB_OFFLINE='1',HF_DATASETS_OFFLINE='1',TOKENIZERS_PARALLELISM='false')
sys.path.append(str(P.parent/'hmg_external_control_20261007/vendor'))
from sage.experiments.embodied_payload_data_v1.typed_reader import RGBDTrainingDataset
from torch.utils.data import DataLoader
original=E/'jobs/reader_export_04/lerobot';canonical=E/'jobs/reader_diagnostic_02/data/canonical.h5';source=E/'jobs/C_development_01r/episode'
root=work/'dataset';shutil.copytree(original,root,copy_function=os.link)
os.link(canonical,root/'canonical.h5')
m=mujoco.MjModel.from_binary_path(str(source/'MODEL.mjb'));d=mujoco.MjData(m)
cameras=['overhead','wrist_cam'];errors=[]
with h5py.File(canonical,'r') as h,h5py.File(source/'TRACE.h5','r') as f:
 indices=h['source_substep_indices'][:];assert len(indices)==32
 assert np.array_equal(h['trajectory/timestamp'][:],f['substep/time_before'][indices])
 for i in [0,15,31]:
  mujoco.mj_setState(m,d,f['substep/integration_before'][int(indices[i])],mujoco.mjtState.mjSTATE_INTEGRATION);mujoco.mj_forward(m,d)
  for cam in cameras:
   cid=m.camera(cam).id;rotation=d.cam_xmat[cid].reshape(3,3)@np.diag([1.,-1.,-1.]);origin=d.cam_xpos[cid].copy();K=h['cameras/'+cam+'/K'][i]
   for u,v in [(96,96),(128,128),(160,160),(112,176),(176,112)]:
    if not h['cameras/'+cam+'/valid'][i,v,u]:continue
    ray=np.array([(u+.5-K[0,2])/K[0,0],(v+.5-K[1,2])/K[1,1],1.]);length=np.linalg.norm(ray);direction=rotation@ray/length
    hit=np.zeros(1,np.int32);dist=mujoco.mj_ray(m,d,origin,direction,np.array([1,1,1,0,0,0],np.uint8),1,-1,hit)
    if dist<0:continue
    actual=float(h['cameras/'+cam+'/depth_m'][i,v,u]);expected=dist/length
    errors.append({'frame':i,'camera':cam,'pixel':[u,v],'geom':m.geom(int(hit[0])).name,'stored_depth_m':actual,'ray_depth_m':float(expected),'absolute_error_m':abs(actual-expected)})
assert errors and max(x['absolute_error_m'] for x in errors)<.003,errors
assert c.read(E/'jobs/C_development_01r_audit/AUDIT.json')['passed']
files={str(p.relative_to(root)):c.sha(p) for p in root.rglob('*') if p.is_file() and 'canonical' not in p.name}
binding={'completed':True,'canonical_independent_audit_passed':True,'export_files':files,'canonical_relative_path':'canonical.h5','canonical_sha256':c.sha(canonical),'cameras':cameras,'rows':32,
         'physical_source_sha256':c.sha(source/'TRACE.h5'),'physical_audit_sha256':c.sha(E/'jobs/C_development_01r_audit/AUDIT.json'),'production_accepted':False,'episode_success':False,'scope':'research failure excerpt; not accepted training data'}
c.write(root/'BINDING.json',binding)
reader=RGBDTrainingDataset(root);assert len(reader)==32;read_rows=0
with h5py.File(canonical,'r') as f:
 for batch in DataLoader(reader,batch_size=8,num_workers=0,shuffle=False):
  for k in range(len(batch['frame_index'])):
   i=int(batch['frame_index'][k]);assert i==read_rows;read_rows+=1
   for cam in cameras:
    assert np.array_equal(batch['observation.depth_m.'+cam][k].numpy(),f['cameras/'+cam+'/depth_m'][i])
    assert np.array_equal(batch['observation.depth_valid.'+cam][k].numpy(),f['cameras/'+cam+'/valid'][i])
assert read_rows==32
report={'passed':True,'reader_class':'RGBDTrainingDataset','actual_dataloader_rows':read_rows,'batch_size':8,'source_alignment_exact':True,
        'ray_depth_checks':errors,'max_ray_depth_error_m':max(x['absolute_error_m'] for x in errors),'new_render_passes':0,'new_physics_steps':0,'training_updates':0,
        'public_observations_exclude_teacher_object_truth':True,'production_accepted':False,'root':str(root),'binding_sha256':c.sha(root/'BINDING.json')}
c.write(E/'REAL_RGBD_CONSUMER_REPORT.json',report);finish(report)
