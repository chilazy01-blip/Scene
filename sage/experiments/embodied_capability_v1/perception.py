"""A fixed, color-specific RGB-D center baseline; no policy or hardware claim."""
import numpy as np


def blue_surface_features(rgb,depth,valid,k,optical_to_base):
    c=np.asarray(rgb,dtype=np.int16)
    mask=np.asarray(valid,dtype=bool)&(c[:,:,2]>=64)&(c[:,:,2]-c[:,:,0]>=40)&(c[:,:,2]-c[:,:,1]>=30)
    y,x=np.nonzero(mask)
    if len(x)<20:return None,int(len(x))
    z=depth[y,x].astype(np.float64)
    points=np.column_stack(((x-k[0,2])*z/k[0,0],(y-k[1,2])*z/k[1,1],z))
    points=points@optical_to_base[:3,:3].T+optical_to_base[:3,3]
    return np.concatenate([points.mean(axis=0),points.min(axis=0),points.max(axis=0)]),int(len(x))


class SurfaceCenterRidge:
    def __init__(self,mean,scale,weights,offset):
        self.mean,self.scale,self.weights,self.offset=mean,scale,weights,offset
    @classmethod
    def fit(cls,features,targets):
        x=np.asarray(features);y=np.asarray(targets);mean=x.mean(axis=0);scale=x.std(axis=0);scale[scale<1e-8]=1;z=np.column_stack((np.ones(len(x)),(x-mean)/scale));offsets=y-x[:,:3];penalty=np.eye(10);penalty[0,0]=0
        return cls(mean,scale,np.linalg.solve(z.T@z+penalty,z.T@offsets),offsets.mean(axis=0))
    def predict(self,features):
        x=np.asarray(features);z=np.column_stack((np.ones(len(x)),(x-self.mean)/self.scale));return x[:,:3]+z@self.weights
    def baseline(self,features):return np.asarray(features)[:,:3]+self.offset
    def save(self,path):np.savez_compressed(path,mean=self.mean,scale=self.scale,weights=self.weights,offset=self.offset)
