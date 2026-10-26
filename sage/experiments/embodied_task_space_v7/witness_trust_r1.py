"""Prepared trust update: let newly discovered contacts enter the next model.

No trust enlargement beyond the original cap, no extra iterations and no
change to complete-path acceptance. A retained radius grants no path success.
"""
import math
from numbers import Integral

def update_radius(current, accepted, scale, new_witnesses, maximum, minimum):
    if not all(math.isfinite(x) for x in [current,maximum,minimum]) or not 0<minimum<=current<=maximum:
        raise ValueError('invalid_trust_domain')
    if not isinstance(new_witnesses,Integral) or isinstance(new_witnesses,bool) or new_witnesses<0:
        raise ValueError('invalid_witness_growth')
    if type(accepted) is not bool:raise ValueError('invalid_acceptance')
    if accepted and scale not in (1.,.5,.25,.125):raise ValueError('invalid_accepted_scale')
    if new_witnesses:
        return current,'rebuild_with_new_contact_witnesses_before_shrinking'
    if accepted:
        return (min(maximum,current*1.2),'accepted_full_step') if scale==1. else (max(minimum,current*max(scale,.25)),'accepted_partial_step_without_new_witnesses')
    return current*.5,'rejected_without_new_witnesses'
