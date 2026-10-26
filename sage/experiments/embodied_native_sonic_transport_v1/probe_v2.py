"""Zero-step arm-reference route probe at the previous real settled posture."""
import argparse
from pathlib import Path
import numpy as np
from .planner_v2 import ArmPlanner
from sage.experiments.embodied_native_object_transport_v1.kinematics_r3 import IK
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding


def run(root,parent):
    import mujoco,time
    assert not (root/'REFERENCE_ROUTE_PROBE_R2.json').exists()
    p=read_bound_json(parent/'PROTOCOL.json');scene=read_bound_json(Path(p['scene']['path']));case=read_bound_json(Path(p['case']['path']))
    trace=read_bound_json(parent/'version_05/full/TRACE.json');actual=np.array(trace['records'][-1]['substeps'][-1]['full_qpos_after'])
    m=load_model(scene['model']['path']);ik=IK(mujoco,m)
    goal=actual[:3]+np.asarray(case['ready_arm_relative_m']);solved=ik.solve(actual,goal,np.eye(3),max_evaluations=150)
    start=time.monotonic();route=ArmPlanner(mujoco,m,ik.qids).solve(actual,solved['angles_rad'])
    safe_save(root/'REFERENCE_ROUTE_PROBE_R2.json',dict(route=route,ik=solved,actual_qpos=actual.tolist(),wall_s=time.monotonic()-start,
        previous_trace=_file_binding(parent/'version_05/full/TRACE.json'),implementation=_file_binding(Path(__file__)),planner=_file_binding(Path(__file__).with_name('planner_v2.py')),
        scope='one real previous posture, FK only, no trajectory execution or SONIC task qualification'))
    print({k:route[k] for k in ('passed','failure','collision_checks','search_iterations')},flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);ap.add_argument('--parent',type=Path,required=True);a=ap.parse_args();run(a.root,a.parent)
