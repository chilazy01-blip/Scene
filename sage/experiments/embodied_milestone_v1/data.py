"""Lossless full-body action chunks and an official LeRobot RGB/depth join."""
from pathlib import Path
import hashlib
import json
import numpy as np


def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def chunks(raw, updates, rows, context):
    n=len(raw['target']);rows=np.asarray(rows,dtype=np.int64)
    if np.any(rows<0) or np.any(rows>=n) or np.any(rows%50):raise ValueError('frame_alignment')
    high=rows[:,None]//10+np.arange(5);low=rows[:,None]+np.arange(50)
    high_valid=high<len(updates);low_valid=low<n
    high_safe=np.minimum(high,len(updates)-1);low_safe=np.minimum(low,n-1)
    commands=np.array([u['packet']['navigate']+[u['packet']['height']]+u['packet']['rpy']+u['packet']['q_reference'] for u in updates],dtype=np.float64)
    qref=np.array([u['packet']['q_reference'] for u in updates],dtype=np.float64)
    previous=qref[np.maximum(rows//10-1,0)].copy();previous[rows==0]=context.nominal
    reference=commands[high_safe].copy();reference[~high_valid]=0
    target=raw['target'][np.minimum(high*10,n-1)].copy();target[~high_valid]=0
    ctrl=raw['ctrl_commands'][low_safe][:,:,context.actuator].copy();ctrl[~low_valid]=0
    return dict(state=np.concatenate([raw['qpos'][rows][:,context.qpos],raw['qvel'][rows][:,context.qvel],previous,raw['qpos'][rows,:7],raw['qvel'][rows,:6]],axis=1),
                action=reference,action_target=target,action_ctrl=ctrl,
                action_valid=high_valid,ctrl_valid=low_valid,time=raw['time'][rows],
                action_time=np.where(high_valid,raw['time'][np.minimum(high*10,n-1)],0.),
                done=(rows+50>=n),physics_row=rows)


def numeric(f):
    result={}
    mapping={'observation.state':'state','action':'action','action.target':'action_target',
             'action.ctrl':'action_ctrl','action.valid':'action_valid','action.ctrl_valid':'ctrl_valid',
             'source.time':'time','source.action_time':'action_time','outcome.done':'done'}
    for public,key in mapping.items():
        value=f['trajectory/'+key][:]
        if value.dtype==bool:value=value.astype(np.int64)
        result[public]=value.reshape(len(value),-1)
    for name in f['cameras']:
        for field in ['K','optical_to_base']:
            value=f['cameras/'+name+'/'+field][:]
            result['observation.calibration.'+name+'.'+field]=value.reshape(len(value),-1)
    return result


class NativeRGBD:
    def __init__(self,root,purpose='training'):
        from decoupled_wbc.data.exporter import TypedLeRobotDataset
        self.root=Path(root);self.binding=json.loads((self.root/'BINDING.json').read_text())
        if purpose not in ('training','inspection'):raise ValueError('purpose')
        if purpose=='training':
            if not self.binding['qualified_development_episode']:raise ValueError('unqualified_episode')
            audit=json.loads((self.root.parent/'DATA_AUDIT.json').read_text())
            if not audit['passed'] or audit['rows']!=self.binding['rows']:raise ValueError('missing_data_audit')
        for entry in self.binding['files']:
            if sha(self.root/entry['path'])!=entry['sha256']:raise ValueError('native_file_hash')
        for entry in self.binding['chunks']:
            if sha(self.root/entry['path'])!=entry['sha256']:raise ValueError('depth_file_hash')
        self.native=TypedLeRobotDataset(repo_id='local/g1-full-body',root=self.root,video_backend='pyav')
        if len(self.native)!=self.binding['rows']:raise ValueError('row_count')

    def __len__(self):return len(self.native)

    def __getitem__(self,index):
        import h5py,torch
        if type(index) is not int or not 0<=index<len(self):raise IndexError(index)
        row=self.native[index]
        entry=next(x for x in self.binding['chunks'] if x['start']<=index<x['stop'])
        with h5py.File(self.root/entry['path'],'r') as f:
            i=index-entry['start']
            if float(row['source.time'])!=float(f['trajectory/time'][i]):raise ValueError('time_alignment')
            for name in f['cameras']:
                for key in ['depth_m','valid']:
                    row['observation.'+key+'.'+name]=torch.from_numpy(f['cameras/'+name+'/'+key][i])
        return row
