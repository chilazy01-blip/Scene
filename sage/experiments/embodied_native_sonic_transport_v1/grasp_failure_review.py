"""Measured grasp-loss regression from recorded native states; zero integrations."""
import argparse
from pathlib import Path
import numpy as np
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding


def longest(rows,predicate):
    best=run=0
    for s in rows:
        run=run+1 if predicate(s) else 0;best=max(best,run)
    return best*.005


def run(root):
    episode=root/'version_04_ordered/full';r=read_bound_json(episode/'REPORT.json');t=read_bound_json(episode/'TRACE.json');case=read_bound_json(root/'CASE_V4.json')
    rows=[s for q in t['records'] for s in q['substeps']];lift=[s for s in rows if s['stage']=='lift'];closed=[s for s in rows if s['stage']=='close'];insert=[s for s in rows if s['stage']=='insert']
    assert r['stop_reason']=='object_slipped' and closed and lift
    anchor=np.asarray(closed[-1]['object_local_m']);last=lift[-1]
    phases={}
    for name in ['preinsert','lower','insert','close','lift']:
        rr=[s for s in rows if s['stage']==name]
        phases[name]=dict(start_s=rr[0]['time_before_s'],end_s=rr[-1]['time_after_s'],steps=len(rr),all_physical_gates_passed=all(s['safe'] for s in rr),
            max_opposing_duration_s=longest(rr,lambda s:s['opposing']),max_no_desk_contact_duration_s=longest(rr,lambda s:not s['desk_supported']),
            max_object_bottom_m=max(s['object_bottom_m'] for s in rr),max_object_center_m=max(s['object_m'][2] for s in rr),
            peak_contact_force_by_group_n={k:max(s['forces'][k] for s in rr) for k in rr[0]['forces']})
    result=dict(schema='native-sonic29-measured-grasp-loss/v1',new_physics_steps=0,task_passed=False,report=_file_binding(episode/'REPORT.json'),trace=_file_binding(episode/'TRACE.json'),
        phases=phases,insert_object_xy_displacement_m=float(np.linalg.norm(np.asarray(insert[-1]['object_m'])[:2]-np.asarray(insert[0]['object_m'])[:2])),
        held_slip_recorded_max_m=r['max_held_slip_m'],original_slip_abort_m=.04,
        required_off_table_bottom_m=case['support_top_m']+.025,required_clearance_ever_reached=any(s['object_bottom_m']>case['support_top_m']+.025 for s in lift),
        final_hand_contact=last['hand_contact'],final_opposing=last['opposing'],final_desk_supported=last['desk_supported'],final_contact_force_groups_n=last['forces'],
        all_executed_physical_gates_passed=all(s['safe'] for s in rows),hand_table_force_n=max(s['hand_scene_force_n'] for s in rows),
        feedback_observes='wrist pose error only; finger closure remains original fixed task schedule, no object-relative slip/contact-force feedback',
        inference='Measured loss of opposing hand contacts while mug remains table-supported localizes failure to grasp retention during lift. Does not alone establish whether pose, finger closure, friction or geometry dominates.',
        next_bounded_work='Keep corrected SONIC29 interface fixed; validate object-relative grasp alignment and retention before another carry attempt, including observed cup motion during insertion. Do not tune whole-body control to compensate for unverified grasp.',
        limitation='one development scene and one corrected continuation, no complete native mug positive or learning benefit',implementation=_file_binding(Path(__file__)))
    safe_save(root/'GRASP_FAILURE_REVIEW.json',result)
    print({k:result[k] for k in ['new_physics_steps','insert_object_xy_displacement_m','held_slip_recorded_max_m','required_clearance_ever_reached','all_executed_physical_gates_passed']},flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);run(ap.parse_args().root)
