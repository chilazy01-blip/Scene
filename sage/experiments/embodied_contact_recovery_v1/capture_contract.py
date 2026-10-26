"""Numeric contract for a complete25Hz episode with actual50Hz command samples."""
import numpy as np

def sample_schedule(steps,dt):
 if steps<1 or dt<=0:raise ValueError('empty_or_invalid_trajectory')
 frame_period=int(round(.04/dt));command_period=int(round(.02/dt))
 if not np.isclose(frame_period*dt,.04,rtol=0,atol=1e-12) or not np.isclose(command_period*dt,.02,rtol=0,atol=1e-12):raise ValueError('incommensurate_sampling')
 frames=np.arange(0,steps,frame_period,dtype=np.int64)
 actions=frames[:,None]+np.array([0,command_period],np.int64)[None,:]
 valid=actions<steps
 return frames,actions,valid

def regression():
 for steps,expected_frames,expected_tail in [(1,1,[True,False]),(8,1,[True,False]),(9,1,[True,True]),(16,1,[True,True]),(24,2,[True,False]),(25,2,[True,True]),(83240,5203,[True,False])]:
  f,a,v=sample_schedule(steps,.0025)
  assert len(f)==expected_frames and v[-1].tolist()==expected_tail
  assert np.all(a[v]<steps) and np.array_equal(a[:,0],f)
 f,a,v=sample_schedule(48,.00125);assert len(f)==2 and v[-1].tolist()==[True,False]
 try:sample_schedule(100,.003)
 except ValueError:pass
 else:raise AssertionError('sampling_mismatch_not_rejected')
