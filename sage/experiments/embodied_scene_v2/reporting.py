"""Complete denominators and paired tables; failures remain in planned coverage."""
from pathlib import Path
import collections,csv,json
import numpy as np
from sage.experiments.embodied_scene_v1.package import bound
from .config import ROOT,write_json
from .diagnosis import diagnose

def csv_write(path,rows):
    columns=list(dict.fromkeys(k for row in rows for k in row))
    with Path(path).open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=columns);w.writeheader();w.writerows(rows)

def summarize():
    cases=json.loads((ROOT/'cases.json').read_text());all_rows=[];failures=[];baseline=[]
    expected=[(c,'baseline') for c in cases]
    for file,label in [('SENSITIVITY_CASES.json','sensitivity'),('INJECTED_CASES.json','injected'),('VISUAL_RECHECK_CASES.json','visual_recheck')]:
        expected.extend((r['config'],label) for r in json.loads((ROOT/file).read_text()))
    for p in sorted((ROOT/'experiments').glob('repair__*/request.json')):expected.append((json.loads(p.read_text()),'repair'))
    for c,stratum in expected:
        path=ROOT/'experiments'/c['case_id']/'result.json'
        r=json.loads(path.read_text()) if path.exists() else dict(status='missing',success=False,admitted=False,engineering_success=False)
        row=dict(case_id=c['case_id'],stratum=stratum,layout_id=c['layout_id'],split=c['split'],task=c['task'],initialization=c['initialization_id'],collider=c['scene_variant'],
            status=r['status'],admitted=r.get('admitted',False),engineering_success=r.get('engineering_success',False),success=r['success'],
            physics_executed=r.get('simulation_s',0)>0,finite=r.get('finite'),
            timeout=r.get('timeout',False),goal_error_m=r.get('goal_xy_error_m'),final_speed_m_s=r.get('final_speed_m_s'),max_lift_m=r.get('max_lift_m'),
            bilateral_seconds=r.get('bilateral_seconds'),stable_seconds=r.get('stable_seconds'),forbidden_contact_pairs=len(r.get('forbidden_contact_steps',{})),
            max_robot_scene_penetration_m=r.get('max_robot_scene_penetration_m'),max_contact_penetration_m=r.get('max_contact_penetration_m'),wall_seconds=r.get('wall_seconds'),compile_seconds=r.get('compile_seconds'),
            mass_multiplier=c['mass_multiplier'],friction_multiplier=c['friction_multiplier'],result_path=str(path))
        all_rows.append(row)
        if stratum=='baseline':baseline.append(row)
        if not r['success']:
            diagnosis=diagnose(path.parent) if path.exists() else dict(labels=['resource_or_startup'],finding='missing_result')
            if path.exists():write_json(path.parent/'diagnosis.json',diagnosis)
            failures.append(dict(**row,diagnosis=diagnosis,error=r.get('error')))
    for path in sorted((ROOT/'experiments').glob('pilot*/result.json')):
        r=json.loads(path.read_text())
        if not r['success']:
            failures.append(dict(case_id=path.parent.name,stratum='interface_pilot',status=r['status'],result_path=str(path),diagnosis=dict(labels=['controller_tracking'] if r['status']=='engineering_failure' else ['task_clearance'],finding='retained interface prototype checkpoint bug' if r['status']=='engineering_failure' else 'forbidden monitor contact')))
    for path in sorted((ROOT/'services').glob('*/terminal.json')):
        r=json.loads(path.read_text())
        if r['status']=='failed':failures.append(dict(case_id=path.parent.name,stratum='service_attempt',status='failed',result_path=str(path),diagnosis=dict(labels=['resource_or_startup'],finding='See original terminal; may correspond to an already-counted pilot failure'),error=r.get('traceback')))
    attempts=[]
    for path in sorted((ROOT/'experiments').glob('*/result.json')):
        r=json.loads(path.read_text());attempts.append(dict(attempt=path.parent.name,case_id=r['task'].get('case_id'),task=r['task']['task'],status=r['status'],success=r['success'],physics_executed=r.get('simulation_s',0)>0,wall_seconds=r.get('wall_seconds'),result_path=str(path)))
    for path in sorted((ROOT/'legacy').glob('legacy__*/result.json')):
        r=json.loads(path.read_text());attempts.append(dict(attempt=path.parent.name,case_id=path.parent.name,task='legacy_five_books',status=r['status'],success=None,physics_executed=True,wall_seconds=r['wall_seconds'],result_path=str(path)))
    csv_write(ROOT/'ALL_ATTEMPTS.csv',attempts)
    csv_write(ROOT/'METRICS.csv',all_rows);write_json(ROOT/'FAILURES.json',failures)
    groups=[]
    for task in ['navigate','pick_place']:
        for split in ['development','holdout']:
            for collider in ['baseline','repaired']:
                rows=[r for r in baseline if r['task']==task and r['split']==split and r['collider']==collider]
                normal=[r for r in rows if r['admitted'] and r['engineering_success'] and r['physics_executed']]
                groups.append(dict(task=task,split=split,collider=collider,planned=len(rows),admitted=sum(r['admitted'] for r in rows),numerically_normal=len(normal),success=sum(r['success'] for r in rows),
                    physically_executed=sum(r['physics_executed'] for r in rows),preexecution_task_failure=sum(r['status']=='task_failure' and not r['physics_executed'] for r in rows),
                    engineering_failure=sum(r['status']=='engineering_failure' for r in rows),configuration_rejected=sum(r['status']=='configuration_rejected' for r in rows),missing=sum(r['status']=='missing' for r in rows),
                    planned_success_coverage=sum(r['success'] for r in rows)/len(rows) if rows else None,normal_condition_success_rate=sum(r['success'] for r in normal)/len(normal) if normal else None))
    pairs=[]
    for c in cases:
        if c['scene_variant']!='baseline':continue
        a=next(r for r in baseline if r['case_id']==c['case_id']);b=next(r for r in baseline if r['case_id']==c['case_id'].replace('__C0','__C1'))
        pairs.append(dict(layout_id=c['layout_id'],initialization=c['initialization_id'],task=c['task'],split=c['split'],C0_success=a['success'],C1_success=b['success'],success_difference=int(b['success'])-int(a['success']),C0_goal_error_m=a['goal_error_m'],C1_goal_error_m=b['goal_error_m']))
    csv_write(ROOT/'PAIRED_COLLIDER_RESULTS.csv',pairs)
    continuous=[]
    for task in ['navigate','pick_place']:
        for metric in ['goal_error_m','max_robot_scene_penetration_m','wall_seconds','compile_seconds']:
            values=[r for r in baseline if r['task']==task and r[metric] is not None]
            a=np.array([r[metric] for r in values]);worst=max(values,key=lambda r:r[metric]) if values else None
            if len(a):continuous.append(dict(task=task,metric=metric,count=len(a),median=float(np.median(a)),q25=float(np.quantile(a,.25)),q75=float(np.quantile(a,.75)),maximum=float(a.max()),worst_case=worst['case_id']))
    csv_write(ROOT/'CONTINUOUS_METRICS.csv',continuous)
    repairs=[]
    for path in sorted((ROOT/'repairs').glob('*/result.json')):
        group=json.loads(path.read_text())
        repairs.append(dict(group_id=group['group_id'],stratum=group['stratum'],split=group['split'],method='F',retained=False,candidate_attempts=0,physical_searches=0,validation_count=0,validation_success=0,translation_m=0,edited_objects=0,comment='Filtering coverage 0 for selected I0 failures; do not rank retained success alone'))
        for m in group['methods']:
            selected=m['selected'];repairs.append(dict(group_id=group['group_id'],stratum=group['stratum'],split=group['split'],method=m['method'],retained=True,candidate_attempts=len(m['evaluated']),physical_searches=sum(e['result'] is not None and e['result'].get('simulation_s',0)>0 for e in m['evaluated']),validation_count=len(m['validation']),validation_success=sum(v['result']['success'] for v in m['validation']),translation_m=selected['translation_norm_m'] if selected else 0,edited_objects=selected['edited_objects'] if selected else 0,selected_candidate_success=next((e['result']['success'] for e in m['evaluated'] if selected and e['proposal']['index']==selected['index'] and e['result'] is not None),False),refusal=m.get('refusal'),comment='I1/I2 unseen in candidate selection; injected pre-repair I1/I2 not separately executed'))
    for row in repairs:
        if row['method']=='F':
            row.update(search_wall_seconds=0,validation_wall_seconds=0,rotation_degrees=0,collision_geometry_changed=False,collision_complexity_delta=0)
            continue
        group=json.loads((ROOT/'repairs'/row['group_id']/'result.json').read_text())
        method=next(m for m in group['methods'] if m['method']==row['method'])
        row.update(static_candidate_rejections=sum(e['result'] is None for e in method['evaluated']),initial_state_rejections=sum(e['result'] is not None and e['result']['status']=='configuration_rejected' for e in method['evaluated']),search_wall_seconds=sum(e['result']['wall_seconds'] for e in method['evaluated'] if e['result']),validation_wall_seconds=sum(v['result']['wall_seconds'] for v in method['validation']),rotation_degrees=method['selected']['rotation_degrees'] if method['selected'] else 0,collision_geometry_changed=False,collision_complexity_delta=0,collision_volume_delta_m3=0,selected_original_relations_passed=method['selected']['legality']['accepted'] if method['selected'] else None,visual_transform_policy='unchanged source assets follow the same rigid object transforms as colliders')
    csv_write(ROOT/'REPAIR_COMPARISON.csv',repairs)
    diagnosis_counts=collections.Counter(label for f in failures for label in f['diagnosis']['labels'])
    summary=dict(baseline_planned=96,baseline_realized=len(cases),baseline_results=len(baseline),baseline_success=sum(r['success'] for r in baseline),groups=groups,continuous=continuous,collider_pairs=pairs,paired_success_changes=collections.Counter(p['success_difference'] for p in pairs),repair_rows=repairs,
        strata={s:dict(planned=sum(r['stratum']==s for r in all_rows),success=sum(r['stratum']==s and r['success'] for r in all_rows),statuses=dict(collections.Counter(r['status'] for r in all_rows if r['stratum']==s))) for s in sorted(set(r['stratum'] for r in all_rows))},diagnosis_counts=dict(diagnosis_counts),scope='Eight same-bedroom layouts; descriptive paired results, not cross-room generalization',confidence_intervals='not estimated; only eight layout clusters')
    write_json(ROOT/'SUMMARY.json',summary)
    print('Summary',summary['strata'],flush=True)
