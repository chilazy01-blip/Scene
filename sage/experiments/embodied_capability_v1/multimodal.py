"""Time-aligned RGB-D/action chunks reconstructed from executed states."""
from pathlib import Path
import json
import numpy as np
import h5py
from .dataset import ProprioTrajectory,sha


def aligned_chunks(binding,physics_rows):
    source=ProprioTrajectory(binding);rows=np.asarray(physics_rows,dtype=np.int64)
    if np.any(rows%50):raise ValueError('visual_grid_must_be_10Hz')
    idx=rows//5;chunk=idx[:,None]+np.arange(10)[None,:]
    if chunk.max()>=len(source):raise ValueError('incomplete_action_chunk')
    x=source.rows
    return dict(timestamp=rows*.002,next_timestamp=(rows+50)*.002,joint_position=x['joint_position'][idx],joint_velocity=x['joint_velocity'][idx],previous_reference=x['previous_reference'][idx],action_reference_chunk=x['action_reference'][chunk],action_ctrl_chunk=x['action_ctrl'][chunk],action_timestamps=x['timestamp'][chunk],action_dt=x['dt'][chunk],next_joint_position=x['next_joint_position'][chunk[:,-1]],next_joint_velocity=x['next_joint_velocity'][chunk[:,-1]],done=x['done'][chunk[:,-1]])


class MultimodalSequence:
    def __init__(self,binding,purpose='inspection'):
        if purpose not in ('inspection','conditional_multimodal_training'):raise ValueError('unsupported_or_unqualified_purpose')
        if sha(binding['path'])!=binding['sha256']:raise ValueError('dataset_hash_mismatch')
        with h5py.File(binding['path'],'r') as f:
            self.metadata=json.loads(f.attrs['metadata'])
            if self.metadata!=binding['metadata']:raise ValueError('metadata_mismatch')
            if purpose=='conditional_multimodal_training' and not self.metadata['complete_episode']:raise ValueError('sparse_profile_is_not_full_episode')
            if purpose=='conditional_multimodal_training' and self.metadata['source_kind'] not in ('complete_task_development','complete_task_household'):raise ValueError('heldout_not_training')
            self.rows={k:f['trajectory'][k][:] for k in f['trajectory']}
            self.cameras={name:{key:f['cameras'][name][key][:] for key in ['rgb','depth_m','valid','K','optical_to_base']} for name in f['cameras']}
    def __len__(self):return self.metadata['frames']
    def __getitem__(self,i):
        return dict(trajectory={k:v[i].copy() for k,v in self.rows.items()},cameras={name:{k:v[i].copy() for k,v in fields.items()} for name,fields in self.cameras.items()})
