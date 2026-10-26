"""Cause-driven reference clearance/speed revision; SONIC29 motor authority unchanged."""
import argparse,time
from pathlib import Path
from .protocol import authorize as parent,reserve as parent_reserve,project_target,check
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding


def authorize(root):
    p=parent(root);v=read_bound_json(root/'VERSION_02_PROTOCOL.json')
    assert v['version']==2 and v['deadline_epoch_utc']==p['deadline_epoch_utc']
    for b in [v['case'],v['cause_report'],v['cause_audit'],v['tracking_diagnosis'],v['reference_preflight'],*v['dependencies'].values()]:check(b)
    p=dict(p);p['case']=v['case'];return p


def reserve(root,output,ceiling):
    authorize(root);assert output in [root/'version_02/admission',root/'version_02/full',root/'continuous_replay']
    return parent_reserve(root,output,ceiling)


def freeze(root):
    p=parent(root);out=root/'VERSION_02_PROTOCOL.json';assert not out.exists() and time.time()<p['deadline_epoch_utc']
    pre=read_bound_json(root/'CLEARANCE_REFERENCE_PROBE_V2.json')
    assert pre['plan']['passed'] and pre['reference_ticks']<=600
    case=read_bound_json(Path(p['case']['path']));case['stage_timeouts_ticks']=dict(case['stage_timeouts_ticks'],ready_arm=700)
    case['reference_revision']='planning-copy40mm scene clearance; peak joint reference speed0.5rad/s; actual model and all29 SONIC actuation unchanged'
    safe_save(root/'CASE_V2.json',case)
    safe_save(out,dict(schema='native-sonic29-reference-revision/v2',version=2,deadline_epoch_utc=p['deadline_epoch_utc'],
        parent=_file_binding(root/'PROTOCOL.json'),case=_file_binding(root/'CASE_V2.json'),
        cause_report=_file_binding(root/'version_01/full/REPORT.json'),cause_audit=_file_binding(root/'version_01/full/AUDIT.json'),
        tracking_diagnosis=_file_binding(root/'TRACKING_PROBE_V1.json'),reference_preflight=_file_binding(root/'CLEARANCE_REFERENCE_PROBE_V2.json'),
        causal_change='larger reference corridor to accommodate measured wrist/arm tracking error, slower reference; no motor gain/effort/range/safety threshold or ownership change',
        geometry_scope='inflate right-arm geom margins in a private copied planning model only; contact acceptance in real simulation unchanged',
        dependencies={n:_file_binding(Path(__file__).with_name(n)) for n in ('protocol_v2.py','planner_v3.py','task_v2.py','engine_v2.py','audit_v2.py','visualize_v2.py','closeout_v2.py','replay_v2.py','advance_v2.py')}))
    print(dict(version=2,frozen=True,physics_steps=0),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);freeze(ap.parse_args().root)
