"""One atomic body-token/dual-hand frame, including source and command timing."""
from __future__ import annotations
from dataclasses import dataclass
import math
import numpy as np
from .contract import finite,reorder,OfficialContract

@dataclass(frozen=True)
class CommandFrame:
    token: np.ndarray
    left: np.ndarray
    right: np.ndarray
    frame_index: int
    observation_time_s: float
    source: str

    def __post_init__(self):
        object.__setattr__(self,'token',finite(self.token,(64,),'motion token',np.float32))
        object.__setattr__(self,'left',finite(self.left,(7,),'left hand'))
        object.__setattr__(self,'right',finite(self.right,(7,),'right hand'))
        if isinstance(self.frame_index,bool) or not isinstance(self.frame_index,(int,np.integer)) or not 0<=self.frame_index<=np.iinfo(np.int64).max:raise ValueError('frame index must fit nonnegative int64')
        if not math.isfinite(self.observation_time_s) or not self.source:raise ValueError('timestamp and source required')

    @classmethod
    def from_task(cls,contract,token,hand_names,hand_target,**metadata):
        ordered=reorder(hand_target,hand_names,contract.hand_names)
        return cls(token,ordered[:7],ordered[7:],**metadata)

    def native_hands(self,contract,native_names):return reorder(np.r_[self.left,self.right],contract.hand_names,native_names)

    def record(self):
        return dict(frame_index=int(self.frame_index),observation_time_s=float(self.observation_time_s),source=self.source,motion_token=self.token.tolist(),left_hand_joints=self.left.tolist(),right_hand_joints=self.right.tolist())

def action_field(action,key):
    keys=[n for n in (key,'action.'+key) if n in action]
    if len(keys)!=1:raise ValueError(f'exactly one {key} field is required')
    return action[keys[0]]

@dataclass(frozen=True)
class ActionChunk:
    tokens: np.ndarray
    left: np.ndarray
    right: np.ndarray
    observation_time_s: float
    source: str
    publish_hz: float=50.

    @classmethod
    def from_policy(cls,action,observation_time_s,source='gr00t'):
        values=[]
        for name,width in [('motion_token',64),('left_hand_joints',7),('right_hand_joints',7)]:
            a=np.asarray(action_field(action,name),dtype=np.float32)
            if a.ndim==3 and a.shape[0]==1:a=a[0]
            if a.ndim==1:a=a[None,:]
            if a.ndim!=2 or a.shape[1]!=width or not a.shape[0] or not np.isfinite(a).all():raise ValueError(f'invalid action horizon: {name}')
            a=a.copy();a.setflags(write=False);values.append(a)
        if len({len(x) for x in values})!=1:raise ValueError('body and hand horizons differ')
        if np.max(np.abs(values[0]))>1.25:raise ValueError('token exceeds official VLA acceptance bound1.25')
        if not math.isfinite(observation_time_s):raise ValueError('invalid observation time')
        return cls(*values,float(observation_time_s),source)

    def sample(self,now_s,frame_index):
        if not math.isfinite(now_s) or now_s<self.observation_time_s:raise ValueError('invalid action time')
        # Same nearest-tick latency compensation as the official inference utility.
        index=int(np.round((now_s-self.observation_time_s)*self.publish_hz))
        if index>=len(self.tokens):raise ValueError('action horizon exhausted; fresh inference required')
        return CommandFrame(self.tokens[index],self.left[index],self.right[index],frame_index,now_s,self.source)

class FrameLatch:
    """Reject stale/out-of-order commands while retaining the last valid grip."""
    def __init__(self,max_age_s=.1):
        if not math.isfinite(max_age_s) or max_age_s<=0:raise ValueError('invalid maximum age')
        self.max_age_s=max_age_s;self.current=None
    def accept(self,frame,now_s):
        if not math.isfinite(now_s) or not 0<=now_s-frame.observation_time_s<=self.max_age_s:raise ValueError('stale or future command')
        if self.current is not None and frame.frame_index<=self.current.frame_index:raise ValueError('out-of-order command')
        self.current=frame
        return frame
