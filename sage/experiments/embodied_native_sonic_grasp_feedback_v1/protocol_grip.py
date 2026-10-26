"""Concrete next full-task candidate; physics requires an approved resource revision."""
import argparse,time
from pathlib import Path
from .protocol_transfer import authorize as previous,check,project_target
from .protocol import read_bound_json,safe_save,_file_binding

def proposal_context(root):
    p=previous(root);v=read_bound_json(root/'GRIP_HOLD_PLAN.json')
    for b in [v['case'],v['previous_protocol'],v['cause'],v['tests'],*v['dependencies'].values()]:check(b)
    p=dict(p);p.update(case=v['case'],full_ticks=v['full_ticks'],prefix_physics_steps=4816,prefix_active_ticks=1194);return p

def authorize(root):
    p=proposal_context(root);revision=read_bound_json(root/'APPROVED_RESOURCE_REVISION.json')
    assert revision['user_approved_cumulative_cap']==75000 and revision['user_approval_quote'] and revision['approval_received_epoch_utc']<=time.time()
    assert revision['plan']==_file_binding(root/'GRIP_HOLD_PLAN.json')
    p.update(cumulative_native_cap=75000,max_new_physics_steps=75000-p['prior_native_steps'],deadline_epoch_utc=revision['deadline_epoch_utc']);return p

def reserve(root,output,ceiling):
    p=authorize(root);assert time.time()<p['deadline_epoch_utc'];l=read_bound_json(root/'COST.json');replay=output.name.startswith('continuous_replay')
    if replay:charged=output;maximum=ceiling;headroom=0
    else:
        assert output==root/'attempt_07/full' and ceiling==40+4*p['full_ticks'];charged=output.parent/'cost';maximum=ceiling-4816;headroom=ceiling
    assert not any(x['output']==str(charged) for x in l['reservations']);spent=sum(read_bound_json(Path(x['output'])/'REPORT.json')['physics_steps'] if (Path(x['output'])/'REPORT.json').exists() else x['maximum_steps'] for x in l['reservations'])
    assert spent+maximum+headroom<=p['max_new_physics_steps'] and p['prior_native_steps']+spent+maximum+headroom<=p['cumulative_native_cap']
    l['reservations'].append(dict(output=str(charged),maximum_steps=maximum,episode_output=str(output),success_replay_headroom=headroom));safe_save(root/'COST.json',l)

def prepare(root):
    p=previous(root);assert not (root/'GRIP_HOLD_PLAN.json').exists();tests=root/'HOLD_FLOOR_TESTS.xml';assert 'failures="0"' in tests.read_text() and 'errors="0"' in tests.read_text();r=read_bound_json(root/'attempt_06/full/REPORT.json');assert r['stop_reason']=='probe_relative_slip';events=[e for e in r['events'] if e.get('kind')=='normal_force_shape_admittance' and 1195<=e['tick']<=1210]
    safe_save(root/'LOAD_REFERENCE_CAUSE.json',dict(new_physics_steps=0,report=_file_binding(root/'attempt_06/full/REPORT.json'),force_check=_file_binding(root/'attempt_06/FORCE_CHECK.json'),normal_reference_events=events,confirmed='During the failed load trial, index closure decreased from about.225 to.192 while its filtered normal exceeded the changing request; then all three contacts were lost. Actual wrist rose7.35mm between force samples, cup COM rose.199mm; relative translation changed9.45mm. Friction is active; real transfer failed.',next_hypothesis='Keep an established position-reference floor during load. The measured-normal controller may increase closure to reacquire, but cannot open fingers during loading/carry before explicit release. Original native PD/range/slew/effort and real load/hover/full-task acceptance unchanged.',limitation='Reference opening and contact loss are observed. The new clamp has not been dynamically verified and is not asserted to be the only cause.'))
    case=read_bound_json(Path(p['case']['path']));case['loaded_reference_floor']='From tick1194 capture actual persistent group targets; monotonic closure floor until explicit release; no qactual reset, no stiffness/damping cancellation, same native halfclosed and .006rad/20ms envelope.';safe_save(root/'CASE_GRIP_HOLD.json',case)
    l=read_bound_json(root/'COST.json');spent=sum(read_bound_json(Path(x['output'])/'REPORT.json')['physics_steps'] for x in l['reservations']);F=9040
    safe_save(root/'GRIP_HOLD_PLAN.json',dict(status='prepared_requires_user_resource_revision_before_physics',previous_protocol=_file_binding(root/'TRANSFER_PROTOCOL.json'),case=_file_binding(root/'CASE_GRIP_HOLD.json'),cause=_file_binding(root/'LOAD_REFERENCE_CAUSE.json'),tests=_file_binding(tests),full_ticks=(F-40)//4,prefix_physics_steps=4816,source_prefix=str(root/'transfer_prefix'),requested_cumulative_native_cap=75000,requested_new_bounded_window_s=7200,budget_proof=dict(actual_current_new_steps=spent,actual_native_steps=p['prior_native_steps']+spent,new_candidate_max=F-4816,required_original_initialization_replay_max=F,combined_next_max=2*F-4816,projected_cumulative_max=p['prior_native_steps']+spent+2*F-4816,existing_cap=p['cumulative_native_cap'],remaining_under_existing_cap=p['cumulative_native_cap']-p['prior_native_steps']-spent,existing_cap_sufficient_for_this_full_task_and_replay=False),physical_and_task_acceptance_unchanged=True,all29body_joints_owned_by_SONIC=True,no_training_download_install_or_external_writes=True,dependencies={x.name:_file_binding(x) for x in Path(__file__).parent.glob('*.py')}));print(dict(prepared=True,physics_authorized=False,spent=spent,projected_native_steps=p['prior_native_steps']+spent+2*F-4816),flush=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);prepare(ap.parse_args().root)
