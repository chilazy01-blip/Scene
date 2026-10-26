"""Zero-step feasibility of correcting the measured v2 wrist tracking offset."""
import argparse
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from .reference_feedback import limited
from sage.experiments.embodied_native_object_transport_v1.kinematics_r3 import IK
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding


def run(root):
    import mujoco
    p=read_bound_json(root/'PROTOCOL.json');scene=read_bound_json(Path(p['scene']['path']));t=read_bound_json(root/'version_02/full/TRACE.json')
    row=t['records'][-1];q=np.asarray(row['substeps'][-1]['full_qpos_after']);m=load_model(scene['model']['path']);d=mujoco.MjData(m);d.qpos[:]=q;mujoco.mj_kinematics(m,d)
    ik=IK(mujoco,m);w=m.body('right_wrist_yaw_link').id;nom=np.asarray(row['wrist_reference_m']);error=nom-d.xpos[w]
    rerror=Rotation.from_matrix(d.xmat[w].reshape(3,3).T).as_rotvec();bias=limited(error,.06);rbias=limited(rerror,.3)
    fit=ik.solve(q,nom+bias,Rotation.from_rotvec(rbias).as_matrix(),max_evaluations=150)
    safe_save(root/'REFERENCE_FEEDBACK_PROBE_V3.json',dict(new_physics_steps=0,nominal_position_error_m=error.tolist(),orientation_error_rad=rerror.tolist(),
        steady_correction_ik=fit,feasible=fit['position_error_m']<=.01 and fit['orientation_error_rad']<=.05,
        source=_file_binding(root/'version_02/full/TRACE.json'),implementation=_file_binding(Path(__file__)),
        limitation='IK feasibility only; actual feedback convergence and complete grasp/carry still require dynamics'))
    print(dict(feasible=fit['position_error_m']<=.01 and fit['orientation_error_rad']<=.05,position_error_m=error.tolist(),orientation_error_rad=rerror.tolist()),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);run(ap.parse_args().root)
