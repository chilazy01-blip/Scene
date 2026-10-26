"""Finite zero-step tucked-arm clearance probe on observed v4 states and stop roots."""
import argparse
from pathlib import Path
import numpy as np
from .protocol_v4 import authorize
from .report_safe_engine import safe_save
from .metrics import measure
from sage.experiments.embodied_native_object_transport_v1.kinematics_r3 import ARM_NAMES
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_data_stability_v1 import sonic_native_dynamic_shadow as native
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding


def run(root):
    import mujoco
    p=authorize(root)
    c=read_bound_json(Path(p['case']['path']))
    scene=read_bound_json(Path(p['scene']['path']))
    trace=read_bound_json(root/'version_04/full/TRACE.json')
    model=load_model(scene['model']['path']); data=mujoco.MjData(model)
    ids=native._model_ids(mujoco,model)
    arm=np.array([int(model.joint(n).qposadr[0]) for n in ARM_NAMES])
    wrist=model.body('right_wrist_yaw_link').id
    original=np.array(trace['initial_qpos'])
    walk=[np.array(r['substeps'][-1]['full_qpos_after']) for r in trace['records'] if r['stage'] in ('approach','source_stop')]
    observed=walk[::10]+walk[-1:]
    stops=[]
    for x in [1.75,1.8,1.85,1.9,1.95]:
        q=walk[-1].copy();q[0]=x;stops.append(q)
    candidates=[
        [0.35,-0.25,0,1.0,0,0,0], [0.55,-0.25,0,1.0,0,0,0],
        [0.75,-0.25,0,1.2,0,0,0], [0.85,-0.25,0,1.4,0,0,0],
        [0.55,-0.40,0,1.2,0,0,0], [0.75,-0.40,0,1.4,0,0,0],
        [0.35,-0.25,0,1.4,0,0,0], [0.0,-0.25,0,1.6,0,0,0]]
    attempts=[]
    for angles in candidates:
        samples=[]
        states=[]
        for f in np.linspace(0,1,21):
            q=original.copy();q[arm]=(1-f)*original[arm]+f*np.array(angles);states.append(('initial_tuck',float(f),q))
        for i,q0 in enumerate(observed+stops):
            q=q0.copy();q[arm]=angles;states.append(('observed_or_stop',i,q))
        for phase,index,q in states:
            data.qpos[:]=q;data.qvel[:]=0;mujoco.mj_forward(model,data)
            m=measure(mujoco,model,data,ids,np.zeros(model.nv),c)
            bad=[]
            for contact in m['contacts']:
                names=[a['name'] for a in contact['pair']]
                bodies=[a['body'] for a in contact['pair']]
                if any(n.startswith('scene_collision_') for n in names) and contact['distance_m'] < 0:
                    bad.append(contact)
                elif contact['forbidden']:
                    bad.append(contact)
            samples.append(dict(phase=phase,index=index,root=q[:3].tolist(),wrist=data.xpos[wrist].tolist(),bad=bad,penetration_m=m['penetration_m']))
        passed=all(not s['bad'] and s['penetration_m']<=.01 for s in samples)
        attempts.append(dict(angles_rad=angles,passed=passed,samples=samples))
        print(dict(angles=angles,passed=passed,bad_samples=sum(bool(s['bad']) for s in samples),wrist_final=samples[-1]['wrist']),flush=True)
    safe_save(root/'TUCK_PREFLIGHT_V5.json',dict(schema='native-tucked-clearance/v5',physics_steps=0,
        original_trace=_file_binding(root/'version_04/full/TRACE.json'),implementation=_file_binding(Path(__file__)),attempts=attempts,
        claim='FK collision screening only, actual dynamics and later post-stop raise must still pass'))

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);run(ap.parse_args().root)
