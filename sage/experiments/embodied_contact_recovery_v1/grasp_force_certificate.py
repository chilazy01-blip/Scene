"""Ideal retained-friction cone certificate; no empirical calibration claim."""
import numpy as np,mujoco
from scipy.optimize import linprog


def certify(m,d,obj):
    columns=[];surfaces=[]
    for ct in d.contact:
        bs=[int(m.geom_bodyid[g]) for g in [ct.geom1,ct.geom2]]
        if obj not in bs or ct.dist>0:continue
        other=ct.geom1 if bs[1]==obj else ct.geom2
        if not m.body(int(m.geom_bodyid[other])).name.startswith('right_hand'):continue
        surfaces.append(m.geom(ct.geom2 if bs[1]==obj else ct.geom1).name)
        normal=(1 if bs[1]==obj else -1)*ct.frame.reshape(3,3)[0];frame=ct.frame.reshape(3,3);lever=ct.pos-d.xipos[obj]
        for angle in np.linspace(0,2*np.pi,8,endpoint=False):
            force=normal+ct.friction[0]*(np.cos(angle)*frame[1]+np.sin(angle)*frame[2]);columns.append(np.r_[force,np.cross(lever,force)/.037])
    if not columns:return {'linearized_force_closure':False,'gravity_equilibrium_feasible':False,'object_contact_geoms':surfaces}
    W=np.array(columns).T;n=W.shape[1];rank=int(np.linalg.matrix_rank(W,tol=1e-8));b=np.r_[-m.body_mass[obj]*m.opt.gravity,np.zeros(3)]
    equilibrium=linprog(np.ones(n),A_eq=W,b_eq=b,bounds=(0,None),method='highs')
    Aeq=np.r_[np.c_[W,np.zeros(6)],np.r_[np.ones(n),0.][None,:]];closure=linprog(np.r_[np.zeros(n),-1.],A_ub=np.c_[-np.eye(n),np.ones(n)],b_ub=np.zeros(n),A_eq=Aeq,b_eq=np.r_[np.zeros(6),1.],bounds=[(0,None)]*(n+1),method='highs')
    return {'wrench_ray_rank':rank,'linearized_force_closure':bool(closure.success and rank==6 and closure.x[-1]>1e-9),'strict_positive_coefficient_margin':float(closure.x[-1]) if closure.success else None,'gravity_equilibrium_feasible':bool(equilibrium.success),'gravity_wrench_residual':float(np.max(abs(W@equilibrium.x-b))) if equilibrium.success else None,'sum_normal_force_N':float(sum(equilibrium.x)) if equilibrium.success else None,'object_contact_geoms':surfaces,'empirical_calibration':False}
