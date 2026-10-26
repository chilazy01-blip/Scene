"""A small, explicitly oracle-conditioned state imitation diagnostic.

The task clock and initial/goal geometry are provided; mass and capability are
not learner inputs. This does not establish end-to-end vision or deployment.
"""
import numpy as np


def features(time,position,velocity,context):
    time=np.asarray(time,dtype=np.float64).reshape(-1)
    position=np.asarray(position,dtype=np.float64).reshape(-1,10)
    velocity=np.asarray(velocity,dtype=np.float64).reshape(-1,10)
    context=np.broadcast_to(np.asarray(context,dtype=np.float64), (len(time),3))
    centers=np.linspace(0,27,68);basis=np.exp(-.5*((time[:,None]-centers)/.40)**2)
    # Geometry is centred on the declared reference fixture. Interactions let
    # the same fitted policy represent condition-dependent trajectories.
    geometry=(context-np.array([-.02,-.64,.52]))/np.array([.02,.04,.05])
    geometry=np.column_stack([np.ones(len(time)),geometry])
    temporal=(basis[:,:,None]*geometry[:,None,:]).reshape(len(time),-1)
    q=position/np.array([12,12,1,.5,3,1,3,.04,3,1])
    v=velocity/np.array([6,6,.2,.2,1,1,1,.1,1,1])
    nonlinear=np.column_stack([np.sin(position[:,7]*10),np.cos(position[:,7]*10)])
    return np.column_stack([np.ones(len(time)),temporal,q,v,nonlinear])


class RidgeImitation:
    def __init__(self,mean,scale,weights):
        self.mean,self.scale,self.weights=mean,scale,weights
    @classmethod
    def fit(cls,x,y,regularization=.001):
        mean=x.mean(axis=0);scale=x.std(axis=0);scale[scale<1e-8]=1
        mean[0]=0;scale[0]=1;z=(x-mean)/scale
        penalty=np.eye(z.shape[1])*regularization;penalty[0,0]=0
        weights=np.linalg.solve(z.T@z+penalty,z.T@y)
        return cls(mean,scale,weights)
    def predict(self,x):return ((x-self.mean)/self.scale)@self.weights
    def save(self,path):np.savez_compressed(path,mean=self.mean,scale=self.scale,weights=self.weights)
    @classmethod
    def load(cls,path):
        a=np.load(path,allow_pickle=False);return cls(a['mean'],a['scale'],a['weights'])
