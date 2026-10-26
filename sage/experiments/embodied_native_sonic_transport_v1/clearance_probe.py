"""Zero-step v2 reference clearance on the real v1 raise-start posture."""
import argparse
from pathlib import Path
import numpy as np
from .planner_v3 import ArmPlanner
from sage.experiments.embodied_native_object_transport_v1.kinematics_r3 import IK
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding


def run(root):
    import mujoco,time
    p=read_bound_json(root/'PROTOCOL.json');scene=read_bound_json(Path(p['scene']['path']));case=read_bound_json(Path(p['case']['path']))
    t=read_bound_json(root/'version_01/full/TRACE.json');row=next(r for r in t['records'] if r['stage']=='ready_arm')
    actual=np.asarray(row['substeps'][0]['full_qpos_before']);model=load_model(scene['model']['path']);ik=IK(mujoco,model)
    fit=ik.solve(actual,actual[:3]+case['ready_arm_relative_m'],np.eye(3),max_evaluations=150)
    begin=time.monotonic();plan=ArmPlanner(mujoco,model,ik.qids).solve(actual,fit['angles_rad'])
    if plan['passed']:
        q=np.asarray(plan['knots_rad']);durations=[max(20,int(np.ceil(1.875*np.max(np.abs(b-a))/(.5*.02)))) for a,b in zip(q[:-1],q[1:])]
    else:durations=[]
    safe_save(root/'CLEARANCE_REFERENCE_PROBE_V2.json',dict(plan=plan,segment_ticks=durations,reference_ticks=sum(durations),new_physics_steps=0,wall_s=time.monotonic()-begin,
        original_trace=_file_binding(root/'version_01/full/TRACE.json'),implementation=_file_binding(Path(__file__)),planner=_file_binding(Path(__file__).with_name('planner_v3.py'))))
    print(dict(passed=plan['passed'],reason=plan['failure'],checks=plan['collision_checks'],reference_ticks=sum(durations)),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);run(ap.parse_args().root)
