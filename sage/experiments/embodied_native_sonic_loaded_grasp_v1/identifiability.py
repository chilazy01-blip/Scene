"""Zero-step witness: identical finger torques can admit different cup loads."""
import argparse,os,resource
from pathlib import Path
import numpy as np
from scipy.optimize import linprog
from .allocation import solve
from sage.experiments.embodied_native_sonic_transport_v1.restore import load_after
from sage.experiments.embodied_native_walk_motion_v2.engine import hand_ids
from sage.experiments.embodied_native_object_transport_v1.metrics import contact_pair
from sage.experiments.embodied_carry_v1.grasp import RIGHT_CLOSED,group
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding

def run(root):
    import mujoco
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    ep=root/'version_02/full';r=read_bound_json(ep/'REPORT.json');t=read_bound_json(ep/'TRACE.json');case=read_bound_json(Path(r['case']['path']));m=load_model(r['model']['path']);m.opt.timestep=.005;d=mujoco.MjData(m);h=hand_ids(m);ix=np.array([i for i,n in enumerate(h['names']) if n in RIGHT_CLOSED]);dofs=h['dofs'][ix];pid=m.body('payload').id;out=[]
    for tick in [1200,1220,1260,1280,1300]:
        s=t['records'][tick-1]['substeps'][-1];load_after(mujoco,m,d,s);proposal=solve(mujoco,m,d,case['loaded_preload_targets_n']);assert proposal['feasible'];com=d.xipos[pid];cols=[];jointcols=[];roles=[]
        for i,c in enumerate(d.contact):
            pair=contact_pair(m,c);names=[v['name'] for v in pair]
            if 'payload_surface' not in names:continue
            side=names.index('payload_surface');other=pair[1-side];role='desk' if other['body']=='generated_desk' else group(other['body']);f=np.zeros(6);mujoco.mj_contactForce(m,d,i,f)
            if role not in ['thumb','index','middle','desk'] or f[0]<=1e-5:continue
            assert c.dim==3;D=np.asarray(c.frame).reshape(3,3);sign=1 if side==1 else -1;u,v=c.friction[:2];J=np.zeros((3,m.nv))
            if role!='desk':mujoco.mj_jac(m,d,J,None,c.pos,int(m.geom_bodyid[c.geom[1-side]]))
            for local in [[1,u,0],[1,-u,0],[1,0,v],[1,0,-v]]:
                F=sign*D.T@local;cols.append(np.r_[F,np.cross(c.pos-com,F)]);jointcols.append(J[:,dofs].T@F);roles.append(role)
        W=np.array(cols).T;T=np.array(jointcols).T;A=np.array([[float(x==g) for x in roles] for g in ['thumb','index','middle','desk']]);target=np.r_[0.,0.,proposal['weight_n'],0.,0.,0.,np.array(proposal['right_motor_torque_nm'])-d.qfrc_bias[dofs]]
        Aub=np.r_[A,-A[:3]];bub=np.r_[[6.,6.,6.,10.],[-case['loaded_preload_targets_n'][g] for g in ['thumb','index','middle']]];eq=np.r_[W,T];objective=np.array([W[2,j] if g!='desk' else 0. for j,g in enumerate(roles)])
        witnesses=[]
        for direction in [1.,-1.]:
            z=linprog(direction*objective,A_ub=Aub,b_ub=bub,A_eq=eq,b_eq=target,bounds=(0,None),method='highs')
            witnesses.append(dict(feasible=bool(z.success),hand_vertical_force_n=float(objective@z.x) if z.success else None,desk_normal_n=float((A@z.x)[3]) if z.success else None,maximum_equilibrium_and_joint_torque_error=float(np.max(np.abs(eq@z.x-target))) if z.success else None))
        out.append(dict(tick=tick,time_s=s['time_after_s'],fixed_right_motor_torque_nm=proposal['right_motor_torque_nm'],minimum_hand_vertical_force=witnesses[0],maximum_hand_vertical_force=witnesses[1]));print(out[-1],flush=True)
    result=dict(schema='finger-torque-to-object-wrench-nonuniqueness/v1',new_physics_steps=0,rows=out,source_trace=r['trace'],method='At same actual contact points/friction and exact same7 desired finger motor torques, impose6D object equilibrium with existing desk contacts. Minimize/maximize handFz within per-group normal bounds and desk normal<=10N. This changes no simulator parameter and performs no integration.',limitation='A static force-cone nonuniqueness witness, not a second real trajectory or proof actual simulator chose an alternative LP solution. Does not model contact compliance/complementarity or finger acceleration, and does not uniquely attribute every dynamic error. It tests whether finger joint torques alone select a unique world wrench.',implementation=_file_binding(Path(__file__)),allocation=_file_binding(Path(__file__).with_name('allocation.py')))
    safe_save(root/'ALLOCATION_IDENTIFIABILITY.json',result)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);run(p.parse_args().root)
