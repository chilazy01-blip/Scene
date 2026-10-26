"""Actual loaded contact locations and normal directions; zero integrations."""
import argparse
from pathlib import Path
import numpy as np
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_native_object_transport_v1.metrics import contact_pair
from sage.experiments.embodied_carry_v1.grasp import group
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_native_sonic_transport_v1.restore import load_after
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding


def run(root):
    import mujoco
    episode=root/'version_02/full';r=read_bound_json(episode/'REPORT.json');c=read_bound_json(Path(r['case']['path']));t=read_bound_json(episode/'TRACE.json');model=load_model(r['model']['path']);model.opt.timestep=.005;d=mujoco.MjData(model)
    bounds=np.array(c['mug_local_bounds_corners']);zmin=float(bounds[:,2].min());zmax=float(bounds[:,2].max());body=model.body('payload').id
    rr=t['records'];start=next(i for i,q in enumerate(rr) if q['stage']=='lift');selected=sorted(set([start-25,start-1,start,min(start+10,len(rr)-1),min(start+20,len(rr)-1),len(rr)-1]));states=[]
    for i in selected:
        q=rr[i];s=q['substeps'][-1];load_after(mujoco,model,d,s);R=d.xmat[body].reshape(3,3);pos=d.xpos[body];contacts=[]
        for contact_index,co in enumerate(d.contact):
            pair=contact_pair(model,co);names=[x['name'] for x in pair]
            if 'payload_surface' not in names:continue
            other=pair[1] if names[0]=='payload_surface' else pair[0];role=group(other['body'])
            if role not in ['thumb','index','middle','palm']:continue
            cf=np.zeros(6);mujoco.mj_contactForce(model,d,contact_index,cf)
            if cf[0]<.01:continue
            local=R.T@(np.array(co.pos)-pos);normal_local=R.T@np.asarray(co.frame).reshape(3,3)[0]
            contacts.append(dict(group=role,normal_force_n=float(cf[0]),contact_object_local_m=local.tolist(),normalized_height=float((local[2]-zmin)/(zmax-zmin)),normal_absolute_vertical_component=float(abs(normal_local[2])),distance_m=float(co.dist)))
        states.append(dict(tick=q['tick'],time_s=s['time_after_s'],stage=q['stage'],forces=s['forces'],object_local_to_wrist_m=s['object_local_m'],wrist_m=q['wrist_position_m'],object_m=s['object_m'],contacts=contacts))
    contacts=[a for q in states for a in q['contacts']];total=sum(a['normal_force_n'] for a in contacts)
    result=dict(schema='actual-native-cup-contact-geometry/v1',new_physics_steps=0,mug_local_z_bounds_m=[zmin,zmax],states=states,
        force_weighted_height=sum(a['normal_force_n']*a['normalized_height'] for a in contacts)/total if total else None,
        force_fraction_in_top_25percent=sum(a['normal_force_n'] for a in contacts if a['normalized_height']>.75)/total if total else None,
        force_fraction_in_bottom_25percent=sum(a['normal_force_n'] for a in contacts if a['normalized_height']<.25)/total if total else None,
        limitation='sampled actual contact geometry; contact-normal magnitude and finger group membership do not alone prove wrench closure or stable lift',
        report=_file_binding(episode/'REPORT.json'),trace=_file_binding(episode/'TRACE.json'),implementation=_file_binding(Path(__file__)))
    safe_save(root/'CONTACT_GEOMETRY_REVIEW.json',result);print({k:result[k] for k in ['force_weighted_height','force_fraction_in_top_25percent','force_fraction_in_bottom_25percent']},flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);run(ap.parse_args().root)
