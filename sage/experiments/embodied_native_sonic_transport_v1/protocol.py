"""Fresh bounded user-authorized SONIC29 native pickup/carry/place round."""
import argparse,time
from pathlib import Path
from sage.experiments.embodied_native_object_transport_v1.protocol_v5 import authorize as authorize_parent
from sage.experiments.embodied_native_object_transport_v1.protocol_v4 import check,project_target
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding


def authorize(root):
    p=read_bound_json(root/'PROTOCOL.json');assert p['schema']=='native-sonic29-task/v1'
    for b in [p['parent_round'],p['handoff'],p['case'],p['scene'],p['reference'],*p['inputs'].values(),*p['dependencies'].values()]:check(b)
    authorize_parent(Path(p['parent_root']))
    return p


def reserve(root,output,ceiling):
    p=authorize(root)
    if time.time()>=p['deadline_epoch_utc']:raise RuntimeError('SONIC29 round deadline reached')
    relative=output.relative_to(root).as_posix()
    allowed=[f'version_0{i}/{stage}' for i in (1,2,3) for stage in ('admission','full')]+['continuous_replay']
    assert relative in allowed
    if relative.startswith(('version_02','version_03')):
        number=int(relative.split('/')[0][-2:]);revision=read_bound_json(root/f'VERSION_0{number}_PROTOCOL.json')
        assert revision['version']==number
        for b in revision['dependencies'].values():check(b)
    ledger=read_bound_json(root/'COST.json')
    assert not any(r['output']==str(output) for r in ledger['reservations'])
    spent=0
    for r in ledger['reservations']:
        result=Path(r['output'])/'REPORT.json'
        spent+=read_bound_json(result)['physics_steps'] if result.exists() else r['maximum_steps']
    if spent+ceiling>p['max_new_physics_steps'] or p['prior_native_steps']+spent+ceiling>p['cumulative_native_cap']:
        raise RuntimeError('bounded SONIC29 physics budget exhausted')
    ledger['reservations'].append(dict(output=str(output),maximum_steps=ceiling,reserved_at_epoch_utc=time.time()))
    safe_save(root/'COST.json',ledger)


def freeze(root,parent):
    assert not (root/'PROTOCOL.json').exists()
    previous=authorize_parent(parent);root.mkdir(parents=True,exist_ok=True)
    handoff=root/'HANDOFF_BEFORE.md';assert not handoff.exists();handoff.write_bytes((Path(__file__).parents[3]/'AGENT.md').read_bytes())
    case=read_bound_json(Path(previous['case']['path']));case['parent_case']=previous['case']
    case['stage_timeouts_ticks']=dict(case['stage_timeouts_ticks'],ready_arm=500)
    case['body_control']='SONIC29; right-arm IK creates reference only; no independent arm actuation'
    safe_save(root/'CASE.json',case)
    p=dict(previous)
    p.update(schema='native-sonic29-task/v1',parent_root=str(parent),parent_round=_file_binding(parent/'ROUND_REVIEW.json'),
        handoff=_file_binding(handoff),case=_file_binding(root/'CASE.json'),
        user_authorization_verbatim='我认为在机器人控制方面可以将大部分控制权先交由sonic去处理。就按照你说的：给 SONIC 合适的操作参考，让它统一控制全身吧，实现的任务还是我们目前的这个任务',
        control='SONIC v1.1 g1-mode full29 joint references -> encoder64token -> decoder29 -> legal range projection -> original PD/effort; active body feedforward0; original separate finger closure',
        reference_semantics='10 full29-joint frames, step5 at50Hz with heading-normalized orientation; inactive SMPL/VR blocks zero, same matched v1.1 encoder/decoder/config',
        bottleneck='independent arm override forfeits learned whole-body arm coordination; hand-authored raise paths collide',
        deliverable='all29 SONIC control ownership plus collision-screened operation references, independently reconstructed real native complete-or-failed task and MP4',
        start_epoch_utc=time.time(),deadline_epoch_utc=time.time()+7200,max_new_physics_steps=30000,
        prior_native_steps=28097,cumulative_native_cap=60000,max_causal_versions=3,
        simulation_dt_s=.005,control_dt_s=.02,full_ticks=3000,admission_ticks=100,
        admission_policy='fresh SONIC29 100tick admission per control revision; full run must exactly reproduce its own admission, never reuse prior SONIC22 prefix',
        planning_budget='deterministic seed20261022, max4000 collision evaluations per raise path; no integrations in planner; max400reference ticks',
        failure_policy='retain every actual step and rejected command/failed reference path; stop measured physical fault or bounded task stall; no fabricated later stages',
        motor_gains='original frozen native gains, no untested tuning bundled with first SONIC29 revision',
        acceptance='same real mug pickup/off-table opposing contacts, >=.25m held actual steps with both feet cycles, release and settle; real video; audit and counted continuous replay before qualified export',
        no_training_download_install_commit_delegation=True,
        dependencies={f.name:_file_binding(f) for f in Path(__file__).parent.glob('*.py') if f.name!='probe.py'})
    p['limits']=dict(p['limits']);p['limits'].pop('max_raw_target_projection_rad',None)
    safe_save(root/'PROTOCOL.json',p)
    safe_save(root/'COST.json',dict(reservations=[],max_physics_steps=30000,prior_native_steps=28097,cumulative_cap=60000))
    print(dict(frozen=True,deadline_epoch_utc=p['deadline_epoch_utc'],physics_steps=0),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);ap.add_argument('--parent',type=Path,required=True);a=ap.parse_args();freeze(a.root,a.parent)
