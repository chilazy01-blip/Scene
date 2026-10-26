"""Causal interpolation of retained leg position requests over one20ms period."""
import numpy as np
class LegInterpolation:
 def __init__(self,leg_indices,substeps=8):
  self.ids=np.asarray(leg_indices,int);self.substeps=int(substeps);self.requested=None;self.start=None;self.current=None;self.tick=0
 def apply(self,target):
  result=np.asarray(target).copy();values=result[self.ids]
  if self.requested is None:
   self.requested=values.copy();self.start=values.copy();self.current=values.copy();self.tick=self.substeps
  elif not np.array_equal(values,self.requested):
   self.start=self.current.copy();self.requested=values.copy();self.tick=0
  self.tick=min(self.substeps,self.tick+1);alpha=self.tick/self.substeps
  self.current=(1-alpha)*self.start+alpha*self.requested;result[self.ids]=self.current
  return result
