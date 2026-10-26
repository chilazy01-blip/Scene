"""Compact, source-bound, first-observed-breach feedback from actual native traces."""
from pathlib import Path
from .common import read_bound_json, safe_save, _file_binding, check
from .contracts_v2 import observe, CONTRACTS


def build(root, output=None):
    root=Path(root); output=Path(output) if output else root/'PHASE_FEEDBACK_V2.json'
    if output.exists(): raise FileExistsError(output)
    report=read_bound_json(root/'full/REPORT.json')
    check(report['trace']);check(report['case']);check(report['model'])
    trace=read_bound_json(Path(report['trace']['path']));case=read_bound_json(Path(report['case']['path']))
    records=trace['records']; samples=trace['warmup_substeps']+[s for r in records for s in r['substeps']]
    assert len(samples)==report['physics_steps']
    phases=[];first=None;previous=None;selected=set();slacks=[];transitions=[]
    for index,s in enumerate(samples):
        view=observe(s,case);slacks.append(view['object_orientation_margin'])
        if previous is None or s['stage']!=previous['stage']:
            phases.append(dict(phase=s['stage'],entry_physics_index=index,entry=view,contract=CONTRACTS.get(s['stage'])))
            selected.update([max(0,index-1),index])
        if previous is not None and s['desk_supported']!=previous['desk_supported']:
            transitions.append(dict(physics_index=index,**view))
        if first is None and view['diagnostic_breaches']:
            first=dict(physics_index=index,**view)
            selected.update(range(max(0,index-12),min(len(samples),index+13)))
        previous=s
    # Retain detailed contact/reference evidence around the first breach and terminal interval.
    selected.update(range(max(0,len(samples)-12),len(samples)))
    timeline=[]
    for i in sorted(selected):
        s=samples[i]
        timeline.append(dict(physics_index=i,**observe(s,case),hand_target_rad=s['hand_target_rad'],
                             actual_finger_qpos_rad=s['full_qpos_after'][36:50],
                             finger_requested_torque_nm=s['finger_requested_torque_nm'],
                             actual_finger_actuator_force_nm=s['actual_finger_actuator_force_nm']))
    # Native hand qpos slice is verified against the immutable G1 schema in tests/QA.
    result=dict(schema='phase-contract-feedback/v2',new_physics_steps=0,
        interpretation='First observable diagnostic breach, not necessarily the unique cause or the native stop time.',
        case_id=case['case_id'],object_id=case['object_id'],source_role=case['source_role'],dataset_split=case['dataset_split'],
        frame_contract=dict(up='robot root cosine',object_rotation='object-local to world matrix',object_local_m='object in right wrist frame',finger_order='native hand_ids order; exact names in model/PolicyIO schema',physics_hz=200,policy_hz=50),
        phases=phases,first_observed_breach=first,table_support_transitions=transitions,
        minimum_object_orientation_margin=min(slacks),timeline=timeline,
        terminal=dict(stage=report['stage'],stop_reason=report['stop_reason'],engineering_error=report['error'],
                      original_task_passed=report['task_passed'],failed_original_gates=[k for k,v in report['gates'].items() if not v],
                      original_max_held_slip_m=report['max_held_slip_m']),
        causal_limit='Temporal evidence only. Finger reference changes, wrist trajectory and disturbances require intervention to distinguish causes.',
        bindings=dict(report=_file_binding(root/'full/REPORT.json'),trace=report['trace'],case=report['case'],model=report['model'],strategy=_file_binding(root/'strategy.py'),implementation=_file_binding(Path(__file__)),contracts=_file_binding(Path(__file__).with_name('contracts_v2.py'))))
    safe_save(output,result)
    return result

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path);a=p.parse_args()
    r=build(a.root,a.output);print(dict(feedback=str(a.output or a.root/'PHASE_FEEDBACK_V2.json'),first=r['first_observed_breach'],terminal=r['terminal']))
