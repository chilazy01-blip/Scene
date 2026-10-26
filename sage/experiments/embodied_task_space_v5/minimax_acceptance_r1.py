"""Whole-path minimax restoration; final robot gates are never relaxed."""
import numpy as np

def measures(value):
    raw=np.asarray(value['raw'],float);ends=np.asarray(value['ends'],float)
    return max(float(np.max(raw,initial=0)),float(np.max(ends,initial=0))),float(np.sum(raw*raw)/raw.shape[1]+np.sum(ends*ends)/30.)

def accept_step(before,after,hard_residual,tolerance=1e-10):
    old=np.asarray(before['raw'],float);new=np.asarray(after['raw'],float)
    a=np.asarray(before['ends'],float);b=np.asarray(after['ends'],float)
    if old.shape!=new.shape or old.ndim!=3 or old.shape[0]!=2 or old.shape[2]!=5:
        raise ValueError('unaligned_current_and_stopping_contact_fields')
    if a.shape!=b.shape or a.ndim!=2 or a.shape[1]!=2:
        raise ValueError('unaligned_endpoint_measurements')
    if any(not np.isfinite(v).all() or np.any(v<0) for v in [old,new,a,b]):
        raise ValueError('invalid_contact_or_endpoint_measurements')
    previous=before['meta']['phases'];candidate=after['meta']['phases']
    if [p['stage'] for p in previous]!=[p['stage'] for p in candidate] or len(previous)!=len(a):
        raise ValueError('phase_identity_changed')
    if not np.isfinite(hard_residual) or hard_residual>1e-8:
        return dict(accepted=False,reason='original_hard_rows_failed')
    newly_unsafe=np.argwhere((old<=tolerance)&(new>tolerance))
    lost=[p['stage'] for p,q in zip(previous,candidate) if p['passed'] and not q['passed']]
    if len(newly_unsafe) or lost:
        return dict(accepted=False,reason='qualified_contact_or_phase_regression',newly_unsafe_components=len(newly_unsafe),examples=newly_unsafe[:10].tolist(),lost_phases=lost)
    old_worst,old_merit=measures(before);new_worst,new_merit=measures(after)
    reduction=old_worst-new_worst;secondary=old_merit-new_merit
    accepted=bool(after['meta']['passed'] or reduction>tolerance or (reduction>=-tolerance and secondary>tolerance))
    return dict(accepted=accepted,reason='minimax_feasibility_progress' if accepted else 'no_minimax_progress',
        maximum_violation_before=old_worst,maximum_violation_after=new_worst,maximum_violation_reduction=reduction,
        secondary_merit_reduction=secondary,newly_unsafe_components=0,lost_phases=[],
        previously_failed_contact_tradeoffs_permitted=True)
