"""Independent virtual-work sign and original PD/bounds certificates, zero steps."""
import argparse,os,resource
from pathlib import Path
import numpy as np
from .allocation import solve
from sage.experiments.embodied_native_sonic_transport_v1.restore import load_after
from sage.experiments.embodied_native_walk_motion_v2.engine import hand_ids
from sage.experiments.embodied_native_object_transport_v1.metrics import contact_pair
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding
from sage.experiments.embodied_carry_v1.grasp import RIGHT_CLOSED,group

def run(root):
    import mujoco
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    ep=root/'version_01/full';r=read_bound_json(ep/'REPORT.json');t=read_bound_json(ep/'TRACE.json');c=read_bound_json(Path(r['case']['path']));m=load_model(r['model']['path']);m.opt.timestep=.005;d=mujoco.MjData(m);h=hand_ids(m);ix=[i for i,n in enumerate(h['names']) if n in RIGHT_CLOSED];maxpd=maxvirtual=0.;count=0
    for tick in [1150,1195,1200,1230,1265,1340]:
        load_after(mujoco,m,d,t['records'][tick-1]['substeps'][-1]);a=solve(mujoco,m,d,c['loaded_preload_targets_n']);assert a['feasible'];target=np.array(a['raw_target_rad']);torque=h['kp']*(target-d.qpos[h['qpos']])-h['kd']*d.qvel[h['dofs']]
        maxpd=max(maxpd,float(np.max(np.abs(torque[ix]-a['right_motor_torque_nm']))));assert a['maximum_wrench_error']<1e-10
        assert np.all(np.abs(target[:7])==0)
        assert np.all(torque[ix]>=m.actuator_ctrlrange[h['actuators'][ix],0]) and np.all(torque[ix]<=m.actuator_ctrlrange[h['actuators'][ix],1])
        for j in ix:assert min(0,RIGHT_CLOSED[h['names'][j]]*.5)-1e-9<=target[j]<=max(0,RIGHT_CLOSED[h['names'][j]]*.5)+1e-9
        generalized=np.zeros(m.nv);jac_generalized=np.zeros(m.nv)
        for i,co in enumerate(d.contact):
            pair=contact_pair(m,co);names=[x['name'] for x in pair]
            if 'payload_surface' not in names:continue
            side=names.index('payload_surface')
            if group(pair[1-side]['body']) not in ['thumb','index','middle']:continue
            f=np.zeros(6);mujoco.mj_contactForce(m,d,i,f);sign=1. if side==1 else -1.;F=-sign*np.asarray(co.frame).reshape(3,3).T@f[:3];body=int(m.geom_bodyid[co.geom[1-side]])
            mujoco.mj_applyFT(m,d,F,np.zeros(3),co.pos,body,generalized)
            J=np.zeros((3,m.nv));mujoco.mj_jac(m,d,J,None,co.pos,body);jac_generalized+=J.T@F
        maxvirtual=max(maxvirtual,float(np.max(np.abs(generalized[h['dofs']]-jac_generalized[h['dofs']]))))
        slew=solve(mujoco,m,d,c['loaded_preload_targets_n'],np.zeros(14));assert slew['feasible'] and np.max(np.abs(slew['target_rad']))<=.006000000001
        assert not solve(mujoco,m,d,dict(thumb=100.,index=100.,middle=100.))['feasible'];count+=1
    load_after(mujoco,m,d,t['records'][999]['substeps'][-1]);assert not solve(mujoco,m,d,c['loaded_preload_targets_n'])['feasible']
    assert maxpd<1e-10 and maxvirtual<1e-10
    result=dict(passed=True,new_physics_steps=0,actual_loaded_states=count,maximum_PD_mapping_error_nm=maxpd,maximum_virtual_work_error_nm=maxvirtual,original_effort_and_half_closed_target_bounds_passed=True,slew_limit_rad_per_20ms=.006,negative_over_cap_and_no_contact_rejected=True,source_trace=r['trace'],allocation=_file_binding(Path(__file__).with_name('allocation.py')),implementation=_file_binding(Path(__file__)))
    safe_save(root/'ALLOCATION_CERTIFICATE.json',result);print(result,flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);run(p.parse_args().root)
