from .solver_schedule import apply as apply_solver
from .protocol import authorize
"""Independent forensic force reconstruction of the new actual load probe."""
import argparse,os,resource
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from sage.experiments.embodied_native_sonic_grasp_diagnosis_v1.friction import frame,capacity
from sage.experiments.embodied_native_sonic_loaded_grasp_v1.quality import required_preload
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding

def run(episode):
    import mujoco
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    p=authorize(episode.parent);r=read_bound_json(episode/'REPORT.json');t=read_bound_json(episode/'TRACE.json');c=read_bound_json(Path(r['case']['path']));model=load_model(r['model']['path']);model.opt.timestep=.005;data=mujoco.MjData(model);pid=model.body('payload').id;w=model.body('right_wrist_yaw_link').id;out=[];forceerr=caperr=sliperr=0.
    for e in t['events']:
        if e.get('kind')!='actual_wrench_quality':continue
        tick=e['tick'];apply_solver(model,p,40+4*tick-1);s=t['records'][tick-1]['substeps'][-1];a=frame(mujoco,model,data,s,pid,c,True);q=e['quality']
        controller_contacts=[v for v in a['contacts'] if v['role'] in ['thumb','index','middle'] and v['normal_n']>1e-5]
        controller_force=np.sum([v['world_force_on_cup_n'] for v in controller_contacts],axis=0) if controller_contacts else np.zeros(3)
        controller_capacity=capacity(controller_contacts,a['weight_n'],np.array(a['cup_com_m']))
        a['controller_three_finger_force_world_n']=controller_force.tolist();a['controller_three_finger_capacity']=controller_capacity
        forceerr=max(forceerr,float(np.max(np.abs(controller_force-q['hand_force_world_n']))),abs(a['desk_force_world_n'][2]-q['desk_force_z_n']))
        x=controller_capacity.get('maximum_weight_multiple');y=q['capacity'].get('maximum_weight_multiple')
        assert (x is None)==(y is None)
        if x is not None:caperr=max(caperr,abs(x-y))
        cc=[v for v in a['contacts'] if v['role'] in ['thumb','index','middle'] and v['normal_n']>1e-5]
        slip=max([v['tangential_speed_m_s'] for v in cc],default=0.);sliperr=max(sliperr,abs(slip-q['maximum_slip_m_s']))
        R=data.xmat[w].reshape(3,3);objR=data.xmat[pid].reshape(3,3)
        out.append(dict(stage=e["stage"],tick=tick,wrist_m=data.xpos[w].tolist(),object_wrist_rotation=(R.T@objR).tolist(),forensic=a,required_preload_1_5=required_preload(cc,a['weight_n'],np.array(a['cup_com_m']),1.5),required_preload_2=required_preload(cc,a['weight_n'],np.array(a['cup_com_m']),2.)))
    probes=[x for x in out if x['stage']=='load_probe'];summary=None
    if probes:
        b=probes[0];z=probes[-1];bf=b['forensic'];zf=z['forensic'];summary=dict(start_tick=b['tick'],end_tick=z['tick'],actual_wrist_delta_m=(np.array(z['wrist_m'])-b['wrist_m']).tolist(),actual_cup_delta_m=(np.array(zf['cup_com_m'])-bf['cup_com_m']).tolist(),relative_translation_change_m=float(np.linalg.norm(np.array(zf['object_local_to_wrist_m'])-bf['object_local_to_wrist_m'])),relative_rotation_change_rad=float(np.linalg.norm(Rotation.from_matrix(np.array(z['object_wrist_rotation'])@np.array(b['object_wrist_rotation']).T).as_rotvec())),start_hand_force_world_n=bf['hand_force_world_n'],end_hand_force_world_n=zf['hand_force_world_n'],start_desk_force_world_n=bf['desk_force_world_n'],end_desk_force_world_n=zf['desk_force_world_n'],minimum_capacity=min((x['forensic']['static_capacity_contact_caps'].get('maximum_weight_multiple') or 0 for x in probes)),maximum_capacity=max((x['forensic']['static_capacity_contact_caps'].get('maximum_weight_multiple') or 0 for x in probes)),peak_contact_slip_m_s=max((v['tangential_speed_m_s'] for x in probes for v in x['forensic']['contacts'] if v['role'] in ['thumb','index','middle']),default=0.))
    print(dict(force_error=forceerr,capacity_error=caperr,slip_error=sliperr),flush=True)
    assert forceerr<1e-8 and caperr<1e-8 and sliperr<1e-8
    result=dict(schema='actual-loaded-probe-independent-force-check/v2',controller_comparison_roles=['thumb','index','middle'],full_hand_palm_included_separately_in_forensics=True,new_physics_steps=0,report=_file_binding(episode/'REPORT.json'),trace=r['trace'],maximum_hand_and_desk_force_error_n=forceerr,maximum_static_capacity_error=caperr,maximum_slip_error_m_s=sliperr,probe=summary,rows=out,implementation=_file_binding(Path(__file__)))
    safe_save(episode.parent/'FORCE_CHECK.json',result);print(dict(samples=len(out),force_error=forceerr,capacity_error=caperr,probe=summary),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--episode',type=Path,required=True);run(p.parse_args().episode)
