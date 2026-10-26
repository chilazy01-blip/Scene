"""Independent checks of a linear certificate in original problem units."""
import numpy as np


def certify(cost, matrix, low, high, primal, dual, solver_success):
    rows, columns = matrix.shape
    cost = np.asarray(cost)
    low, high = np.asarray(low), np.asarray(high)
    primal, dual = np.asarray(primal), np.asarray(dual)
    if (cost.shape != (columns,) or primal.shape != (columns,)
            or low.shape != (rows,) or high.shape != (rows,)
            or dual.shape != (rows,)):
        raise ValueError('original_certificate_shape')
    if (not np.isfinite(cost).all() or not np.isfinite(matrix.data).all()
            or not np.isfinite(primal).all() or not np.isfinite(dual).all()
            or np.isnan(low).any() or np.isnan(high).any()
            or np.isposinf(low).any() or np.isneginf(high).any()
            or np.any(low > high)):
        raise ValueError('original_certificate_nonfinite_or_invalid_bounds')
    values = matrix @ primal
    adjoint = matrix.T @ dual
    primal_error = max(0., float(np.max(low - values, initial=0.)),
                       float(np.max(values - high, initial=0.)))
    stationarity = float(np.max(np.abs(cost + adjoint), initial=0.))
    scale = max(1., float(np.max(np.abs(cost), initial=0.)),
                float(np.max(np.abs(adjoint), initial=0.)))
    positive, negative = dual > 0, dual < 0
    upper = positive & np.isfinite(high)
    lower = negative & np.isfinite(low)
    wrong_sign = max(float(np.max(dual[positive & ~np.isfinite(high)], initial=0.)),
                     float(np.max(-dual[negative & ~np.isfinite(low)], initial=0.)))
    complementarity = max(
        float(np.max(np.abs(dual[upper] * (high[upper] - values[upper])), initial=0.)),
        float(np.max(np.abs(dual[lower] * (values[lower] - low[lower])), initial=0.)))
    metrics = dict(primal_inf=primal_error, scaled_stationarity_inf=stationarity / scale,
                   stationarity_inf=stationarity, dual_sign_inf=wrong_sign,
                   complementarity_inf=complementarity)
    finite = all(np.isfinite(value) for value in metrics.values())
    passed = bool(solver_success and finite and primal_error <= 1e-8
                  and stationarity / scale <= 1e-6 and wrong_sign <= 1e-6
                  and complementarity <= 1e-6)
    # Informational aggregate gap; the frozen gate uses maximum residuals.
    objective = float(cost @ primal)
    dual_objective = float(-dual[upper] @ high[upper] - dual[lower] @ low[lower])
    return dict(passed=passed, original_rows=rows, variables=columns,
                objective=objective, dual_objective=dual_objective,
                duality_gap=objective - dual_objective, **metrics)
