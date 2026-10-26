"""Promote only independently verified complete episodes in an explicit scope."""
from pathlib import Path
from .common import read_bound_json, check, _file_binding
from .experience_v2 import identity


def assess(verification_paths, required_cases):
    receipts=[];reasons=[];strategies=set();seen=set()
    for path in verification_paths:
        path=Path(path);v=read_bound_json(path)
        evidence=v['evidence']
        for b in evidence.values():check(b)
        r=read_bound_json(Path(evidence['report']['path']))
        p=read_bound_json(Path(r['protocol']['path']));check(r['protocol']);check(r['case']);check(p['candidate'])
        c=read_bound_json(Path(r['case']['path']));case=c['case_id'];seen.add(case);strategies.add(p['candidate']['sha256'])
        a=read_bound_json(Path(evidence['audit']['path']));f=read_bound_json(Path(evidence['force']['path']))
        m=read_bound_json(Path(evidence['measurements']['path']));d=read_bound_json(Path(evidence['delivery']['path']))
        gates=dict(independent_final=v['complete'] and v['positive'],original_task=r['task_passed'] and all(r['gates'].values()),
            original_init=r['checkpoint_continuation']['fresh_original_initialization'] and r['checkpoint_continuation']['exact_state_restore_count']==0,
            control=a['task_passed'],orientation=m['additional_upright_quality_passed'],
            force=max(f[k] for k in ('maximum_hand_and_desk_force_error_n','maximum_static_capacity_error','maximum_slip_error_m_s'))<1e-8,
            exported=d['mechanically_qualified'] and 'episode' in evidence,
            video=d['all_decoded_frames']==(r['physics_steps']+3)//4,
            visual=v['primary_visual_observations']['sampled_actual_frames_reviewed'],
            development_scope=c['source_role']=='development_validation' and c['dataset_split']=='unassigned')
        if 'replay' in evidence:
            replay=read_bound_json(Path(evidence['replay']['path']))
            gates['continuous_replay']=bool(replay['passed'] and replay['no_numerical_warnings'] and replay['initializations']==1 and replay['intermediate_state_injections']==0 and max(replay['maximum_absolute_error'].values())==0)
        else:gates['continuous_replay']=False
        reasons.extend(case+':'+k for k,value in gates.items() if not value)
        receipts.append(dict(case_id=case,gates=gates,verification=_file_binding(path),model_sha256=r['model']['sha256'],
            strategy_sha256=p['candidate']['sha256'],**identity(r['protocol'],r['case'])))
    if set(required_cases)!=seen:reasons.append('declared_scope_incomplete')
    if len(strategies)!=1:reasons.append('not_one_frozen_strategy')
    if not required_cases:reasons.append('empty_declared_scope')
    return dict(schema='independent-experience-promotion/v1',eligible=not reasons,reasons=reasons,receipts=receipts,
        qualified_scope=sorted(seen) if not reasons else [],automatic_deployment_approved=False,
        source_role='development_validation',dataset_split='unassigned',new_physics_steps=0,
        interpretation='Eligibility for a scoped complete-skill experience; no automatic deployment, generalization or training claim.')
