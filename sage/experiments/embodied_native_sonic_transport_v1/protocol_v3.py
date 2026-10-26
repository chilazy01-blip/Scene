"""Final bounded reference-feedback revision, preserve complete SONIC29 authority."""
import argparse,time
from pathlib import Path
from .protocol_v2 import authorize as parent
from .protocol import reserve as parent_reserve,project_target,check
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding


def authorize(root):
    p=parent(root);v=read_bound_json(root/'VERSION_03_PROTOCOL.json')
    assert v['version']==3 and v['deadline_epoch_utc']==p['deadline_epoch_utc']
    for b in [v['case'],v['cause_report'],v['cause_audit'],v['endpoint_probe'],v['tests'],*v['dependencies'].values()]:check(b)
    p=dict(p);p['case']=v['case'];p['full_ticks']=2795;return p


def reserve(root,output,ceiling):
    authorize(root);assert output in [root/'version_03/admission',root/'version_03/full',root/'continuous_replay']
    return parent_reserve(root,output,ceiling)


def freeze(root):
    p=parent(root);out=root/'VERSION_03_PROTOCOL.json';assert not out.exists() and time.time()<p['deadline_epoch_utc']
    assert read_bound_json(root/'REFERENCE_FEEDBACK_PROBE_V3.json')['feasible']
    cost=read_bound_json(root/'COST.json')
    spent=sum(read_bound_json(Path(r['output'])/'REPORT.json')['physics_steps'] for r in cost['reservations'])
    assert spent==7116 and spent+440+2*11220<=p['max_new_physics_steps']
    case=read_bound_json(Path(p['case']['path']));case['reference_revision']='v2 collision corridor and speed plus bounded actual-wrist-error correction of SONIC input references only'
    safe_save(root/'CASE_V3.json',case)
    safe_save(out,dict(schema='native-sonic29-reference-feedback/v3',version=3,deadline_epoch_utc=p['deadline_epoch_utc'],
        parent=_file_binding(root/'VERSION_02_PROTOCOL.json'),case=_file_binding(root/'CASE_V3.json'),
        cause_report=_file_binding(root/'version_02/full/REPORT.json'),cause_audit=_file_binding(root/'version_02/full/AUDIT.json'),
        endpoint_probe=_file_binding(root/'REFERENCE_FEEDBACK_PROBE_V3.json'),tests=_file_binding(root/'REFERENCE_FEEDBACK_TESTS.xml'),
        only_causal_change='bounded integral Cartesian position/orientation correction applied to IK-generated SONIC motion reference, no correction of NN output or independent arm motors',
        correction_limits=dict(position_norm_m=.06,rotation_norm_rad=.3,position_increment_m=.01,rotation_increment_rad=.04,update_period_s=.1,integral_gain_per_s=2.,ik_feasibility_backoff_factors=[1.,.5,0.]),
        unchanged='native model, gains/effort/real ranges/physical gates, SONIC29 ownership, nominal wrist reach15mm/0.12rad, real pickup/carry/release task',
        full_ticks=2795,maximum_full_physics_steps=11220,
        reserved_replay_capacity_proof=dict(prior_round_steps=spent,new_admission_max=440,full_max=11220,replay_max=11220,worst_total=spent+440+22440),
        dependencies={n:_file_binding(Path(__file__).with_name(n)) for n in ('protocol_v3.py','reference_feedback.py','task_v3.py','engine_v3.py','audit_v3.py','visualize_v3.py','closeout_v3.py','replay_v3.py','advance_v3.py','test_reference_feedback.py','feedback_probe.py','render.py')}))
    print(dict(version=3,frozen=True,physics_steps=0,worst_total=spent+440+22440),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);freeze(ap.parse_args().root)
