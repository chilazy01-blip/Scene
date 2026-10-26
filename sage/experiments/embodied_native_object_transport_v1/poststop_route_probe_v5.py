"""Bounded zero-integration post-stop route search on the actual v5 terminal state."""
import argparse
from pathlib import Path
import numpy as np
from .protocol_v5 import authorize
from .report_safe_engine import safe_save
from .metrics import measure
from .kinematics_r3 import IK
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_data_stability_v1 import sonic_native_dynamic_shadow as native
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding


def run(root):
    import mujoco
    p=authorize(root);trace=read_bound_json(root/'version_05/full/TRACE.json')
    c=read_bound_json(Path(p['case']['path']));scene=read_bound_json(Path(p['scene']['path']))
    model=load_model(scene['model']['path']);data=mujoco.MjData(model);ids=native._model_ids(mujoco,model)
    actual=np.array(trace['records'][-1]['substeps'][-1]['full_qpos_after']);ik=IK(mujoco,model)
    goal=actual[:3]+np.array(c['ready_arm_relative_m'])
    solved=ik.solve(actual,goal,np.eye(3),max_evaluations=150)
    assert solved['position_error_m']<=.01 and solved['orientation_error_rad']<=.05
    final=np.array(solved['angles_rad']);origin=actual[ik.qids]
    mid=np.array([-1.2,-.2,0,1.6,0,0,0])
    routes=[
        [[.75,-.6,0,1.2,0,0,0],[-1.2,-.6,0,1.6,0,0,0],mid],
        [[.75,-.8,0,1.2,0,0,0],[-1.2,-.8,0,1.6,0,0,0],mid],
        [[.75,-.6,0,2.0,0,0,0],[-1.2,-.6,0,2.0,0,0,0],mid],
        [[.75,-.6,0,1.2,0,0,0],[.2,-.6,0,.6,0,0,0],mid],
        [[.75,-.8,0,1.2,0,0,0],[-.6,-.8,0,1.8,0,0,0],mid],
        [[.75,-.5,0,1.8,0,0,0],[-1.2,-.5,0,1.8,0,0,0],mid]]
    attempts=[]
    for rid,route in enumerate(routes):
        knots=[origin,*[np.asarray(a) for a in route],final];samples=[]
        for segment,(a,b) in enumerate(zip(knots[:-1],knots[1:])):
            for fraction in np.linspace(0,1,31):
                data.qpos[:]=actual;data.qpos[ik.qids]=(1-fraction)*a+fraction*b;data.qvel[:]=0
                mujoco.mj_forward(model,data)
                m=measure(mujoco,model,data,ids,np.zeros(model.nv),c)
                bad=[]
                for contact in m['contacts']:
                    names=[a['name'] for a in contact['pair']];bodies=[a['body'] for a in contact['pair']]
                    robot_scene=any(n.startswith('scene_collision_') for n in names) and any(n.startswith('robot_') for n in names)
                    if contact['forbidden'] or contact['distance_m']<-.01 or (robot_scene and contact['distance_m']<0):bad.append(contact)
                samples.append(dict(segment=segment,fraction=float(fraction),angles_rad=data.qpos[ik.qids].tolist(),bad=bad,penetration_m=m['penetration_m']))
        passed=all(not s['bad'] for s in samples)
        attempts.append(dict(route_id=rid,knots_rad=[k.tolist() for k in knots],passed=passed,samples=samples))
        print(dict(route_id=rid,passed=passed,bad_samples=sum(bool(s['bad']) for s in samples)),flush=True)
    safe_save(root/'POSTSTOP_ROUTE_PROBE_V5.json',dict(schema='native-poststop-arm-route-probe/v5',physics_steps=0,
        actual_terminal_trace=_file_binding(root/'version_05/full/TRACE.json'),implementation=_file_binding(Path(__file__)),
        original_ik=solved,attempts=attempts,selected_route=next((a['route_id'] for a in attempts if a['passed']),None),
        budget=dict(max_routes=6,max_fk_samples=744),
        limitation='geometric screen at one actual settled full-body posture only; no execution, no dynamic grasp success or multi-state robustness',
        next_step='if one route passes, a future bounded control version can replace only the initial raise route, with actual-state preflight still mandatory'))

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);run(ap.parse_args().root)
