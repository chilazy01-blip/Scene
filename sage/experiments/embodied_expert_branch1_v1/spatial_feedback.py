"""Compact requested/actual wrist and named hand state with explicit time alignment."""
import math
from pathlib import Path
from .common import ROOT,read_bound_json,safe_save,_file_binding,check


def build(root):
    root=Path(root);out=root/'SPATIAL_FEEDBACK.json'
    if out.exists():raise FileExistsError(out)
    report=read_bound_json(root/'full/REPORT.json');check(report['trace'])
    trace=read_bound_json(Path(report['trace']['path']));schema=read_bound_json(ROOT/'ROBOT_DATA_SCHEMA.json')
    hand_names=[v['joint_name'] for v in schema['hand_target_order']]
    addresses=[v['joint_qpos_address'] for v in schema['hand_target_order']]
    official=read_bound_json(root/'PHASE_FEEDBACK_V3.json')
    assert addresses==official['state_order']['hand_qpos_indices'] and hand_names==official['state_order']['hand_names']
    groups={};records=[];previous=trace['warmup_substeps'][-1]
    for row in trace['records']:
        first=row['substeps'][0]
        assert previous['time_after_s']==first['time_before_s']
        assert previous['full_qpos_after']==first['full_qpos_before']
        actual=row['wrist_position_m'];requested=row['wrist_reference_m']
        error=None if requested is None else math.dist(actual,requested)
        view=dict(tick=row['tick'],phase=row['stage'],time_s=first['time_before_s'],
            actual_wrist_world_m=actual,requested_wrist_world_m=requested,wrist_position_error_m=error,
            actual_object_world_m=previous['object_m'],actual_object_in_wrist_m=previous['object_local_m'],
            measured_forces_n=previous['forces'],desk_supported=previous['desk_supported'],
            actual_hand_qpos_rad=dict(zip(hand_names,[previous['full_qpos_after'][j] for j in addresses])),
            requested_hand_qpos_rad=dict(zip(hand_names,first['hand_target_rad'])))
        groups.setdefault(row['stage'],[]).append(len(records));records.append(view);previous=row['substeps'][-1]
    selected=set(range(max(0,len(records)-5),len(records)));summary={}
    for stage,indices in groups.items():
        errors=[records[i]['wrist_position_error_m'] for i in indices if records[i]['wrist_position_error_m'] is not None]
        selected.update((indices[0],indices[len(indices)//2],indices[-1]))
        if errors:selected.add(max((i for i in indices if records[i]['wrist_position_error_m'] is not None),key=lambda i:records[i]['wrist_position_error_m']))
        summary[stage]=dict(policy_samples=len(indices),maximum_wrist_position_error_m=max(errors) if errors else None,last_wrist_position_error_m=records[indices[-1]]['wrist_position_error_m'])
    result=dict(schema='time-aligned-spatial-expert-feedback/v1',new_physics_steps=0,
        alignment='All actual poses/forces are at policy-command time, before its first physics substep; requested references are the command for that time. Previous exact state/time chain is asserted.',
        phase_summaries=summary,samples=[records[i] for i in sorted(selected)],
        limits='Measured tracking errors are diagnostics, not proof of a unique grasp failure cause or fresh motion.',
        bindings=dict(report=_file_binding(root/'full/REPORT.json'),trace=report['trace'],model=report['model'],phase_feedback=_file_binding(root/'PHASE_FEEDBACK_V3.json'),schema=_file_binding(ROOT/'ROBOT_DATA_SCHEMA.json'),implementation=_file_binding(Path(__file__))))
    safe_save(out,result);return result

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);r=build(p.parse_args().root);print(r['phase_summaries'])
