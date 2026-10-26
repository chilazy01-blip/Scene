"""Independent spline reconstruction; no compiler or map imports."""
import numpy as np
from scipy.interpolate import BSpline

def reconstruct(anchor,plan,x,stages,nominal_rows,source_rows,initial):
    j=len(initial);coarse=[];refined=[];offsets=[0];old_offsets=[0]
    for i,(_,a,b) in enumerate(stages):
        old_n=round((b-a)/.02)+300;n=int(np.ceil(old_n*max(1.,source_rows[i]/nominal_rows[i])))
        def parameter(count,rows):
            moving=count-25;ramp=max(1,min(50,(moving-rows+1)//2,moving//4));k=np.arange(moving);w=np.minimum(np.minimum((k+1)/ramp,(moving-k)/ramp),1.)
            return np.r_[np.cumsum(w)/w.sum(),np.ones(25)]
        segments=max(4,int(np.ceil((old_n-25)/100)));knots=np.r_[np.zeros(4),np.arange(1,segments)/segments,np.ones(4)]
        param=parameter(n,source_rows[i]);original=parameter(old_n,nominal_rows[i])
        coarse.append((BSpline.design_matrix(param,knots,3).toarray(),BSpline.design_matrix(original,knots,3).toarray()))
        refined.append(BSpline.design_matrix(param,np.sort(np.r_[knots,plan['inserted_knots'][i]]),3).toarray())
        offsets.append(offsets[-1]+n);old_offsets.append(old_offsets[-1]+old_n)
    ax=anchor['variables'];qvars=15*j+sum((b.shape[1]-6)*j for b,_ in coarse);qi=15*j;pi=qvars;base=[];basep=[];oldraw=[];oldp=[]
    for i,(basis,oldbasis) in enumerate(coarse):
        nk=basis.shape[1];coeff=np.empty((nk,j));coeff[:3]=initial if i==0 else ax[(i-1)*j:i*j];coeff[-3:]=ax[i*j:(i+1)*j];count=(nk-6)*j;coeff[3:-3]=ax[qi:qi+count].reshape(nk-6,j);qi+=count;pp=np.r_[0.,ax[pi:pi+nk-2],1.];pi+=nk-2
        base.extend(basis@coeff);basep.extend(basis@pp);oldraw.extend(oldbasis@coeff);oldp.extend(oldbasis@pp)
    assert qi==qvars and pi==len(ax)
    assert np.max(abs(np.asarray(oldraw)-anchor['raw_reference']))<1e-10 and np.max(abs(np.asarray(oldp)-anchor['progress']))<1e-10
    if offsets==old_offsets:base=anchor['raw_reference'];basep=anchor['progress']
    qvars=15*j+sum((b.shape[1]-6)*j for b in refined);qi=15*j;pi=qvars;delta=[];deltap=[]
    for i,basis in enumerate(refined):
        nk=basis.shape[1];coeff=np.empty((nk,j));coeff[:3]=np.zeros(j) if i==0 else x[(i-1)*j:i*j];coeff[-3:]=x[i*j:(i+1)*j];count=(nk-6)*j;coeff[3:-3]=x[qi:qi+count].reshape(nk-6,j);qi+=count;pp=np.r_[0.,x[pi:pi+nk-2],0.];pi+=nk-2;delta.extend(basis@coeff);deltap.extend(basis@pp)
    assert qi==qvars and pi==len(x)
    raw=np.asarray(base)+np.asarray(delta);progress=np.asarray(basep)+np.asarray(deltap);velocity=np.diff(np.vstack([initial,raw]),axis=0)/.02;acceleration=np.diff(np.vstack([np.zeros(j),velocity]),axis=0)/.02
    return dict(raw_reference=raw,progress=progress,raw_velocity=velocity,raw_acceleration=acceleration,offsets=np.array(offsets)),dict(raw_reference=np.asarray(base),progress=np.asarray(basep)),refined
