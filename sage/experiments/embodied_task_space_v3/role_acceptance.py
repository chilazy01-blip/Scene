"""Prospective role-preserving acceptance gate; not applied to the closed method."""
import numpy as np


def decide(before_contacts,after_contacts,before_passed,after_passed,before_merit,after_merit,hard_residual):
    old=np.asarray(before_contacts,float);new=np.asarray(after_contacts,float)
    passed=np.asarray(before_passed,bool);candidate=np.asarray(after_passed,bool)
    if old.shape!=new.shape or passed.shape!=candidate.shape or old.ndim!=1 or passed.ndim!=1 or not np.isfinite(old).all() or not np.isfinite(new).all() or np.any(old<0) or np.any(new<0):raise ValueError('invalid_or_unaligned_metrics')
    if not all(np.isfinite(v) for v in [before_merit,after_merit,hard_residual]) or hard_residual>1e-8:return dict(accepted=False,reason='original_hard_rows_failed')
    regressed=np.flatnonzero(new>old+1e-12);lost=np.flatnonzero(passed&~candidate)
    if len(regressed) or len(lost):return dict(accepted=False,reason='contact_or_previously_passed_stage_regression',regressed_contact_components=regressed.tolist(),lost_passed_stages=lost.tolist())
    return dict(accepted=bool(after_merit<before_merit or candidate.all()),reason='protected_components_preserved_and_merit_improved' if after_merit<before_merit or candidate.all() else 'no_measured_progress')
