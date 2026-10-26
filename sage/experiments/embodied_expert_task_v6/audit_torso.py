"""Independent torso goal/history checks using the declared Z-X-Y waist chain."""
import numpy as np
from scipy.spatial.transform import Rotation

def torso_rpy(goal):
    return Rotation.from_euler('ZXY',np.asarray(goal)[18:21]).as_euler('xyz').astype(np.float32)

def source_intent_error(goals,phases,inputs):
    error=0.
    for goal,phase in zip(goals,phases):
        phase=min(float(phase),920.);i=int(phase);j=min(i+1,920);expected=(1-(phase-i))*inputs['upper'][i,:3]+(phase-i)*inputs['upper'][j,:3]
        error=max(error,float(np.max(np.abs(goal[18:21]-expected))))
    return error

def chronological_rpy_error(goals,nn,dim,initial):
    expected=np.vstack([np.asarray(initial,dtype=np.float32),np.asarray([torso_rpy(goal) for goal in goals[:-1]])]);actual=nn.reshape(len(goals),-1)[:,-dim+4:-dim+7]
    return float(np.max(np.abs(actual-expected)))
