import re
import shutil
from pathlib import Path
import numpy as np
from .common import ROOT,PREVIOUS,ORIGINAL,PACKAGE,read_bound_json,safe_save,_file_binding,check
from .guard import check_source


def run(strategy,case_id,name):
    plan=read_bound_json(ROOT/'PLAN.json');auth=read_bound_json(ROOT/'AUTHORIZATION.json')
    if case_id not in plan['cases'] or not re.fullmatch('[A-Za-z0-9_]{1,64}',name):raise ValueError('unknown case or invalid unique trial name')
    strategy=Path(strategy).resolve();allowed=(ROOT/'workbench/strategies').resolve()
    if not strategy.is_relative_to(allowed) or strategy.suffix!='.py':raise ValueError('strategy must be a workbench strategy.py')
    check_source(strategy.read_text())
    trial=ROOT/'trials'/name;trial.mkdir(parents=True,exist_ok=False)
    frozen=trial/'strategy.py';shutil.copyfile(strategy,frozen)
    previous=read_bound_json(PREVIOUS/'target_y_minus_30mm/baseline_v2/PROTOCOL.json')
    case=read_bound_json(ORIGINAL/'trial_07/CASE.json')
    case.pop('codex_reference_proposal',None)
    case.update(case_id=case_id+'/'+name,target_object_xyz_m=(np.asarray(case['target_object_xyz_m'])+plan['cases'][case_id]).tolist(),source_role='development_validation',dataset_split='unassigned')
    safe_save(trial/'CASE.json',case)
    dependencies=dict(previous['dependencies'])
    dependencies.update({'expert_v2/'+f.name:_file_binding(f) for f in PACKAGE.glob('*.py')})
    p=dict(schema='codex-expert-code-protocol/v2',authorization=_file_binding(ROOT/'AUTHORIZATION.json'),plan=_file_binding(ROOT/'PLAN.json'),
        case=_file_binding(trial/'CASE.json'),candidate=_file_binding(frozen),scene=previous['scene'],reference=previous['reference'],inputs=previous['inputs'],dependencies=dependencies,
        prefix_report=previous['prefix_report'],prefix_trace=previous['prefix_trace'],prefix_io=previous['prefix_io'],prefix_active_ticks=1597,prefix_physics_steps=6428,
        prefix_video=_file_binding(ORIGINAL/'trial_07/actual_video/motion.mp4'),
        full_ticks=2800,ledger_root=str(ROOT),prior_native_steps=91644,max_new_physics_steps=64000,cumulative_native_cap=155644,
        deadline_epoch_utc=auth['deadline_epoch_utc'],solver_schedule=previous['solver_schedule'],
        active_source='codex_generated_expert_code/v2',arm='expert_code',paired_case_id=case_id,
        all_original_physical_and_task_gates_preserved=True,shared_prefix_not_independent_sample=True)
    safe_save(trial/'PROTOCOL.json',p)
    print(dict(prepared=str(trial),candidate=p['candidate'],case=case_id),flush=True)
    return trial
