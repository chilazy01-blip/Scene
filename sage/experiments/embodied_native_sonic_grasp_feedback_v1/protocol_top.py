"""Freeze axis-derived reference and exact earlier prefix inside remaining budget."""
import argparse,time
from pathlib import Path
import numpy as np
from .protocol_damped import authorize as previous,check,project_target
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding

def authorize(root):
    p=previous(root);v=read_bound_json(root/'TOP_PROTOCOL.json')
    for b in [v['previous_protocol'],v['case'],v['screen'],v['approach_check'],v['prefix_report'],v['prefix_trace'],v['prefix_io'],*v['dependencies'].values()]:check(b)
    p=dict(p);p.update(case=v['case'],full_ticks=v['full_ticks'],prefix_physics_steps=3200,prefix_active_ticks=790);return p

def reserve(root,output,ceiling):
    p=authorize(root);assert time.time()<p['deadline_epoch_utc'];l=read_bound_json(root/'COST.json');replay=output.name.startswith('continuous_replay')
    if replay:charged=output;maximum=ceiling;headroom=0
    else:
        assert output==root/'attempt_04/full' and ceiling==40+4*p['full_ticks'];charged=output.parent/'cost';maximum=ceiling-3200;headroom=ceiling
    assert not any(x['output']==str(charged) for x in l['reservations']);spent=sum(read_bound_json(Path(x['output'])/'REPORT.json')['physics_steps'] if (Path(x['output'])/'REPORT.json').exists() else x['maximum_steps'] for x in l['reservations'])
    assert spent+maximum+headroom<=p['max_new_physics_steps'] and p['prior_native_steps']+spent+maximum+headroom<=p['cumulative_native_cap']
    l['reservations'].append(dict(output=str(charged),maximum_steps=maximum,episode_output=str(output),success_replay_headroom=headroom));safe_save(root/'COST.json',l)

def freeze(root):
    p=previous(root);assert not (root/'TOP_PROTOCOL.json').exists();s=read_bound_json(root/'AXIS_TOP_REFERENCE_CHECK_R2.json');candidates=[x for x in s['candidates'] if x['eligible']];c=min(candidates,key=lambda x:x['maximum_vertical_normal']);approach=read_bound_json(root/'TOP_APPROACH_CHECK.json');assert approach['passed']
    case=read_bound_json(Path(p['case']['path']));case.update(grasp_local_xyz_m=c['offset_world_m'],repair_grasp_local_xyz_m=c['offset_world_m'],loaded_grasp_rotation=c['rotation'],loaded_preload_targets_n={g:max(.5,n) for g,n in c['preload']['required_group_normal_n'].items()},top_nominal_closure=c['closure'],top_reference_screen=_file_binding(root/'AXIS_TOP_REFERENCE_CHECK_R2.json'),top_reference_note='Native cylinder axis and tripod plane aligned; vertical open approach10cm; persistent native finger PD targets. Static preload uses capacity and bounded resultant,10mm real load trial determines transfer. Original real10mm penetration gate unchanged.')
    safe_save(root/'CASE_TOP.json',case)
    source=Path('/data/wsj/main/scene_runs/codex_trellis_v2/embodied_native_sonic_transport_20261022_v1/version_04/full');t=read_bound_json(source/'TRACE.json');assert len(t['records'])==790;t['checkpoint_continuation']=dict(source_trace=_file_binding(source/'TRACE.json'),prefix_physics_steps=3200,prefix_active_ticks=790,prepared_with_zero_integrations=True)
    folder=root/'top_prefix';folder.mkdir();safe_save(folder/'TRACE.json',t);io=np.load(source/'POLICY_IO.npz',allow_pickle=False);np.savez_compressed(folder/'POLICY_IO.npz',**{k:io[k] for k in io.files});rows=t['records'];assert all(x['safe'] for row in rows for x in row['substeps'])
    safe_save(folder/'REPORT.json',dict(schema='exact-recorded-safe-prefix/v1',physics_steps=3200,new_physics_steps=0,maximum_saturation_run_ticks=np.max([r['projection']['saturation_run_ticks'] for r in rows],axis=0).tolist(),maximum_target_projection_rad=max(r['projection']['maximum_projection_rad'] for r in rows),projected_ticks=sum(bool(r['projection']['projected_joints']) for r in rows),source_report=_file_binding(source/'REPORT.json'),source_trace=_file_binding(source/'TRACE.json')))
    ledger=read_bound_json(root/'COST.json');spent=sum(read_bound_json(Path(x['output'])/'REPORT.json')['physics_steps'] for x in ledger['reservations']);F=((p['max_new_physics_steps']-spent+3200)//2)//4*4
    safe_save(root/'TOP_PROTOCOL.json',dict(previous_protocol=_file_binding(root/'DAMPED_WRIST_PROTOCOL.json'),case=_file_binding(root/'CASE_TOP.json'),screen=_file_binding(root/'AXIS_TOP_REFERENCE_CHECK_R2.json'),approach_check=_file_binding(root/'TOP_APPROACH_CHECK.json'),prefix_report=_file_binding(folder/'REPORT.json'),prefix_trace=_file_binding(folder/'TRACE.json'),prefix_io=_file_binding(folder/'POLICY_IO.npz'),full_ticks=(F-40)//4,budget_proof=dict(spent=spent,new_suffix_max=F-3200,full_replay_max=F,total_new_max=spent+2*F-3200,cumulative_max=p['prior_native_steps']+spent+2*F-3200),selected=c,unchanged_deadline=p['deadline_epoch_utc'],dependencies={x.name:_file_binding(x) for x in Path(__file__).parent.glob('*.py')}));print(dict(frozen=True,full_ticks=(F-40)//4,spent=spent),flush=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);freeze(ap.parse_args().root)
