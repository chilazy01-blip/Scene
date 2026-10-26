"""Content-based batch accounting: registered slots, execution, and qualification differ."""
from collections import Counter
from pathlib import Path
import json

def read_optional(path):
    return json.loads(Path(path).read_text()) if Path(path).exists() else None

def episode_row(config, seed):
    config=Path(config);name='source_'+str(seed);ep=config/'episodes'/name
    attempt=read_optional(ep/'ATTEMPT.json')
    verification=read_optional(config/'evidence'/f'{name}_VERIFICATION.json')
    visual=read_optional(config/'evidence'/f'{name}_VISUAL.json')
    export=read_optional(config/'exports'/f'{name}_VERIFICATION.json')
    preflight=read_optional(config/'evidence/PREFLIGHT.json')
    physical=bool(verification and verification.get('qualified_physical'))
    qualified=bool(physical and visual and visual.get('accepted') and export and export.get('passed'))
    if qualified:reason=None
    elif not preflight or not preflight.get('passed'):reason='configuration_not_executable'
    elif attempt is None:reason='registered_but_not_executed'
    elif attempt.get('status')!='success':reason=attempt.get('error') or attempt.get('status','missing_status')
    elif not physical:reason='physical_quality_or_replay_failed'
    elif not visual:reason='RGB_or_visual_verification_incomplete'
    elif not visual.get('accepted'):reason='visual_rejected:'+','.join(visual.get('reasons',[]))
    else:reason='official_export_incomplete_or_rejected'
    return dict(configuration=config.name,seed=seed,source_name=name,registered_slot=True,
        execution_started=attempt is not None,source_artifact_status=(attempt or {}).get('status'),
        physical_success=bool(attempt and attempt.get('status')=='success' and attempt.get('result',{}).get('success')),
        physical_qualified=physical,replay_passed=bool(verification and verification.get('replay_passed')),
        visual_accepted=bool(visual and visual.get('accepted')),standard_export_passed=bool(export and export.get('passed')),
        qualified=qualified,rejection_reason=reason,source_actions=(attempt or {}).get('actions'),
        source_physical_seconds=(attempt or {}).get('physical_seconds'),
        collector_wall_seconds=(attempt or {}).get('wall_seconds'),
        source_episode=str(ep) if attempt else None,
        source_trajectory=str(ep/'trajectory.h5') if (ep/'trajectory.h5').exists() else None,
        standard_dataset=str(config/'exports'/name) if qualified else None,
        attempt=attempt,verification=verification,visual=visual,export=export)

def summarize(rows):
    keys=[(r['configuration'],r['seed']) for r in rows]
    if len(set(keys))!=len(keys):raise ValueError('duplicate_registered_slot')
    for row in rows:
        if row['qualified'] and not all(row[k] for k in ['execution_started','physical_success','physical_qualified','replay_passed','visual_accepted','standard_export_passed']):
            raise ValueError('qualification_not_supported_by_all_gates')
    n=len(rows);executed=sum(x['execution_started'] for x in rows);passed=sum(x['qualified'] for x in rows)
    return dict(registered_slots=n,source_attempts_started=executed,unexecuted_slots=n-executed,
        physical_successes=sum(x['physical_success'] for x in rows),physical_qualified=sum(x['physical_qualified'] for x in rows),
        independent_replays_passed=sum(x['replay_passed'] for x in rows),qualified_episodes=passed,
        qualified_per_registered_slot=passed/n if n else None,
        qualified_per_executed_attempt=passed/executed if executed else None,
        rejection_counts=dict(Counter(x['rejection_reason'] for x in rows if not x['qualified'])))
