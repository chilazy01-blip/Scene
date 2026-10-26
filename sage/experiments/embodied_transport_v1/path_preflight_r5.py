"""Zero integration swept mesh clearance on the new exact task model."""
import argparse
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from .kinematics import solve, ARM_NAMES
from .metrics_r5 import observe
from sage.experiments.embodied_carry_v1.grasp import RIGHT_CLOSED
from sage.experiments.embodied_data_stability_v1.audit_candidates import canonical_sha256, write_json_atomic
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding

def run(root):
    import mujoco
    parent=root.parent/'embodied_transport_20261020_v4/attempt_01/active_1000/REPORT.json'
    report=read_bound_json(parent)
    trace=read_bound_json(Path(report['trace']['path']))
    active=[r for r in trace['records'] if r['sonic_candidate_consumed_by_physics']]
    m=mujoco.MjModel.from_xml_path(str(root/'model/model.xml'))
    d=mujoco.MjData(m)
    d.qpos[:]=active[179]['substeps'][-1]['full_qpos_after']
    adr=int(m.joint('payload_free').qposadr[0])
    d.qpos[adr:adr+7]=[1.45,2.45,.86,1,0,0,0]
    for name,value in RIGHT_CLOSED.items():
        d.qpos[int(m.joint(name).qposadr[0])]=.45*value
    mujoco.mj_forward(m,d)
    w=m.body('right_wrist_yaw_link').id
    origin=d.xpos[w].copy(); orientation=d.xmat[w].reshape(3,3).copy()
    segments=[('withdraw', origin+[-.09,.04,.07],orientation),('preinsert',np.array([1.24,2.4,.87]),np.eye(3)),('insert',np.array([1.32,2.4,.87]),np.eye(3))]
    checks=[]
    for phase,goal,target_R in segments:
        start=d.xpos[w].copy(); start_R=d.xmat[w].reshape(3,3).copy()
        delta=Rotation.from_matrix(start_R.T@target_R).as_rotvec()
        for i in range(1,21):
            weight=i/20
            s=solve(mujoco,m,d.qpos,start*(1-weight)+goal*weight,start_R@Rotation.from_rotvec(delta*weight).as_matrix())
            for name,value in zip(ARM_NAMES,s['angles_rad']):
                d.qpos[int(m.joint(name).qposadr[0])]=value
            mujoco.mj_forward(m,d)
            p=observe(mujoco,m,d)
            checks.append({'phase':phase,'sample':i,'position_error_m':s['position_error_m'],'orientation_error_rad':s['orientation_error_rad'],'fixture':p['body_fixture_violation'],'scene':p['scene_violation'],'contacts':p['contacts']})
    passed=all(c['position_error_m']<.005 and c['orientation_error_rad']<.05 and not c['fixture'] and not c['scene'] for c in checks)
    result={'physics_steps':0,'passed':passed,'samples':checks,'parent_report':_file_binding(parent),'model':_file_binding(root/'model/model.xml'),'implementation':_file_binding(Path(__file__)),'scope':'static swept reference feasibility only; does not establish tracking or grasp'}
    result['content_sha256_excluding_this_field']=canonical_sha256(result)
    write_json_atomic(root/'PATH_PREFLIGHT.json',result)
    print({'passed':passed,'rejected':[c for c in checks if c['fixture'] or c['scene'] or c['position_error_m']>=.005 or c['orientation_error_rad']>=.05]})

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);run(p.parse_args().root)
