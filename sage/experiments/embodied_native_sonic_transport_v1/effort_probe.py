"""Read-only native command/actual force-limit diagnosis; no integrations."""
import argparse
from pathlib import Path
import numpy as np
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_data_stability_v1 import sonic_native_dynamic_shadow as native
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding


def run(root):
    p=read_bound_json(root/'PROTOCOL.json');scene=read_bound_json(Path(p['scene']['path']));t=read_bound_json(root/'version_04_resume/full/TRACE.json')
    model=load_model(scene['model']['path']);g=native.official_control_arrays();last=t['records'][-1]['substeps'][-1];ctrl=np.asarray(last['all_ctrl'])
    mismatches=[]
    for i in range(model.nu):
        lo,hi=model.actuator_ctrlrange[i]
        if ctrl[i]<lo or ctrl[i]>hi:
            mismatches.append(dict(actuator=model.actuator(i).name,requested_nm=float(ctrl[i]),model_range=[float(lo),float(hi)],model_ctrl_limited=bool(model.actuator_ctrllimited[i]),
                model_force_range=model.actuator_forcerange[i].tolist(),model_force_limited=bool(model.actuator_forcelimited[i])))
    assert mismatches and all(x['model_ctrl_limited'] for x in mismatches)
    safe_save(root/'NATIVE_EFFORT_COMMAND_PROBE.json',dict(new_physics_steps=0,mismatches=mismatches,
        inherited_effort_limits=list(g['effort_limit']),scope='recorded data.ctrl request exceeded model range; native MuJoCo actuator_ctrllimited already bounds applied control internally. Correct the command before sending, preserve original failed trial.',
        source=_file_binding(root/'version_04_resume/full/TRACE.json'),implementation=_file_binding(Path(__file__))))
    print(mismatches,flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);run(ap.parse_args().root)
