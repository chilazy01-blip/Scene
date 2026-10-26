"""A source failure blocks the approved conditional collector/full-task branch."""
from .runtime import J,read,digest

def continuation():
    trial=J/'results/B1'
    result=read(trial/'RESULT.json');audit=read(trial/'INDEPENDENT_AUDIT.json')
    binding_ok=(audit.get('input_sha256')==digest(trial/'TRACE.npz')==result.get('trace_sha256'))
    source_ok=bool(binding_ok and result.get('passed') is True and
        audit.get('passed') is True and audit.get('physical_source_success') is True and
        result.get('physics_steps')==2756 and result.get('actions')==689 and
        result.get('mid_episode_state_writes')==0 and result.get('initial_state_restorations')==1)
    reasons=[]
    if not source_ok:reasons.append('native_source_baseline_and_independent_audit_not_passed')
    # A collector has not been supplied, frozen or independently admitted yet.
    if not (J/'COLLECTOR_ADMISSION.json').exists():reasons.append('validated_feedback_collector_missing')
    # Deliberately no positive task admission from a data-consumer or replay receipt.
    return dict(source_baseline_passed=source_ok,collector_trial_admitted=False,
        full_task_admitted=False,qualified_episodes=0,reasons=reasons,
        unused_component_is_conditional=True,source_evidence_hashes={
            name:digest(trial/name) for name in ('RESULT.json','INDEPENDENT_AUDIT.json','TRACE.npz')})

def require_collector():
    report=continuation()
    if not report['collector_trial_admitted']:
        raise RuntimeError('collector_not_admitted:'+','.join(report['reasons']))
