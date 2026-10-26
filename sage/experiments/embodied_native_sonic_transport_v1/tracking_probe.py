"""Zero-step diagnosis of reference tracking and planning-copy margin support."""
import argparse,copy
from pathlib import Path
import numpy as np
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_native_object_transport_v1.kinematics_r3 import IK
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding


def run(root):
    import mujoco
    p=read_bound_json(root/'PROTOCOL.json');scene=read_bound_json(Path(p['scene']['path']));t=read_bound_json(root/'version_01/full/TRACE.json')
    model=load_model(scene['model']['path']);d=mujoco.MjData(model);ik=IK(mujoco,model);wrist=model.body('right_wrist_yaw_link').id
    row=t['records'][-1];actual=np.array(row['substeps'][0]['full_qpos_before'])
    enter=next(r for r in t['records'] if r['stage']=='ready_arm');initial=np.array(enter['substeps'][0]['full_qpos_before'])
    checks=[]
    for label,q in [('actual',actual.copy()),('actual_body_reference_arm',actual.copy()),('planned_start_body_reference_arm',initial.copy())]:
        if label!='actual':q[ik.qids]=np.asarray(row['reference_qpos'])[29:36]
        d.qpos[:]=q;mujoco.mj_kinematics(model,d)
        checks.append(dict(label=label,wrist_m=d.xpos[wrist].tolist(),arm_qpos=q[ik.qids].tolist()))
    cloned=copy.copy(model)
    ids=[i for i in range(cloned.ngeom) if (cloned.body(int(cloned.geom_bodyid[i])).name or '').startswith(('right_shoulder','right_elbow','right_wrist','right_hand'))]
    original_margin=model.geom_margin.copy();cloned.geom_margin[ids]=.04
    assert np.array_equal(model.geom_margin,original_margin)
    safe_save(root/'TRACKING_PROBE_V1.json',dict(new_physics_steps=0,comparisons=checks,
        maximum_joint_reference_error_rad=float(np.max(np.abs(np.asarray(row['reference_qpos'])[29:36]-actual[ik.qids]))),
        copy_margin_supported=True,planning_only_inflated_geom_count=len(ids),physical_model_margin_unchanged=True,
        trace=_file_binding(root/'version_01/full/TRACE.json'),implementation=_file_binding(Path(__file__))))
    print(dict(comparisons=checks,copy_margin_supported=True),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);run(ap.parse_args().root)
