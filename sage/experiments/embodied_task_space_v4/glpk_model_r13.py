"""Isolated GLPK ranged LP with persistent basis and bounded exact fallback."""
from pathlib import Path
import hashlib,json,sys,time
import numpy as np
root=Path('/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/feasibility_guard_v4')
ready=json.loads((root/'dependencies/GLPK_READY.json').read_text())
assert ready['passed'] and ready['version']=='5.0.13'
for p,h in ready['files'].items():assert hashlib.sha256(Path(p).read_bytes()).hexdigest()==h,p
sys.path.insert(0,str(root/'dependencies/swiglpk_5_0_13'))
import swiglpk as g
assert g.glp_version()=='5.0'

def bound(l,u):
    if np.isfinite(l) and np.isfinite(u):return (g.GLP_FX if l==u else g.GLP_DB,float(l),float(u))
    if np.isfinite(l):return g.GLP_LO,float(l),0.
    if np.isfinite(u):return g.GLP_UP,0.,float(u)
    return g.GLP_FR,0.,0.

class Model:
    def __init__(self,cost,lb,ub):
        self.p=g.glp_create_prob();self.n=len(cost);self.m=0
        g.glp_set_obj_dir(self.p,g.GLP_MIN);g.glp_add_cols(self.p,self.n)
        for j in range(self.n):
            g.glp_set_col_bnds(self.p,j+1,*bound(lb[j],ub[j]));g.glp_set_obj_coef(self.p,j+1,float(cost[j]))
    def add(self,C,lo,hi):
        C=C.tocsr();C.sum_duplicates();C.eliminate_zeros();C.sort_indices();m=C.shape[0]
        g.glp_add_rows(self.p,m);maxlen=int(np.max(np.diff(C.indptr),initial=0));idx=g.intArray(maxlen+1);val=g.doubleArray(maxlen+1)
        for k in range(m):
            row=self.m+k+1;g.glp_set_row_bnds(self.p,row,*bound(lo[k],hi[k]));a,b=C.indptr[k:k+2]
            for t in range(a,b):idx[t-a+1]=int(C.indices[t])+1;val[t-a+1]=float(C.data[t])
            g.glp_set_mat_row(self.p,row,b-a,idx,val)
        self.m+=m
    def solve(self,seconds):
        start=time.monotonic();g.glp_term_out(g.GLP_OFF);g.glp_scale_prob(self.p,g.GLP_SF_EQ|g.GLP_SF_2N)
        parm=g.glp_smcp();g.glp_init_smcp(parm);parm.msg_lev=g.GLP_MSG_OFF;parm.meth=g.GLP_DUALP
        parm.presolve=g.GLP_OFF;parm.tol_bnd=1e-9;parm.tol_dj=1e-9;parm.tol_piv=1e-10;parm.tm_lim=max(1,int(min(8.,seconds)*1000))
        code=g.glp_simplex(self.p,parm);status=g.glp_get_status(self.p);record=dict(float_returncode=int(code),float_status=int(status),exact_used=False)
        left=seconds-(time.monotonic()-start)
        if (code!=0 or status!=g.GLP_OPT or self.n<=4) and left>.5:
            parm.tm_lim=max(1,int(min(12.,left)*1000));parm.it_lim=10000
            code=g.glp_exact(self.p,parm);status=g.glp_get_status(self.p)
            record.update(exact_used=True,exact_returncode=int(code),exact_status=int(status))
        record.update(optimal=bool(code==0 and status==g.GLP_OPT),iterations=int(g.glp_get_it_cnt(self.p)),seconds=time.monotonic()-start)
        x=np.array([g.glp_get_col_prim(self.p,j+1) for j in range(self.n)])
        row_dual=np.array([g.glp_get_row_dual(self.p,k+1) for k in range(self.m)])
        col_dual=np.array([g.glp_get_col_dual(self.p,j+1) for j in range(self.n)])
        return x,row_dual,col_dual,record
    def close(self):
        if self.p:g.glp_delete_prob(self.p);self.p=None
