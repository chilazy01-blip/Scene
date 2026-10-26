"""Numerical and nonlinear step gates. These do not grant task qualification."""
import numpy as np


def qp_residuals(H, f, A, low, high, primal, dual):
    """Recompute residuals on ORIGINAL full rows, independent of solver status.

    Assumes the caller supplies a symmetric convex H (e.g. J.T @ J + ridge I).
    This function reports residuals; it does not prove H is positive semidefinite.
    """
    x=np.asarray(primal,float); y=np.asarray(dual,float)
    f=np.asarray(f,float); low=np.asarray(low,float); high=np.asarray(high,float)
    if not all(np.isfinite(v).all() for v in [x,y,f]):
        raise ValueError('nonfinite_primal_dual_or_gradient')
    if np.isnan(low).any() or np.isnan(high).any() or np.any(low>high):
        raise ValueError('invalid_bounds')
    ax=np.asarray(A@x).ravel(); hx=np.asarray(H@x).ravel(); aty=np.asarray(A.T@y).ravel()
    if ax.shape!=y.shape or low.shape!=ax.shape or high.shape!=ax.shape or hx.shape!=f.shape or x.shape!=f.shape:
        raise ValueError('inconsistent_shapes')
    primal_error=max(0.,float(np.max(low-ax,initial=0)),float(np.max(ax-high,initial=0)))
    positive=y>0; negative=y<0
    wrong_sign=np.r_[y[positive & ~np.isfinite(high)],-y[negative & ~np.isfinite(low)]]
    dual_error=float(np.max(wrong_sign,initial=0))
    up=positive & np.isfinite(high); down=negative & np.isfinite(low)
    comp=np.r_[y[up]*(high[up]-ax[up]),-y[down]*(ax[down]-low[down])]
    complementarity=float(np.max(abs(comp),initial=0))
    stationarity=float(np.max(abs(hx+f+aty),initial=0))
    scale=max(1.,float(np.max(abs(hx),initial=0)),float(np.max(abs(f),initial=0)),float(np.max(abs(aty),initial=0)))
    return dict(primal_inf=primal_error,stationarity_inf=stationarity,scaled_stationarity_inf=stationarity/scale,dual_sign_inf=dual_error,complementarity_inf=complementarity,full_rows=int(len(low)))


def residual_gate(metrics, primal_tol=1e-8, dual_tol=1e-6):
    """An LP primal repair alone cannot satisfy the stationarity gate."""
    return bool(metrics['primal_inf']<=primal_tol and metrics['scaled_stationarity_inf']<=dual_tol and metrics['dual_sign_inf']<=dual_tol and metrics['complementarity_inf']<=dual_tol)


def accept_geometry_step(before, after, hard_residual, predicted_reduction, min_ratio=.1):
    """Accept only full-audit violation reduction with original hard rows intact.

    before/after must contain the same nonnegative, gate-normalized violations
    from ALL current states, endpoints, and exact stopping configurations. This
    gate does not produce these measurements or replace the original audit.
    """
    before=np.asarray(before,float);after=np.asarray(after,float)
    if before.shape!=after.shape or before.ndim!=1 or not np.isfinite(before).all() or not np.isfinite(after).all() or np.any(before<0) or np.any(after<0):
        raise ValueError('invalid_or_incomparable_violation_vectors')
    if not np.isfinite(hard_residual) or hard_residual>1e-8:
        return dict(accepted=False,reason='original_hard_rows_failed')
    initial=float(before@before);final=float(after@after);actual=initial-final
    if final==0:
        return dict(accepted=True,reason='zero_measured_violation_requires_independent_task_audit',actual_reduction=actual)
    if not np.isfinite(predicted_reduction) or predicted_reduction<=0 or actual<=0:
        return dict(accepted=False,reason='no_actual_or_predicted_improvement',actual_reduction=actual)
    ratio=actual/predicted_reduction
    return dict(accepted=bool(ratio>=min_ratio),reason='sufficient_actual_improvement' if ratio>=min_ratio else 'model_prediction_not_confirmed',actual_reduction=actual,ratio=ratio)


def available_solver_time(deadline, now, reserve_seconds):
    """Use before every costly operation; native work also needs a process timer."""
    if reserve_seconds<0:raise ValueError('negative_reserve')
    remaining=deadline-now-reserve_seconds
    if remaining<=0:raise TimeoutError('case_deadline_reserve')
    return remaining
