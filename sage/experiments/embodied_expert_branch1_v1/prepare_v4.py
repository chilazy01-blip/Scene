import re
import shutil
from pathlib import Path
from .common import ROOT,PREVIOUS,PACKAGE,read_bound_json,safe_save,_file_binding
from .guard import check_source
from .common import check


def run(strategy,case_id,name):
    plan=read_bound_json(ROOT/'PLAN_v2.json');auth=read_bound_json(ROOT/'AUTHORIZATION.json')
    if case_id not in plan['cases'] or not re.fullmatch('[A-Za-z0-9_]{1,64}',name):raise ValueError('unknown case or invalid name')
    registry=read_bound_json(ROOT/'CASE_ADMISSION_REGISTRY.json')
    binding=registry['cases'][case_id]
    if binding is None:raise ValueError('case numerical admission pending')
    check(binding)
    admission=read_bound_json(Path(binding['path']))
    if not admission['passed']:raise ValueError('case failed static admission')
    strategy=Path(strategy).resolve();allowed=(ROOT/'workbench/strategies').resolve()
    if not strategy.is_relative_to(allowed) or strategy.suffix!='.py':raise ValueError('strategy outside workbench')
    check_source(strategy.read_text())
    trial=ROOT/'trials'/name;trial.mkdir(parents=True,exist_ok=False)
    frozen=trial/'strategy.py';shutil.copyfile(strategy,frozen)
    check(admission['case']);shutil.copyfile(admission['case']['path'],trial/'CASE.json')
    previous=read_bound_json(PREVIOUS/'target_y_minus_30mm/baseline_v2/PROTOCOL.json')
    dependencies=dict(previous['dependencies'])
    dependencies.update({'expert_branch1_v1/'+f.name:_file_binding(f) for f in PACKAGE.glob('*.py')})
    p=dict(schema='generated-grasp-code-protocol/v1',authorization=_file_binding(ROOT/'AUTHORIZATION.json'),plan=_file_binding(ROOT/'PLAN_v2.json'),case=_file_binding(trial/'CASE.json'),candidate=_file_binding(frozen),scene=admission['scene'],reference=admission['reference'],inputs=previous['inputs'],dependencies=dependencies,prefix_active_ticks=0,prefix_physics_steps=0,full_ticks=3200,ledger_root=str(ROOT),prior_native_steps=239138,max_new_physics_steps=120000,cumulative_native_cap=359138,deadline_epoch_utc=auth['deadline_epoch_utc'],solver_schedule=previous['solver_schedule'],active_source='codex_expert/phase_contract_scoped_memory_branch1',arm='expert_code',paired_case_id=case_id,all_original_physical_and_task_gates_preserved=True,shared_prefix_not_independent_sample=False,static_admission=binding,case_admission_registry=_file_binding(ROOT/'CASE_ADMISSION_REGISTRY.json'))
    p['branch_one_evidence']={f.name:_file_binding(f) for f in (ROOT/'workbench/context').glob('*.json')}
    p['branch_one_evidence']['expert_contract']=_file_binding(ROOT/'workbench/EXPERT_CONTRACT.md')
    safe_save(trial/'PROTOCOL.json',p)
    print(dict(prepared=str(trial),candidate=p['candidate'],case=case_id),flush=True)
    return trial
