"""Raw evidence recomputation and native-model admission for surface task v1."""
from pathlib import Path
import numpy as np
from sage.experiments.embodied_scene_quality_v2.contracts import (
    read,read_ref,bound,reference,require,fingerprint,digest,decisions,write_new)
from sage.experiments.embodied_scene_quality_v2.geometry import fidelity,fidelity_passed
from .physics import evaluate,numerical_comparison


def binding_context(package):
    binding=read_ref(package)
    require(binding['schema']=='task-conditioned-binding/v1','binding_schema')
    for ref in list(binding['files'].values())+list(binding['sources'].values()):bound(ref['path'],ref['sha256'])
    task=read_ref(binding['files']['task.json'])
    require(task['schema']=='task-conditioned-release/v1','task_schema')
    return binding,task


def trace_context(ref,task,protocol,binding_sha,initials,purpose,key):
    attempt=read_ref(ref);initial=read_ref(attempt['initial'])
    require(attempt['binding_sha256']==binding_sha,'attempt_binding_mismatch')
    require(attempt['case']==key and attempt['purpose']==purpose,'attempt_scope_mismatch')
    require(initial==initials['cases'][key] and fingerprint(initial)==attempt['initial_sha256'],'frozen_initial_mismatch')
    dt=protocol['physics']['refined_dt_s'] if purpose=='refinement' else protocol['physics']['base_dt_s']
    require(attempt['dt_s']==dt,'timestep_mismatch')
    require(attempt['description']['timestep_s']==dt,'native_timestep_mismatch')
    require(attempt['description']['mass_kg']==task['physical_prior']['mass_kg'],'native_mass_mismatch')
    require(np.allclose(attempt['description']['inertia'],task['physical_prior']['inertia_body_kg_m2'],rtol=1e-9,atol=1e-12),'native_inertia_mismatch')
    raw=dict(np.load(bound(attempt['raw']['path'],attempt['raw']['sha256']),allow_pickle=False))
    return raw,evaluate(raw,initial,attempt,task,protocol)


def recompute(evidence):
    require(evidence['schema']=='task-conditioned-evidence/v1','evidence_schema')
    protocol=read_ref(evidence['protocol']);binding,task=binding_context(evidence['package'])
    require(binding['protocol_sha256']==fingerprint(protocol),'protocol_binding_mismatch')
    for ref in evidence['implementation'].values():bound(ref['path'],ref['sha256'])
    require(task['request'] in protocol['requests'],'unregistered_request')
    geometry=dict(np.load(bound(binding['files']['GEOMETRY_RAW.npz']['path'],binding['files']['GEOMETRY_RAW.npz']['sha256']),allow_pickle=False))
    support=fidelity(geometry['source_height'],geometry['proxy_height']);target=fidelity(geometry['target_source'],geometry['target_proxy'])
    geometry_ok=fidelity_passed(support,protocol['geometry']) and target['height_abs_p95_m'] is not None and target['height_abs_p95_m']<=protocol['geometry']['target_hull_underside_p95_m_max']
    initials=read_ref(evidence['initials']);require(initials['protocol_sha256']==fingerprint(protocol),'initial_protocol_mismatch')
    require(set(initials['cases'])=={c['key'] for c in protocol['cases']},'initial_scope_mismatch')
    results={};raws={};binding_sha=evidence['package']['sha256']
    for key,ref in evidence['primary'].items():
        require(key in initials['cases'],'unregistered_primary')
        raws[key],results[key]=trace_context(ref,task,protocol,binding_sha,initials,'primary',key)
    complete=set(results)=={c['key'] for c in protocol['cases']}
    dynamic=all(r['passed'] for r in results.values()) if complete else None
    numerical={}
    for purpose in ('refinement','replay'):
        if purpose not in evidence['numerical']:continue
        key=protocol['numerical'][purpose+'_case'];require(key in raws,'numerical_without_primary')
        raw,value=trace_context(evidence['numerical'][purpose],task,protocol,binding_sha,initials,purpose,key)
        numerical[purpose]=numerical_comparison(raws[key],raw,results[key],value,protocol,replay=purpose=='replay')
    numerical_ok=all(v['passed'] for v in numerical.values()) if set(numerical)=={'refinement','replay'} else None
    state=lambda b:'unknown' if b is None else 'pass' if b else 'fail'
    metrics={k:dict(state=state(v)) for k,v in dict(input_binding=True,geometry_fidelity=geometry_ok,
        dynamic_release=dynamic,numerical_reliability=numerical_ok,primitive_task_feasibility=dynamic,
        full_robot_task=None,observation_export=None).items()}
    return dict(request_id=task['request']['id'],scope=protocol['scope'],task=task['request'],
        metrics=metrics,decisions=decisions(metrics),geometry=dict(support=support,target=target),primary=results,numerical=numerical)


def collect_evidence(config,protocol_path):
    config=Path(config);here=Path(__file__).parent
    implementation={str(p):reference(p) for p in sorted(here.glob('*.py'))}
    for parent in ['embodied_scene_quality_v1','embodied_scene_quality_v2']:
        implementation.update({str(p):reference(p) for p in sorted((here.parent/parent).glob('*.py'))})
    primary={p.parent.name:reference(p) for p in sorted((config/'physics/primary').glob('*/ATTEMPT.json'))}
    numerical={kind:reference(config/'physics'/kind/'ATTEMPT.json') for kind in ('refinement','replay') if (config/'physics'/kind/'ATTEMPT.json').exists()}
    return dict(schema='task-conditioned-evidence/v1',protocol=reference(protocol_path),package=reference(config/'package/BINDING.json'),
        implementation=implementation,initials=reference(config/'INITIAL_STATES.json'),primary=primary,numerical=numerical)


def open_task(evidence_path,expected_sha,purpose,expected_request_id):
    evidence=read(bound(evidence_path,expected_sha));result=recompute(evidence)
    require(result['request_id']==expected_request_id,'request_identity_mismatch')
    require(purpose in result['decisions'],'unknown_purpose')
    require(result['decisions'][purpose]['qualified'],'purpose_rejected:'+','.join(result['decisions'][purpose]['reasons']))
    binding,task=binding_context(evidence['package'])
    import mujoco
    path=bound(binding['files']['model.mjb']['path'],binding['files']['model.mjb']['sha256'])
    model=mujoco.MjModel.from_binary_path(str(path))
    require(model.nq==7 and model.nv==6 and model.nu==0,'native_layout_mismatch')
    return model,result
