"""Explicit one-version interface extension under the same user task/deadline/ledger.

Original max3 was the agent's bounded plan, not a user-specified permanent cap.
The frozen three-version contract is preserved. This appended protocol discloses
one official-interface experiment and does not reset or expand the physics cap.
"""
import argparse,time
from pathlib import Path
from .protocol_v3 import authorize as parent
from .protocol import project_target,check
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding


def authorize(root):
    p=parent(root);v=read_bound_json(root/'VERSION_04_PROTOCOL.json')
    assert v['version']==4 and v['additional_interface_versions']==1 and v['deadline_epoch_utc']==p['deadline_epoch_utc']
    for b in [v['case'],v['prior_protocol'],v['cause_report'],v['cause_audit'],v['interface_preflight'],v['tests'],v['reused_admission'],*v['official_sources'].values(),*v['dependencies'].values()]:check(b)
    p=dict(p);p['case']=v['case'];p['full_ticks']=2200;p['max_causal_versions']=4;return p


def reserve(root,output,ceiling):
    p=authorize(root)
    assert output in (root/'version_04/full',root/'continuous_replay')
    if time.time()>=p['deadline_epoch_utc']:raise RuntimeError('same round deadline reached')
    ledger=read_bound_json(root/'COST.json');assert not any(q['output']==str(output) for q in ledger['reservations'])
    spent=0
    for q in ledger['reservations']:
        rp=Path(q['output'])/'REPORT.json';spent+=read_bound_json(rp)['physics_steps'] if rp.exists() else q['maximum_steps']
    if spent+ceiling>p['max_new_physics_steps'] or spent+ceiling+p['prior_native_steps']>p['cumulative_native_cap']:
        raise RuntimeError('unchanged shared physics cap reached')
    ledger['reservations'].append(dict(output=str(output),maximum_steps=ceiling,reserved_at_epoch_utc=time.time()))
    safe_save(root/'COST.json',ledger)


def freeze(root):
    p=parent(root);out=root/'VERSION_04_PROTOCOL.json';assert not out.exists() and time.time()<p['deadline_epoch_utc']
    pre=read_bound_json(root/'TELEOP_INTERFACE_PREFLIGHT.json');assert pre['passed'] and pre['mode']==[1,0,0,0]
    cost=read_bound_json(root/'COST.json');spent=sum(read_bound_json(Path(q['output'])/'REPORT.json')['physics_steps'] for q in cost['reservations'])
    assert spent==12312 and spent+2*8840<=p['max_new_physics_steps']
    case=read_bound_json(Path(p['case']['path']));case['reference_revision']='mode0 joint references for walk/raise; official mode1 lowerbody+left/right/head targets for Cartesian manipulation, no fixed-torso IK gate for hand targets'
    safe_save(root/'CASE_V4.json',case)
    safe_save(out,dict(schema='native-sonic29-official-hand-interface-extension/v4',version=4,additional_interface_versions=1,
        prior_protocol=_file_binding(root/'VERSION_03_PROTOCOL.json'),deadline_epoch_utc=p['deadline_epoch_utc'],case=_file_binding(root/'CASE_V4.json'),
        user_scope='same explicit user instruction: SONIC handles most robot control and completes current native mug task; no user-specified numerical version cap was changed',
        plan_revision_disclosure='initial agent max3 has completed; append exactly1 official-interface validation based on local shipped YAML/CPP and measured72mm task failure. Original protocols/reports remain frozen. No further interface versions in this extension.',
        cause_report=_file_binding(root/'version_03/full/REPORT.json'),cause_audit=_file_binding(root/'version_03/full/AUDIT.json'),
        interface_preflight=_file_binding(root/'TELEOP_INTERFACE_PREFLIGHT.json'),tests=_file_binding(root/'TELEOP_INTERFACE_TESTS.xml'),official_sources=pre['official_sources'],
        reused_admission=_file_binding(root/'version_03/admission/REPORT.json'),
        admission_proof='first100ticks/warmup remain identical G1 mode and same gains/state/reference; full must reproduce prior v3 admission qpos/qvel/warmstart bitwise. Only later Cartesian phases select mode1.',
        all29_motor_authority='same SONIC encoder/decoder, no arm action overrides or active body feedforward, original hand closure and physical safety gates',
        input_semantics='mode1: lower12 IsaacLab joint horizon; root-full-quaternion normalized wrist/head points and wxyz orientations; local wrist offsets left[.18,-.025,0],right[.18,.025,0],torsohead[0,0,.35]; inactive fullG1/SMPL/wrist-joint blocks zero',
        fixed_task_gates_unchanged='same 15mm/0.12rad nominal wrist reach, real opposing grasp/off-table lift, held steps>=.25m and both foot cycles, release and settle',
        full_ticks=2200,maximum_physics_steps=8840,
        shared_budget_proof=dict(already_executed=spent,full_max=8840,replay_max=8840,worst_total=spent+17680,original_maximum=30000),
        dependencies={n:_file_binding(Path(__file__).with_name(n)) for n in ('protocol_v4.py','teleop_reference.py','task_v4.py','engine_v4.py','audit_v4.py','visualize_v4.py','closeout_v4.py','replay_v4.py','test_teleop_reference.py','teleop_preflight.py','advance_v4.py')}))
    print(dict(version=4,one_interface_extension=True,frozen=True,worst_total=spent+17680,physics_steps=0),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);freeze(ap.parse_args().root)
