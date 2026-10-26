"""Native ranged-row IPM, retaining column duals without requiring a basis.

Full original rows and unscaled residual gates remain the admission authority.
Nonoptimal native solver states may be saved for diagnostics, never admitted.
"""
import time
import numpy as np
from scipy import sparse
from scipy.optimize._highspy import _core as highs_core
from .certified_sided_reduction_r4 import reduce_rows
from sage.experiments.embodied_task_space_v3.globalization_gate import qp_residuals,residual_gate


def solve_lp(cost,A,low,high,seconds,callback=None):
    started=time.monotonic();A=A.tocsr();n=len(cost)
    B,lo,hi,mapping,reduction=reduce_rows(A,low,high)
    scale=np.ones(B.shape[0]);up=np.flatnonzero(np.isfinite(hi));down=np.flatnonzero(np.isfinite(lo))
    C=sparse.vstack([B[up],-B[down]],format="csc");rhs=np.r_[hi[up],-lo[down]]
    if callback:callback(reduction)
    h=highs_core._Highs()
    remaining=seconds-(time.monotonic()-started)
    if remaining<=.1:return None,None,dict(passed=False,status='preprocessing_deadline',reduction=reduction,seconds=time.monotonic()-started)
    options=dict(solver='ipm',run_crossover='off',presolve='on',parallel='off',threads=1,
                 time_limit=remaining,ipm_optimality_tolerance=1e-8,
                 primal_feasibility_tolerance=1e-9,dual_feasibility_tolerance=1e-6,output_flag=True)
    for key,value in options.items():
        if h.setOptionValue(key,value)!=highs_core.HighsStatus.kOk:raise RuntimeError('native_option_rejected:'+key)
    native=lambda v:np.where(np.isposinf(v),highs_core.kHighsInf,np.where(np.isneginf(v),-highs_core.kHighsInf,v))
    lp=highs_core.HighsLp();lp.num_col_=n;lp.num_row_=C.shape[0]
    lp.col_cost_=cost;lp.col_lower_=native(low[-n:]);lp.col_upper_=native(high[-n:])
    lp.row_lower_=np.full(C.shape[0],-highs_core.kHighsInf);lp.row_upper_=rhs
    lp.a_matrix_.num_col_=n;lp.a_matrix_.num_row_=C.shape[0];lp.a_matrix_.format_=highs_core.MatrixFormat.kColwise
    lp.a_matrix_.start_=C.indptr;lp.a_matrix_.index_=C.indices;lp.a_matrix_.value_=C.data
    if h.passModel(lp)==highs_core.HighsStatus.kError:raise RuntimeError('native_model_rejected')
    run_status=h.run();status=h.getModelStatus();info=h.getInfo();solution=h.getSolution()
    optimal=status==highs_core.HighsModelStatus.kOptimal
    result=dict(passed=False,status=h.modelStatusToString(status),status_code=0 if optimal else 4,
                native_model_status=int(status),native_run_status=int(run_status),
                seconds=time.monotonic()-started,iterations=int(info.ipm_iteration_count),
                simplex_iterations=int(info.simplex_iteration_count),reduction=reduction,options=options,
                numerical_backend='proved_sided_reduction_native_ipm_column_duals_r4',
                native_value_valid=bool(solution.value_valid),native_dual_valid=bool(solution.dual_valid),
                native_primal_infeasibility=float(info.max_primal_infeasibility),
                native_dual_infeasibility=float(info.max_dual_infeasibility))
    if not solution.value_valid or not solution.dual_valid:return None,None,result
    primal=np.asarray(solution.col_value);native_dual=np.asarray(solution.row_dual);reduced_dual=np.zeros(B.shape[0])
    np.add.at(reduced_dual,up,-native_dual[:len(up)]);np.add.at(reduced_dual,down,native_dual[len(up):])
    owner=np.where((reduced_dual>=0)[:,None],mapping['upper_owner'],mapping['lower_owner'])
    dual=np.zeros(A.shape[0]);np.add.at(dual,owner[:,0].astype(int),reduced_dual*owner[:,1]);dual[-n:]=-np.asarray(solution.col_dual)
    zero=sparse.csr_matrix((n,n));metrics=qp_residuals(zero,cost,A,low,high,primal,dual);result['before_polish']=metrics
    if not residual_gate(metrics):
        candidate=dual.copy();candidate[-n:]-=cost+A.T@dual
        repaired=qp_residuals(zero,cost,A,low,high,primal,candidate);result['polish_metrics']=repaired
        if residual_gate(repaired):dual,metrics=candidate,repaired
    result.update(passed=bool(optimal and residual_gate(metrics)),residuals=metrics,
                  objective=float(cost@primal),all_original_rows_verified=True)
    return primal,dual,result
