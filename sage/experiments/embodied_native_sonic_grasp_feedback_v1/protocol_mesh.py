"""Actual native-mesh planned grasp inside approved75000 cap and original task."""
import argparse,time
from pathlib import Path
import numpy as np
from .protocol_early import authorize as previous,check,project_target
from .protocol import read_bound_json,safe_save,_file_binding
from .mesh_hand_reference import from_shape

def authorize(root):
    p=previous(root);v=read_bound_json(root/'NATIVE_MESH_PROTOCOL.json')
    for b in [v['previous_protocol'],v['case'],v['mesh_plan'],v['path_check'],v['geometry_correction'],v['tests'],v['prefix_report'],v['prefix_trace'],v['prefix_io'],*v['dependencies'].values()]:check(b)
    p=dict(p);p.update(case=v['case'],full_ticks=v['full_ticks'],prefix_physics_steps=3200,prefix_active_ticks=790);return p

def reserve(root,output,ceiling):
    p=authorize(root);assert time.time()<p['deadline_epoch_utc'];l=read_bound_json(root/'COST.json');replay=output.name.startswith('continuous_replay')
    if replay:charged=output;maximum=ceiling;headroom=0
    else:
        assert output==root/'attempt_09/full' and ceiling==40+4*p['full_ticks'];charged=output.parent/'cost';maximum=ceiling-3200;headroom=ceiling
    assert not any(x['output']==str(charged) for x in l['reservations']);spent=sum(read_bound_json(Path(x['output'])/'REPORT.json')['physics_steps'] if (Path(x['output'])/'REPORT.json').exists() else x['maximum_steps'] for x in l['reservations'])
    assert spent+maximum+headroom<=p['max_new_physics_steps'] and p['prior_native_steps']+spent+maximum+headroom<=p['cumulative_native_cap']
    l['reservations'].append(dict(output=str(charged),maximum_steps=maximum,episode_output=str(output),success_replay_headroom=headroom));safe_save(root/'COST.json',l)

def freeze(root):
    p=previous(root);assert not (root/'NATIVE_MESH_PROTOCOL.json').exists();plan=read_bound_json(root/'NATIVE_MESH_GRASP_PLAN.json');selected=plan['selected'];path=read_bound_json(root/'NATIVE_MESH_PATH_CHECK.json');assert selected and selected['eligible'] and path['passed'] and plan['actual_model_unchanged'];tests=root/'MESH_REFERENCE_TESTS.xml';assert 'failures="0"' in tests.read_text() and 'errors="0"' in tests.read_text();template,touch=from_shape(selected['finger_joint_names'],selected['finger_angles_rad']);case=read_bound_json(Path(p['case']['path']))
    case.update(grasp_local_xyz_m=selected['offset_world_m'],repair_grasp_local_xyz_m=selected['offset_world_m'],loaded_grasp_rotation=selected['rotation'],loaded_preload_targets_n={g:max(.5,n) for g,n in selected['actual_native_geometry']['preload']['required_group_normal_n'].items()},mesh_finger_template=template,mesh_touch_closures=touch,mesh_planned_finger_angles_rad=dict(zip(selected['finger_joint_names'],selected['finger_angles_rad'])),mesh_grasp_plan=_file_binding(root/'NATIVE_MESH_GRASP_PLAN.json'),geometry_basis='Actual native mesh vertices and native signed contact queries. No capsule approximation. Physical engine uses original model unchanged; query-margin copy is never integrated or used for control.',loaded_reference_floor='Capture current persistent group targets upon actual capacity qualification; monotonic reference floor until explicit release, with original native halfclosed/rate/gain/effort limits.',feedback_control='Measured normal-force group admittance on the native-mesh planned finger shape; raw actual capacity/slip qualification15ticks triggers diagnostic10mm load. Strict postload,1s off-table hold, real both-foot carry, place/release and continuous original-init replay remain required.',top_reference_note='Open native-mesh approach10cm, descend5cm then to goal; no capsule-plane/radius assumptions.')
    safe_save(root/'CASE_NATIVE_MESH.json',case);folder=root/'top_prefix';r=read_bound_json(folder/'REPORT.json');assert r['physics_steps']==3200
    l=read_bound_json(root/'COST.json');spent=sum(read_bound_json(Path(x['output'])/'REPORT.json')['physics_steps'] for x in l['reservations']);F=9040;assert p['prior_native_steps']+spent+2*F-3200<=75000
    safe_save(root/'NATIVE_MESH_PROTOCOL.json',dict(previous_protocol=_file_binding(root/'EARLY_GRIP_PROTOCOL.json'),case=_file_binding(root/'CASE_NATIVE_MESH.json'),mesh_plan=_file_binding(root/'NATIVE_MESH_GRASP_PLAN.json'),path_check=_file_binding(root/'NATIVE_MESH_PATH_CHECK.json'),geometry_correction=_file_binding(root/'NATIVE_MESH_GEOMETRY_CORRECTION.json'),tests=_file_binding(tests),prefix_report=_file_binding(folder/'REPORT.json'),prefix_trace=_file_binding(folder/'TRACE.json'),prefix_io=_file_binding(folder/'POLICY_IO.npz'),full_ticks=(F-40)//4,budget_proof=dict(spent=spent,new_suffix_max=F-3200,full_replay_max=F,projected_native_max=p['prior_native_steps']+spent+2*F-3200),unchanged_deadline=p['deadline_epoch_utc'],actual_engine_uses_original_model_no_query_margin=True,dependencies={x.name:_file_binding(x) for x in Path(__file__).parent.glob('*.py')}));print(dict(frozen=True,full_ticks=(F-40)//4,spent=spent,projected_native_max=p['prior_native_steps']+spent+2*F-3200),flush=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);freeze(ap.parse_args().root)
