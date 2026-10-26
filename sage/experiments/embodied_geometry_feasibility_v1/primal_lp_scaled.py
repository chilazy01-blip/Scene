"""Read a native HiGHS primal candidate only after independent full checks.

Unlike optimization success, primal feasibility is sufficient for a phase-I
search step. Non-optimal status is preserved and never implies infeasibility.
"""
from types import SimpleNamespace
import numpy as np
from scipy import sparse
from scipy.optimize._highspy import _core as h


def linprog(c,A_ub,b_ub,bounds,method=None,options=None):
    del method
    A=sparse.csc_matrix(A_ub);original_b=np.asarray(b_ub);original_bounds=np.asarray(bounds);b=1000*original_b;bounds=1000*original_bounds
    lp=h.HighsLp();lp.num_col_=A.shape[1];lp.num_row_=A.shape[0]
    lp.a_matrix_.num_col_=A.shape[1];lp.a_matrix_.num_row_=A.shape[0]
    lp.a_matrix_.format_=h.MatrixFormat.kColwise
    lp.a_matrix_.start_=A.indptr;lp.a_matrix_.index_=A.indices;lp.a_matrix_.value_=A.data
    lp.col_cost_=c;lp.col_lower_=bounds[:,0];lp.col_upper_=bounds[:,1]
    lp.row_lower_=np.full(len(b),-h.kHighsInf);lp.row_upper_=b
    solver=h._Highs();opt=h.HighsOptions();opt.output_flag=False;opt.log_to_console=False;opt.solver='ipm';opt.run_crossover='off'
    for key,value in (options or {}).items():
        if key=='presolve':value='on' if value else 'off'
        setattr(opt,key,value)
    assert solver.passOptions(opt)==h.HighsStatus.kOk
    model_status=solver.passModel(lp)
    assert model_status!=h.HighsStatus.kError
    solver.run();status=solver.getModelStatus();info=solver.getInfo();solution=solver.getSolution()
    optimal=status==h.HighsModelStatus.kOptimal
    record=dict(status=0 if optimal else int(status),message=solver.modelStatusToString(status),
                nit=int(info.ipm_iteration_count+info.simplex_iteration_count),crossover_nit=int(info.crossover_iteration_count),
                success=optimal,optimal=optimal,feasible=False,x=None,fun=None,
                native_primal_status=solver.solutionStatusToString(info.primal_solution_status),
                model_loading_status=str(model_status),solution_value_valid=bool(solution.value_valid),full_residual=None)
    if solution.value_valid:
        x=np.asarray(solution.col_value)/1000
        if x.shape==(len(c),) and np.isfinite(x).all():
            violation=max(0.,float(np.max(A@x-original_b,initial=0)),float(np.max(original_bounds[:,0]-x)),float(np.max(x-original_bounds[:,1])))
            record['full_residual']=violation
            if violation<=2e-8:record.update(feasible=True,x=x,fun=float(np.dot(c,x)))
    return SimpleNamespace(**record)
