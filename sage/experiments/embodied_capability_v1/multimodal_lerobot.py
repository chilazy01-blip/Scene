"""Lossless native LeRobot RGB/action chunks, with bound metric-depth sidecars."""
from pathlib import Path
import json
import numpy as np
from .dataset import sha
from .multimodal import MultimodalSequence


def numeric_fields(sequence):
    x=sequence.rows
    result={'observation.state':np.concatenate([x['joint_position'],x['joint_velocity'],x['previous_reference']],axis=1),
            'action':x['action_reference_chunk'].reshape(len(sequence),100),
            'action.ctrl':x['action_ctrl_chunk'].reshape(len(sequence),100),
            'next.observation.state':np.concatenate([x['next_joint_position'],x['next_joint_velocity']],axis=1),
            'source.time':x['timestamp'].reshape(-1,1),
            'source.action_times':x['action_timestamps'],
            'source.action_dt':x['action_dt'],
            'outcome.done':x['done'].astype(np.int64).reshape(-1,1)}
    for name,camera in sequence.cameras.items():
        for field in ['K','optical_to_base']:
            result[f'observation.calibration.{name}.{field}']=camera[field].reshape(len(sequence),-1)
    return result


def export_multimodal(bindings,destination):
    from lerobot.common.datasets.lerobot_dataset import LeRobotDataset
    from decoupled_wbc.data.exporter import TypedLeRobotDataset
    import torch
    destination=Path(destination);assert bindings
    source=MultimodalSequence(bindings[0],purpose='conditional_multimodal_training');fields=numeric_fields(source)
    features={key:dict(dtype=str(value.dtype),shape=(value.shape[1],),names=[f'{key}_{i}' for i in range(value.shape[1])]) for key,value in fields.items()}
    for name,camera in source.cameras.items():
        features['observation.images.'+name]=dict(dtype='image',shape=camera['rgb'].shape[1:],names=['height','width','channels'])
    source_info=dict(schema='conditional-sim-lerobot-rgbd-chunks/v1',scope='simulation_only',purpose='conditional_multimodal_research',source_bindings=bindings,action_layout='reshape row-major100 ->10 future samples x10 native actuator references;100Hz actions,10Hz observations',state_layout='10joint_position +10joint_velocity +10previous_reference',next_state_layout='10joint_position +10joint_velocity at end of chunk',action_names=source.metadata['action_names'],action_units=source.metadata['action_units'],position_units=source.metadata['position_units'],rgb_encoding='lossless PNG embedded in native parquet; Typed reader float32 CHW/255',depth_encoding='exact float32 metric depth plus bool mask retained in bound canonical HDF5 sidecars; not encoded as RGB/video',hardware_validated=False,production_qualified=False)
    if destination.exists():
        assert json.loads((destination/'meta/scene_source.json').read_text())==source_info
        writer=LeRobotDataset(repo_id='local/conditional-stretch-rgb',root=destination,video_backend='pyav')
        writer.episode_buffer=writer.create_episode_buffer()
    else:
        writer=LeRobotDataset.create(repo_id='local/conditional-stretch-rgb',root=destination,fps=10,robot_type='Stretch effective assumed simulation',features=features,use_videos=False,image_writer_threads=0,video_backend='pyav')
        (destination/'meta/scene_source.json').write_text(json.dumps(source_info,indent=2))
    completed=writer.meta.total_episodes;assert completed<=len(bindings)
    for i,binding in enumerate(bindings):
        data=MultimodalSequence(binding,purpose='conditional_multimodal_training');values=numeric_fields(data)
        if i>=completed:
            for j in range(len(data)):
                frame={key:array[j] for key,array in values.items()}
                frame.update({'observation.images.'+name:camera['rgb'][j] for name,camera in data.cameras.items()})
                frame['task']='Pick up the calibration object, carry it 0.12 m, place and release stably.'
                writer.add_frame(frame)
            writer.save_episode()
        # Decode native PNG and typed state/action values using the real official consumer.
        native=TypedLeRobotDataset(repo_id='local/conditional-stretch-rgb',root=destination,episodes=[i],video_backend='pyav');assert len(native)==len(data);cursor=0
        for batch in torch.utils.data.DataLoader(native,batch_size=16,num_workers=0):
            n=len(batch['index'])
            for key,expected in values.items():
                actual=batch[key].numpy().reshape(n,-1);want=expected[cursor:cursor+n];assert actual.dtype==want.dtype and np.array_equal(actual,want),(i,key)
            for name,camera in data.cameras.items():
                tensor=batch['observation.images.'+name];actual=tensor.numpy();expected=camera['rgb'][cursor:cursor+n].transpose(0,3,1,2).astype(np.float32)/255
                assert actual.dtype==np.float32 and np.array_equal(actual,expected),(i,name,'normalized_pixels')
                assert np.array_equal(np.rint(actual*255).astype(np.uint8),camera['rgb'][cursor:cursor+n].transpose(0,3,1,2)),(i,name,'lossless_pixels')
            assert np.all(batch['episode_index'].numpy()==i);assert np.array_equal(batch['frame_index'].numpy(),np.arange(cursor,cursor+n));cursor+=n
        assert cursor==270
        (destination/'EXPORT_PROGRESS.json').write_text(json.dumps(dict(verified_episodes=i+1,planned=len(bindings),native_rows=(i+1)*270),indent=2))
    writer.stop_image_writer()
    # Relative sidecar locations keep the entire parent bundle relocatable.
    import os
    manifest=dict(completed=True,schema=source_info['schema'],episodes=len(bindings),native_rows=len(bindings)*270,rgb_images=len(bindings)*270*len(source.cameras),native_rgb_lossless=True,all_typed_fields_exact=True,depth_sidecars=[dict(path=os.path.relpath(b['path'],destination),sha256=b['sha256'],episode_index=i,rows=270) for i,b in enumerate(bindings)],depth_in_native_parquet=False,depth_available_through_bound_sidecars=True,physics_steps=0,scope='simulation_only',files=[dict(path=str(p.relative_to(destination)),sha256=sha(p)) for p in sorted(destination.rglob('*')) if p.is_file() and p.name!='BINDING.json'])
    (destination/'BINDING.json').write_text(json.dumps(manifest,indent=2));return manifest


