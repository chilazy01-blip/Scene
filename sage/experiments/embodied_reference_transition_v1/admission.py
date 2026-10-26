"""At command emission q cannot jump: new tracking error is e - delta_reference.

This checks a declared empirical domain before sending a command. It is not a
prediction or proof of future physical tracking, contact safety, or task success.
"""
import numpy as np

class ReferenceTransitionRejected(ValueError):
    pass

class TrackingDomain:
    def __init__(self,lower,upper,active,names,tolerance=1e-9):
        self.lower=np.asarray(lower,dtype=np.float64);self.upper=np.asarray(upper,dtype=np.float64);self.active=np.asarray(active,dtype=bool);self.names=tuple(names);self.tolerance=float(tolerance)
        if any(x.shape!=(43,) for x in [self.lower,self.upper,self.active]) or len(self.names)!=43:raise ValueError('domain_shape')
        if not np.isfinite(self.lower).all() or not np.isfinite(self.upper).all() or np.any(self.lower>self.upper) or not 0<=self.tolerance<=1e-9:raise ValueError('domain_bounds')
    def assess(self,observed,previous_reference,proposed_reference):
        arrays=[np.asarray(v,dtype=np.float64) for v in [observed,previous_reference,proposed_reference]]
        if any(v.shape!=(43,) or not np.isfinite(v).all() for v in arrays):raise ValueError('reference_shape_finite')
        q,previous,proposed=arrays;current=q-previous;emitted=q-proposed
        def violations(error):
            excess=np.maximum(np.maximum(self.lower-error,error-self.upper),0.)
            return [dict(index=int(i),name=self.names[i],error_rad=float(error[i]),lower_rad=float(self.lower[i]),upper_rad=float(self.upper[i]),excess_rad=float(excess[i])) for i in np.where(self.active & (excess>self.tolerance))[0]]
        before=violations(current);after=violations(emitted)
        return dict(current_inside=not before,emission_inside=not after,current_violations=before,emission_violations=after,reference_delta_rad=(proposed-previous).tolist(),future_tracking_certified=False)
    def require(self,observed,previous_reference,proposed_reference):
        result=self.assess(observed,previous_reference,proposed_reference)
        if not result['current_inside']:raise ReferenceTransitionRejected('observed_tracking_out_of_domain')
        if not result['emission_inside']:raise ReferenceTransitionRejected('reference_jump_out_of_domain')
        return result
