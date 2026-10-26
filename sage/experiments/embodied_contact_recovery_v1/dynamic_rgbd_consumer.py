"""Independent saved-state/camera audit and real consumer for a research segment."""
import os,sys,shutil
from pathlib import Path
import numpy as np,h5py,mujoco
from .work import E,P,c,finish
source_name,export_name=sys.argv[1:];work=Path(os.environ['CONTINUOUS_JOB_DIR'])
source=E/'jobs'/source_name/'episode';export=E/'jobs'/export_name;canonical=export/'data/canonical.h5'
assert c.read(export/'DATA_READ_REPORT.json')['passed']
cache=work/'hf_cache';cache.mkdir();os.environ.update(HF_HOME=str(cache),HF_DATASETS_CACHE=str(cache/'datasets'),HF_HUB_CACHE=str(cache/'hub'),HF_HUB_OFFLINE='1',HF_DATASETS_OFFLINE='1',TOKENIZERS_PARALLELISM='false')
sys.path.append(str(P.parent/'hmg_external_control_20261007/vendor'))
from sage.experiments.embodied_payload_data_v1.typed_reader import RGBDTrainingDataset
from torch.utils.data import DataLoader
m=mujoco.MjModel.from_binary_path(str(source/'MODEL.mjb'));d=mujoco.MjData(m)
names=[m.joint(j).name for j in range(m.njnt) if m.jnt_type[j]==mujoco.mjtJoint.mjJNT_HINGE];qa=[m.jnt_qposadr[m.joint(n).id] for n in names];va=[m.jnt_dofadr[m.joint(n).id] for n in names];aids=[m.actuator(n).id for n in names]
cameras=['overhead','wrist_cam'];errors={};rays=[]
def compare(key,x,y):errors[key]=max(errors.get(key,0.),float(np.max(np.abs(np.asarray(x)-np.asarray(y)))))
with h5py.File(canonical,'r') as h,h5py.File(source/'TRACE.h5','r') as f:
 indices=h['source_substep_indices'][:];count=len(indices)
 assert np.array_equal(h['trajectory/timestamp'][:],f['substep/time_before'][indices])
 assert np.allclose(np.diff(h['trajectory/timestamp'][:]),.04,atol=1e-10,rtol=0.)
 for i,k in enumerate(indices):
  mujoco.mj_setState(m,d,f['substep/integration_before'][k],mujoco.mjtState.mjSTATE_INTEGRATION)
  compare('q',h['trajectory/joint_position'][i],d.qpos[qa]);compare('v',h['trajectory/joint_velocity'][i],d.qvel[va]);compare('base_quat',h['trajectory/base_orientation_wxyz'][i],d.qpos[3:7]);compare('gyro',h['trajectory/base_gyro_rps'][i],d.qvel[3:6])
  compare('previous_command',h['trajectory/previous_command'][i],f['substep/ctrl'][max(0,k-1)][aids])
  for j in range(2):
   row=int(k+j*8);compare('action',h['trajectory/action_chunk'][i,j],f['substep/ctrl'][row][aids]);compare('action_time',h['trajectory/action_timestamps'][i,j],f['substep/time_before'][row])
  if i not in np.linspace(0,count-1,10,dtype=int):continue
  mujoco.mj_forward(m,d)
  rb=np.zeros(9);mujoco.mju_quat2Mat(rb,d.qpos[3:7]);rb=rb.reshape(3,3)
  for cam in cameras:
   cid=m.camera(cam).id;rotation=d.cam_xmat[cid].reshape(3,3)@np.diag([1.,-1.,-1.]);origin=d.cam_xpos[cid].copy();K=h['cameras/'+cam+'/K'][i]
   T=np.eye(4);T[:3,:3]=rb.T@rotation;T[:3,3]=rb.T@(origin-d.qpos[:3]);compare('extrinsics',h['cameras/'+cam+'/optical_to_base'][i],T)
   for u,v in [(96,96),(128,128),(160,160),(112,176),(176,112)]:
    if not h['cameras/'+cam+'/valid'][i,v,u]:continue
    ray=np.array([(u+.5-K[0,2])/K[0,0],(v+.5-K[1,2])/K[1,1],1.]);length=np.linalg.norm(ray);direction=rotation@ray/length
    near=float(m.vis.map.znear*m.stat.extent);near_distance=near*length;hit=np.zeros(1,np.int32)
    dist=mujoco.mj_ray(m,d,origin+direction*near_distance,direction,np.array([1,1,1,0,0,0],np.uint8),1,-1,hit)
    if dist<0:continue
    actual=float(h['cameras/'+cam+'/depth_m'][i,v,u]);expected=(dist+near_distance)/length
    rays.append({'frame':i,'camera':cam,'pixel':[u,v],'absolute_error_m':abs(actual-expected)})
assert all(v==0. for v in errors.values()),errors
assert rays and max(r['absolute_error_m'] for r in rays)<.003,rays
root=work/'dataset';shutil.copytree(export/'data/lerobot',root,copy_function=os.link);os.link(canonical,root/'canonical.h5')
files={str(p.relative_to(root)):c.sha(p) for p in root.rglob('*') if p.is_file() and p.name!='canonical.h5'}
binding={'completed':True,'canonical_independent_audit_passed':True,'canonical_audit_scope':'Independent all-row saved-state/action/time comparison and sampled depth rays; NOT an independent physical rerun.',
 'export_files':files,'canonical_relative_path':'canonical.h5','canonical_sha256':c.sha(canonical),'cameras':cameras,'rows':count,'physical_source_sha256':c.sha(source/'TRACE.h5'),
 'physical_source_independent_reintegration':False,'production_accepted':False,'episode_success':False,'segment_truncated':True,'scope':'Research diagnostic contact segment with failed object upright quality; not an accepted training episode'}
c.write(root/'BINDING.json',binding);reader=RGBDTrainingDataset(root);read_rows=0
with h5py.File(canonical,'r') as f:
 for batch in DataLoader(reader,batch_size=8,num_workers=0,shuffle=False):
  for k in range(len(batch['frame_index'])):
   i=int(batch['frame_index'][k]);assert i==read_rows;read_rows+=1
   for cam in cameras:
    assert np.array_equal(batch['observation.depth_m.'+cam][k].numpy(),f['cameras/'+cam+'/depth_m'][i]);assert np.array_equal(batch['observation.depth_valid.'+cam][k].numpy(),f['cameras/'+cam+'/valid'][i])
assert read_rows==count
report={'passed':True,'actual_dataloader_rows':read_rows,'batch_size':8,'independent_source_max_errors':errors,'ray_depth_checks':rays,'max_ray_depth_error_m':max(r['absolute_error_m'] for r in rays),'new_render_passes':0,'new_physics_steps':0,'training_updates':0,'physical_rerun_claimed':False,'production_accepted':False,'root':str(root),'binding_sha256':c.sha(root/'BINDING.json')}
c.write(E/'DYNAMIC_RGBD_CONSUMER_REPORT.json',report);finish(report)