class NativeRGBDChunks:
    """Join official LeRobot RGB/action rows with exact bound depth, no privilege."""
    def __init__(self,root,purpose='conditional_multimodal_research'):
        if purpose!='conditional_multimodal_research':raise ValueError('not_qualified_for_hardware_or_production')
        from decoupled_wbc.data.exporter import TypedLeRobotDataset
        self.root=Path(root);self.binding=json.loads((self.root/'BINDING.json').read_text())
        if not self.binding['completed'] or self.binding['scope']!='simulation_only':raise ValueError('unqualified_binding')
        for row in self.binding['files']:
            if sha(self.root/row['path'])!=row['sha256']:raise ValueError('native_file_hash_mismatch')
        self.sidecars={x['episode_index']:x for x in self.binding['depth_sidecars']};assert len(self.sidecars)==self.binding['episodes']
        for row in self.sidecars.values():
            if sha(self.root/row['path'])!=row['sha256']:raise ValueError('depth_sidecar_hash_mismatch')
        self.native=TypedLeRobotDataset(repo_id='local/conditional-stretch-rgb',root=self.root,video_backend='pyav')
    def __len__(self):return len(self.native)
    def __getitem__(self,index):
        import h5py,torch
        row=self.native[index];episode=int(row['episode_index']);frame=int(row['frame_index']);sidecar=self.sidecars[episode];assert 0<=frame<sidecar['rows']
        with h5py.File(self.root/sidecar['path'],'r') as f:
            # source.time remains float64, while standard LeRobot timestamp is float32.
            assert float(row['source.time'])==float(f['trajectory/timestamp'][frame])
            for name in f['cameras']:
                for field in ['depth_m','valid']:
                    row[f'observation.{field}.{name}']=torch.from_numpy(f['cameras/'+name+'/'+field][frame])
        return row
