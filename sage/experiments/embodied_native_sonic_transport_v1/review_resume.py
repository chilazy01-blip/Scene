"""Honest stage accounting, independent audit and measured cost per actual attempt."""
import argparse
from pathlib import Path
import numpy as np
from .protocol_resume import authorize
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding


def run(root,episode):
    p=authorize(root);out=episode.parent/'ATTEMPT_REVIEW.json';assert not out.exists()
    r=read_bound_json(episode/'REPORT.json');a=read_bound_json(episode/'AUDIT.json');t=read_bound_json(episode/'TRACE.json')
    steps=t['warmup_substeps']+[s for row in t['records'] for s in row['substeps']]
    entered=['initial_stand']+[e['stage'] for e in t['events'] if 'stage' in e]
    expected=['initial_stand','approach','source_stop','ready_arm','preinsert','lower','insert','close','lift','tuck','carry','target_stop','place','release','retract','settle','done']
    phases=[]
    for stage in expected:
        hits=[s for s in steps if s['stage']==stage]
        status='not_executed'
        if stage in entered:status='completed' if entered.index(stage)<len(entered)-1 or (stage=='done' and r['task_passed']) else 'stopped_here'
        phases.append(dict(stage=stage,status=status,physics_steps=len(hits),start_s=hits[0]['time_before_s'] if hits else None,end_s=hits[-1]['time_after_s'] if hits else None))
    ledger=read_bound_json(root/'COST.json');spent=sum(read_bound_json(Path(q['output'])/'REPORT.json')['physics_steps'] if (Path(q['output'])/'REPORT.json').exists() else q['maximum_steps'] for q in ledger['reservations'])
    result=dict(schema='native-sonic29-attempt-review/v1',task_passed=bool(r['task_passed'] and a['task_passed']),
        positive_episode_count=int(r['task_passed'] and a['task_passed']),physical_steps=len(steps),new_physics_steps=r['new_physics_steps'],checkpoint_continuation=r['checkpoint_continuation'],duration_s=len(steps)*.005,
        phase_accounting=phases,stop_reason=r['stop_reason'],engineering_error=r['error'],
        all_executed_physics_safe=all(s['safe'] for s in steps),all_active_body_commands_sonic29=all(row['body_action_source']=='SONIC29' and not row['independent_arm_actuation'] for row in t['records']),
        active_body_extra_feedforward_zero=all(not np.any(s['body_feedforward_nm']) for s in steps if s['active']),
        maximum_penetration_m=max(s['penetration_m'] for s in steps),maximum_contact_force_n=max(s['maximum_contact_force_n'] for s in steps),
        minimum_up=min(s['up'] for s in steps),maximum_actual_joint_excess_rad=max(s['maximum_joint_excess_rad'] for s in steps),
        maximum_hand_scene_force_n=max(s['hand_scene_force_n'] for s in steps),
        final_root_m=steps[-1]['root_m'],final_root_speed_m_s=float(np.linalg.norm(steps[-1]['root_velocity_m_s'])),
        final_object_m=steps[-1]['object_m'],final_opposing=steps[-1]['opposing'],final_desk_supported=steps[-1]['desk_supported'],
        failed_physics=[dict(time=s['time_after_s'],stage=s['stage'],gates=[k for k,v in s['gates'].items() if not v],contacts=[c for c in s['contacts'] if c['forbidden'] or c['distance_m']<-.01]) for s in steps if not s['safe']],
        independent_audit_gates=a['gates'],policy_io=r['policy_io'],trace=r['trace'],report=_file_binding(episode/'REPORT.json'),audit=_file_binding(episode/'AUDIT.json'),
        round_actual_or_reserved_steps=spent,cumulative_native_steps=p['prior_native_steps']+spent,ledger_snapshot=ledger,
        terminal_reference_events=t['events'][-4:],rejected_command=t['rejected_command'],
        implementation=_file_binding(Path(__file__)),scope='real actual attempt, no unexecuted later phases or inferred pickup success')
    safe_save(out,result)
    print({k:result[k] for k in ('task_passed','physical_steps','stop_reason','all_executed_physics_safe','all_active_body_commands_sonic29')},flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);ap.add_argument('--episode',type=Path,required=True);a=ap.parse_args();run(a.root,a.episode)
