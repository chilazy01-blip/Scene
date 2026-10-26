"""Compact cache built through the official reader; no privileged fields."""
from pathlib import Path
import numpy as np
import torch
import torch.nn.functional as F
from lerobot.datasets.lerobot_dataset import LeRobotDataset
from sage.experiments.embodied_scene_bridge.contracts import read,write,digest

CAMERAS=['workspace','wrist']

def resize_rgb(tensor):
    """Common offline/online path: CHW float [0,1] -> resized uint8 CHW."""
    batch=tensor.ndim==4
    if not batch:tensor=tensor.unsqueeze(0)
    small=F.interpolate(tensor,size=(120,160),mode='bilinear',align_corners=False,antialias=True)
    result=(small.clamp(0,1)*255).round().to(torch.uint8)
    return result if batch else result[0]

def build_cache(dataset_root, destination):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=False)
    dataset=LeRobotDataset('local/scene-abc',root=dataset_root,video_backend='pyav')
    n=len(dataset)
    images=np.lib.format.open_memmap(destination/'images.npy',mode='w+',dtype='u1',shape=(n,2,3,120,160))
    state=np.zeros((n,18),dtype='f4');action=np.zeros((n,8),dtype='f4');episode=np.zeros(n,dtype='i8')
    for i in range(n):
        row=dataset[i]
        state[i]=row['observation.state'].numpy();action[i]=row['action'].numpy();episode[i]=int(row['episode_index'])
        for j,cam in enumerate(CAMERAS):images[i,j]=resize_rgb(row['observation.images.'+cam]).numpy()
        if i%500==0:print(dict(cache=str(destination),row=i,total=n),flush=True)
    images.flush()
    for name,value in [('state',state),('action',action),('episode',episode)]:np.save(destination/(name+'.npy'),value)
    ends=np.zeros(n,dtype='i8')
    for ep in np.unique(episode):
        idx=np.flatnonzero(episode==ep)
        assert np.array_equal(idx,np.arange(idx[0],idx[-1]+1))
        ends[idx]=idx[-1]+1
    np.save(destination/'episode_end.npy',ends)
    write(destination/'CACHE.json',dict(rows=n,episodes=int(len(np.unique(episode))),
        source_dataset=str(dataset_root),source_info_sha256=digest(Path(dataset_root)/'meta/info.json'),
        official_reader=True,features=['RGB_workspace','RGB_wrist','robot_state','action'],
        resize='bilinear 160x120 antialias, quantize uint8; same online function',
        files={p.name:digest(p) for p in destination.glob('*.npy')}))

class CachedSamples:
    def __init__(self, root, chunk_size):
        self.root=Path(root);self.chunk_size=chunk_size
        self.arrays={name:np.load(self.root/(name+'.npy'),mmap_mode='r') for name in ['images','state','action','episode_end']}
        self.length=len(self.arrays['state'])

    def batch(self, indices, zero_images=False):
        indices=np.asarray(indices,dtype='i8')
        raw=indices[:,None]+np.arange(self.chunk_size)[None,:]
        end=self.arrays['episode_end'][indices,None]
        padded=raw>=end;chosen=np.minimum(raw,end-1)
        result={'observation.state':torch.from_numpy(self.arrays['state'][indices].copy()),
            'action':torch.from_numpy(self.arrays['action'][chosen].copy()),
            'action_is_pad':torch.from_numpy(padded)}
        for j,cam in enumerate(CAMERAS):
            im=torch.from_numpy(self.arrays['images'][indices,j].copy()).float()/255.
            if zero_images:im.zero_()
            result['observation.images.'+cam]=im
        return result
