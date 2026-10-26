"""Independent immutable RGB-D shards and a portable bound virtual assembly."""
import os,sys
from pathlib import Path
import numpy as np
import h5py
from .work import E,c,finish

CAMERAS=['overhead','wrist_cam']

def render(config_path):
 import mujoco
 cfg=c.read(config_path);source=Path(cfg['source_episode']);numeric=Path(cfg['numeric_source']);work=Path(os.environ['CONTINUOUS_JOB_DIR'])
 first,stop=int(cfg['first_frame']),int(cfg['stop_frame']);assert 0<=first<stop
 m=mujoco.MjModel.from_binary_path(str(source/'MODEL.mjb'));d=mujoco.MjData(m)
 renderer=mujoco.Renderer(m,256,256);usage={'render_passes':0}
 mujoco.mj_step=lambda *a,**k:(_ for _ in ()).throw(AssertionError('render_must_not_integrate'))
 try:
  with h5py.File(numeric,'r') as n,h5py.File(source/'TRACE.h5','r') as trace,h5py.File(work/'shard.h5','w') as out:
   count=stop-first;assert stop<=len(n['source_substep_indices']);indices=n['source_substep_indices'][first:stop]
   out.attrs['first_frame']=first;out.attrs['stop_frame']=stop;out.attrs['complete']=False
   out.create_dataset('source_substep_indices',data=indices)
   for key in n['trajectory']:out.create_dataset('trajectory/'+key,data=n['trajectory/'+key][first:stop],compression='lzf')
   for cam in CAMERAS:
    for key,shape,dtype in [('rgb',(count,256,256,3),'u1'),('depth_m',(count,256,256),'f4'),('valid',(count,256,256),'u1'),('K',(count,3,3),'f8'),('optical_to_base',(count,4,4),'f8')]:
     out.create_dataset('cameras/'+cam+'/'+key,shape=shape,dtype=dtype,chunks=True,compression='lzf')
   for i,k in enumerate(indices):
    mujoco.mj_setState(m,d,trace['substep/integration_before'][int(k)],mujoco.mjtState.mjSTATE_INTEGRATION);mujoco.mj_forward(m,d)
    assert abs(float(n['trajectory/timestamp'][first+i])-d.time)<1e-12
    rb=np.zeros(9);mujoco.mju_quat2Mat(rb,d.qpos[3:7]);rb=rb.reshape(3,3)
    for cam in CAMERAS:
     cid=m.camera(cam).id;renderer.disable_depth_rendering();renderer.update_scene(d,camera=cam);usage['render_passes']+=1;rgb=renderer.render().copy()
     renderer.enable_depth_rendering();usage['render_passes']+=1;depth=renderer.render().astype('f4')
     near=float(m.vis.map.znear*m.stat.extent);far=float(m.vis.map.zfar*m.stat.extent);valid=((depth>near)&(depth<far*(1-1e-5))).astype('u1')
     assert np.isfinite(depth).all() and (depth>0).all()
     focal=128/np.tan(np.radians(m.cam_fovy[cid])/2);K=np.array([[focal,0,128],[0,focal,128],[0,0,1.]])
     transform=np.eye(4);transform[:3,:3]=rb.T@d.cam_xmat[cid].reshape(3,3)@np.diag([1,-1,-1]);transform[:3,3]=rb.T@(d.cam_xpos[cid]-d.qpos[:3])
     for key,value in [('rgb',rgb),('depth_m',depth),('valid',valid),('K',K),('optical_to_base',transform)]:out['cameras/'+cam+'/'+key][i]=value
    c.write(work/'USAGE.json',usage)
   out.attrs['complete']=True
 finally:renderer.close()
 binding={'complete':True,'first_frame':first,'stop_frame':stop,'rows':stop-first,'shard_sha256':c.sha(work/'shard.h5'),
          'numeric_source':str(numeric),'numeric_source_sha256':c.sha(numeric),'source_episode':str(source),'source_trace_sha256':c.sha(source/'TRACE.h5'),
          'cameras':CAMERAS,'RGBD_hz':25,'size':[256,256],'separate_rgb_depth_passes':True,'production_accepted':False}
 c.write(work/'SHARD_BINDING.json',binding);finish(binding,usage)


def assemble(config_path):
 cfg=c.read(config_path);work=Path(os.environ['CONTINUOUS_JOB_DIR']);root=work/'assembled';(root/'chunks').mkdir(parents=True)
 shards=[Path(path) for path in cfg['shard_jobs']];records=[];cursor=0;paths=None;identity=None
 for j,folder in enumerate(shards):
  binding=c.read(folder/'SHARD_BINDING.json');assert binding['complete'] and binding['shard_sha256']==c.sha(folder/'shard.h5')
  assert binding['first_frame']==cursor,'shard_gap_overlap_or_out_of_order';cursor=binding['stop_frame']
  current=(binding['numeric_source_sha256'],binding['source_trace_sha256'],binding['RGBD_hz'])
  if identity is None:identity=current
  assert current==identity,'mixed_source_shards'
  target=root/'chunks'/f'{j:04d}.h5';os.link(folder/'shard.h5',target)
  with h5py.File(target,'r') as f:
   assert f.attrs['complete'];current_paths=[]
   f.visititems(lambda name,obj:current_paths.append((name,obj.shape[1:],str(obj.dtype))) if isinstance(obj,h5py.Dataset) else None)
   if paths is None:paths=current_paths
   assert paths==current_paths,'shard_schema_mismatch'
  records.append({'relative_path':str(target.relative_to(root)),'rows':binding['rows'],'sha256':binding['shard_sha256']})
 with h5py.File(root/'canonical.h5','w',libver='latest') as out:
  for name,tail,dtype in paths:
   layout=h5py.VirtualLayout(shape=(cursor,*tail),dtype=np.dtype(dtype));start=0
   for record in records:
    count=record['rows'];source=h5py.VirtualSource(record['relative_path'],name,shape=(count,*tail));layout[start:start+count]=source;start+=count
   out.create_virtual_dataset(name,layout)
 # Read every assembled element through HDF5, including both sides of boundaries.
 maximum={}
 with h5py.File(root/'canonical.h5','r') as merged,h5py.File(cfg['reference_canonical'],'r') as reference:
  for name,_,_ in paths:
   actual=merged[name][:];expected=reference[name][:cursor]
   assert actual.shape==expected.shape
   error=float(np.max(abs(actual.astype(float)-expected.astype(float))))
   maximum[name]=error;assert error==0.,name
 binding={'completed':True,'rows':cursor,'chunks':records,'cameras':CAMERAS,'canonical_sha256':c.sha(root/'canonical.h5'),
          'all_shard_fields_exact_to_reference':True,'maximum_field_errors':maximum,'portable_relative_virtual_sources':True,
          'new_render_passes':0,'new_physics_steps':0,'production_accepted':False,'task_learning_verified':False,
          'scope':'Immutable rendering shard/assembly regression using a failed research excerpt.'}
 c.write(root/'BINDING.json',binding);finish(binding)

if __name__=='__main__':{'render':render,'assemble':assemble}[sys.argv[1]](sys.argv[2])
