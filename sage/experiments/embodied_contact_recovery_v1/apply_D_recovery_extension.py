"""Apply the prepared amendment only with an actual separately recorded user approval."""
import copy
import sys,time
from pathlib import Path
from .work import E,c
from sage.experiments.embodied_continuous_v3 import controller as previous
from . import controller_recovery_v4 as revised


def main(approval_path):
    approval_path=Path(approval_path).resolve()
    assert approval_path==E/'D_RECOVERY_EXTENSION_APPROVAL.json'
    approval=c.read(approval_path);proposal=E/'D_RECOVERY_EXTENSION_PROPOSAL.json'
    assert approval['approved'] is True and approval['actual_user_reply'].strip()
    assert approval['proposal_sha256']==c.sha(proposal)
    assert set(approval['approved_decisions'])=={'D_failure_limit_3_to_5_existing_two_development_slots','transfer64000_unused_development_task_steps_to_diagnostics'}
    request=c.read(proposal);assert c.evidence_ok(request['prepared_reviewable_inputs'])
    assert c.read(E/'D_RECOVERY_CONTROLLER_PREFLIGHT.json')['passed']
    applied=E/'D_RECOVERY_EXTENSION_APPLIED.json'
    if applied.exists():
        report=c.read(applied);assert report['approval_sha256']==c.sha(approval_path);print('already_applied');return
    with previous.locked(E) as (_,state):
        assert state['active'] is None,'finish current worker and suspend pending jobs before controller migration'
        oldplan=c.read(E/'PLAN.json');oldauth=c.read(E/'AUTHORIZATION.json');oldstate=copy.deepcopy(state)
        assert c.sha(E/'PLAN.json')==request['previous_plan_sha256']
        assert state['methods']['D_object_pose_planning']['scientific_failures']==3 and state['methods']['D_object_pose_planning']['closed']
        assert all(state['methods'][name]['closed'] for name in ['A','B','C_measured_contact_recovery'])
        assert state['stage_counts']['development']==6
        assert oldplan['limits']['task_physics_steps']==4695120 and oldplan['limits']['diagnostic_physics_steps']==75746
        plan=copy.deepcopy(oldplan);auth=copy.deepcopy(oldauth)
        plan['limits'].update(task_physics_steps=4631120,diagnostic_physics_steps=139746)
        plan['method_scientific_failure_limits']={'D_object_pose_planning':5}
        assert plan['scientific_failure_limit']==3
        assert plan['clock']==oldplan['clock'] and plan['protected_pools']==oldplan['protected_pools']
        method=state['methods']['D_object_pose_planning'];method.update(closed=False,last_closure_reason=method.get('closure_reason'),closure_reason=None)
        method['authorized_recovery']={'approval_sha256':c.sha(approval_path),'existing_scientific_failures_retained':3,'cumulative_failure_limit':5,'additional_development_task_cap':2}
        spent=copy.deepcopy(state['spent']);methods_before=copy.deepcopy(oldstate['methods'])
        state['events'].append({'epoch':time.time(),'action':'apply_approved_D_recovery_extension','approval_sha256':c.sha(approval_path),'proposal_sha256':c.sha(proposal),'D_failures_retained':3,'diagnostic_transfer_steps':64000,'global_physics_total_unchanged':True,'controller':'sage.experiments.embodied_contact_recovery_v1.controller_recovery_v4'})
        merged=copy.deepcopy(plan);merged['jobs'].update(state.get('additional_jobs',{}));revised.validate_plan(merged)
        snapshot=E/'evidence/before_D_recovery_extension';snapshot.mkdir(exist_ok=False)
        for name,value in [('PLAN.json',oldplan),('AUTHORIZATION.json',oldauth),('STATE.json',oldstate),('RUN_CLOCK.json',c.read(E/'RUN_CLOCK.json'))]:c.write(snapshot/name,value)
        auth['active_controller']='sage.experiments.embodied_contact_recovery_v1.controller_recovery_v4'
        files=[approval_path,proposal,Path(revised.__file__),Path(__file__),E/'D_RECOVERY_CONTROLLER_PREFLIGHT.json',snapshot/'RUN_CLOCK.json',snapshot/'PLAN.json',snapshot/'AUTHORIZATION.json',snapshot/'STATE.json']
        auth['bindings'].update({str(p):c.sha(p) for p in files});auth['D_recovery_extension_approval_sha256']=c.sha(approval_path)
        c.write(E/'D_RECOVERY_EXTENSION_COMMIT_INTENT.json',{'approval_sha256':c.sha(approval_path),'old_plan_sha256':c.sha(E/'PLAN.json'),'new_plan':plan,'new_state':state,'new_authorization_without_plan_sha':auth,'safe_recovery_precondition':'No active workers; use immutable approval and old/new expected content, never reset counters.'})
        c.write(E/'STATE.json',state);c.write(E/'PLAN.json',plan);auth['plan_sha256']=c.sha(E/'PLAN.json');c.write(E/'AUTHORIZATION.json',auth)
        assert c.read(E/'STATE.json')['spent']==spent
        assert all(state['methods'][name]==methods_before[name] for name in ['A','B','C_measured_contact_recovery'])
    with revised.locked(E) as (checked,actual):
        assert actual['spent']==spent and actual['methods']['D_object_pose_planning']['scientific_failures']==3
        assert revised.scientific_limit(checked,'D_object_pose_planning')==5 and revised.scientific_limit(checked,'C_measured_contact_recovery')==3
    c.write(applied,{'applied_epoch':time.time(),'approval_sha256':c.sha(approval_path),'proposal_sha256':c.sha(proposal),'new_plan_sha256':c.sha(E/'PLAN.json'),'controller':auth['active_controller'],'limits':plan['limits'],'D_existing_failures':3,'D_cumulative_failure_limit':5,'other_methods_unchanged':True,'clock_unchanged':plan['clock'],'protected_pools_unchanged':True,'spent_preserved':spent,'audit_recovery_steps_reserved':180000})
    print('approved_D_recovery_extension_applied')


if __name__=='__main__':main(sys.argv[1])
