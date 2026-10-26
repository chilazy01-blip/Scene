"""Typed installed LeRobot reader with a bound exact metric-depth sidecar."""
from pathlib import Path
import json
import numpy as np
import torch,h5py
from PIL import Image
from lerobot.datasets.lerobot_dataset import LeRobotDataset
from .runtime import digest
DTYPES=dict(float64=torch.float64,float32=torch.float32,int64=torch.int64,int32=torch.int32,uint8=torch.uint8,bool=torch.bool)
class TypedLeRobotDataset(LeRobotDataset):
    def __init__(self,root):
        super().__init__(repo_id='local/native-g1-physical-rgbd',root=root,video_backend='pyav',download_videos=False)
        features=self.features
        def transform(items):
            result={}
            for key,values in items.items():
                kind=features.get(key,{}).get('dtype')
                if kind in ['image','video'] or (values and isinstance(values[0],Image.Image)):
                    result[key]=[torch.from_numpy(np.array(x,copy=True).transpose(2,0,1)).to(torch.float32)/255 for x in values]
                elif values and isinstance(values[0],str):result[key]=values
                else:
                    if kind not in DTYPES:raise ValueError('undeclared_public_dtype:'+str((key,kind)))
                    result[key]=[torch.as_tensor(x,dtype=DTYPES[kind]) for x in values]
            return result
        self.hf_dataset.set_transform(transform)
class RGBDTrainingDataset(torch.utils.data.Dataset):
    def __init__(self,root):
        self.root=Path(root);self.binding=json.loads((self.root/'BINDING.json').read_text())
        assert self.binding['completed'] and self.binding['canonical_independent_audit_passed']
        for name,h in self.binding['export_files'].items():
            if digest(self.root/name)!=h:raise ValueError('export_hash_mismatch:'+name)
        self.sidecar=self.root/self.binding['canonical_relative_path']
        if digest(self.sidecar)!=self.binding['canonical_sha256']:raise ValueError('canonical_hash_mismatch')
        self.native=TypedLeRobotDataset(self.root)
        self.cameras=self.binding['cameras'];assert len(self.native)==self.binding['rows']
    def __len__(self):return len(self.native)
    def __getitem__(self,index):
        row=self.native[index];frame=int(row['frame_index'])
        with h5py.File(self.sidecar,'r') as source:
            assert float(row['source.sensor_time'])==float(source['trajectory/timestamp'][frame])
            for name in self.cameras:
                row['observation.depth_m.'+name]=torch.from_numpy(source['cameras/'+name+'/depth_m'][frame])
                row['observation.depth_valid.'+name]=torch.from_numpy(source['cameras/'+name+'/valid'][frame])
        return row
