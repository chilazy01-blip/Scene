"""Isolated pinned conic LP backend with SciPy-shaped primal/dual results."""
from pathlib import Path
from types import SimpleNamespace
import hashlib,json,sys,time
import numpy as np
from scipy import sparse


def linprog(cost,A_ub,b_ub,bounds,method=None,options=None):
    root=Path('/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/feasibility_guard_v4')
    ready=json.loads((root/'dependencies/CLARABEL_READY.json').read_text())
    assert ready['passed'] and ready['version']=='0.11.1'
    if 'clarabel' not in sys.modules:
        for p,h in ready['files'].items():assert hashlib.sha256(Path(p).read_bytes()).hexdigest()==h,p
        sys.path.insert(0,str(root/'dependencies/clarabel_0_11_1'))
    import clarabel
    assert clarabel.__version__=='0.11.1'
    n=len(cost);lb,ub=np.asarray(bounds).T;lower=np.flatnonzero(np.isfinite(lb));upper=np.flatnonzero(np.isfinite(ub));identity=sparse.eye(n,format='csc')
    C=sparse.vstack([A_ub,identity[upper],-identity[lower]],format='csc');rhs=np.r_[b_ub,ub[upper],-lb[lower]]
    settings=clarabel.DefaultSettings();settings.verbose=False;settings.time_limit=float(options['time_limit'])
    settings.max_iter=200;settings.tol_feas=1e-10;settings.tol_gap_abs=1e-9;settings.tol_gap_rel=1e-10
    # Contact hierarchy leaves margins around 1e-8. Default KKT shifts (1e-8
    # static, 2e-7 dynamic) exceed those margins and previous duals stalled.
    # Reduce only the linear-system regularization; original LP is unchanged.
    settings.static_regularization_eps=1e-12
    settings.dynamic_regularization_eps=1e-15
    settings.dynamic_regularization_delta=1e-11
    settings.iterative_refinement_abstol=1e-13
    settings.iterative_refinement_reltol=1e-13
    settings.iterative_refinement_max_iter=30
    if hasattr(settings,'max_threads'):settings.max_threads=1
    started=time.monotonic();solver=clarabel.DefaultSolver(sparse.csc_matrix((n,n)),cost,C,rhs,[clarabel.NonnegativeConeT(len(rhs))],settings);answer=solver.solve()
    optimal=answer.status==clarabel.SolverStatus.Solved
    x=np.asarray(answer.x);z=np.asarray(answer.z);m=A_ub.shape[0]
    lo_dual=np.zeros(n);hi_dual=np.zeros(n);hi_dual[upper]=-z[m:m+len(upper)];lo_dual[lower]=z[m+len(upper):]
    return SimpleNamespace(x=x,status=0 if optimal else 4,success=optimal,message=str(answer.status),nit=int(answer.iterations),
             ineqlin=SimpleNamespace(marginals=-z[:m]),lower=SimpleNamespace(marginals=lo_dual),upper=SimpleNamespace(marginals=hi_dual),
             elapsed_seconds=time.monotonic()-started,diagnostics={k:float(getattr(answer,k)) for k in ['r_prim','r_dual','obj_val','obj_val_dual'] if hasattr(answer,k)})
