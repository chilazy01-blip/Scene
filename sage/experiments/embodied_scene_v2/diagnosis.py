"""Evidence-only attribution. The diagnostic interface excludes fault labels."""
from pathlib import Path
import json,gzip
import numpy as np

LABELS=['initial_configuration','collision_representation','task_clearance','planner_conservative_or_no_path','ik_reachability','controller_tracking','contact_or_physical_sensitivity','numerical_solver','resource_or_startup','unknown']

def scene_contact_evidence(episode):
    episode=Path(episode);mapping=episode/'contact_geom_mapping.json'
    if not mapping.exists():return []
    m=json.loads(mapping.read_text());owners={int(k):v for k,v in m['owners'].items()};names={int(k):v for k,v in m['names'].items()}
    c=json.loads((episode/'request.json').read_text());rows={}
    for file in sorted(episode.glob('contacts_1khz_*.jsonl.gz')):
        with gzip.open(file,'rt') as stream:
            for line in stream:
                for contact in json.loads(line)['contacts']:
                    if contact['force'][0]<=1e-6:continue
                    a,b=contact['g'];pair=[owners[a],owners[b]];kind=None;other=None
                    if 'task_book' in pair:
                        other=pair[1-pair.index('task_book')]
                        if other not in ('base','base_link','task_book',c['support_owner'],'world'):kind='target_obstacle'
                    elif any(owner in ('base','base_link') for owner in pair):
                        k=next(i for i,v in enumerate(pair) if v in ('base','base_link'));other=pair[1-k];g=[a,b][1-k]
                        if other not in c['allowed_robot_contact_owners'] and names[g] not in c['allowed_robot_contact_geoms']:kind='robot_obstacle'
                    if kind:
                        row=rows.setdefault((other,kind),dict(object_id=other,kind=kind,active_contact_samples=0,normal_impulse_n_s=0.))
                        row['active_contact_samples']+=1;row['normal_impulse_n_s']+=contact['force'][0]*c['dt_s']
    return sorted(rows.values(),key=lambda r:(-r['normal_impulse_n_s'],r['object_id']))

def diagnose(episode):
    episode=Path(episode);r=json.loads((episode/'result.json').read_text());labels=[];evidence=[]
    if r['success']:return dict(labels=[],finding='task_passed',evidence=[],fault_truth_accessed=False)
    error=r.get('error','')
    if r['status']=='configuration_rejected':labels.append('initial_configuration');evidence.append(error)
    elif 'clearance' in error or 'path' in error:labels.append('planner_conservative_or_no_path');evidence.append(error)
    elif 'IK' in error:labels.append('ik_reachability');evidence.append(error)
    elif r.get('engineering_success') is False:
        labels.append('numerical_solver' if r.get('warning_counts') or r.get('finite') is False else 'resource_or_startup');evidence.append(error or 'Engineering state/restore check rejected')
    if r.get('forbidden_contact_steps'):
        labels.append('task_clearance');evidence.append(dict(forbidden_contacts=r['forbidden_contact_steps']))
    target_obstacles=[row for row in scene_contact_evidence(episode) if row['kind']=='target_obstacle']
    if target_obstacles:
        labels.append('task_clearance');evidence.append(dict(actual_target_obstacle_contacts=target_obstacles))
    if r.get('task',{}).get('controller_gain_multiplier',1)!=1:
        labels.append('controller_tracking');evidence.append(dict(observed_controller_gain_multiplier=r['task']['controller_gain_multiplier'],reference_multiplier=1,source='declared controller input, not injection truth'))
    if r.get('task',{}).get('task')=='pick_place' and not error:
        if r.get('max_lift_m',0)<.08 or r.get('bilateral_seconds',0)<=.05:
            labels.extend(['controller_tracking','contact_or_physical_sensitivity']);evidence.append(dict(max_lift=r.get('max_lift_m'),bilateral_seconds=r.get('bilateral_seconds')))
    if not labels:labels=['unknown']
    return dict(labels=sorted(set(labels)),finding='multiple_candidates' if len(set(labels))>1 else 'evidence_supported_candidate',evidence=evidence,fault_truth_accessed=False,certainty='diagnostic hypothesis; controlled comparison required',allowed_inputs=['result task/metrics/error','trajectory','geometry','contacts'])
