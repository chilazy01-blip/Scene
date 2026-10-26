"""Frozen, budget-matched local translations driven by declared geometry/evidence."""
from pathlib import Path
from copy import deepcopy
import gzip,json,time,gc
import numpy as np
from sage.experiments.codex_trellis_scene_v2.validator import validate_layout
from sage.experiments.embodied_scene_v1.package import bound
from .config import ROOT,PACKAGE,write_json,digest,ledger
from .diagnosis import diagnose,scene_contact_evidence
from .runner import run

EDITABLE=['desk_monitor','desk_mug','desk_plant','desktop_tower','desk_floor_lamp','explicit_office_chair','wardrobe_storage_box']

def legal(c,changed):
    plan=json.loads((ROOT/'layouts'/c['layout_id']/'layout_plan.json').read_text());objects=json.loads((PACKAGE/'objects.json').read_text());byid={o['id']:o for o in plan['objects']}
    for name,pose in c['object_poses'].items():
        a=np.asarray(pose);byid[name].update(x=float(a[0,3]),y=float(a[1,3]),yaw=float(np.rad2deg(np.arctan2(a[1,0],a[0,0]))))
        if name in changed and byid[name].get('support_id'):
            parent=c['object_poses'].get(byid[name]['support_id'],objects[byid[name]['support_id']]['pose_z_up']);local=np.linalg.inv(np.asarray(parent))@np.r_[a[:3,3],1]
            byid[name]['support_offset']=local[:2].tolist()
    check=validate_layout(plan);issues=[v for v in check.get('violations',[]) if v.get('severity') in ('hard','soft')]
    # Rigid tabletop support check includes the rotated child footprint.
    for name in changed:
        if name not in ['desk_monitor','desk_mug','desk_plant']:continue
        parent=np.asarray(c['object_poses']['explicit_desk']);pose=np.asarray(c['object_poses'][name]);local=np.linalg.inv(parent)@pose
        half=np.asarray(objects[name]['dimensions_local_m'])/2;corners=np.array([[x,y,z] for x in [-half[0],half[0]] for y in [-half[1],half[1]] for z in [-half[2],half[2]]])
        points=corners@local[:3,:3].T+local[:3,3];limit=np.asarray(objects['explicit_desk']['dimensions_local_m'])[:2]/2
        if np.any(np.abs(points[:,:2])>limit+1e-5):issues.append(dict(type='tabletop_footprint_exits_support',object_id=name,severity='hard'))
    return dict(accepted=not issues,issues=issues,validation=check)

def contact_object(episode):
    r=json.loads((episode/'result.json').read_text());scores={}
    for pair,steps in r.get('forbidden_contact_steps',{}).items():
        for name in EDITABLE:
            if 'col_'+name in pair:scores[name]=scores.get(name,0)+steps
    for row in scene_contact_evidence(episode):
        if row['object_id'] in EDITABLE:scores[row['object_id']]=scores.get(row['object_id'],0)+row['normal_impulse_n_s']
    return sorted(scores,key=lambda k:(-scores[k],k))[0] if scores else None

def evidence_direction(episode,name,c):
    mapping=json.loads((episode/'contact_geom_mapping.json').read_text());owners={int(k):v for k,v in mapping['owners'].items()};points=[]
    for file in sorted(episode.glob('contacts_1khz_*.jsonl.gz')):
        with gzip.open(file,'rt') as f:
            for line in f:
                for contact in json.loads(line)['contacts']:
                    if name in [owners[i] for i in contact['g']] and contact['force'][0]>0:points.append(contact['position'][:2])
    center=np.asarray(c['object_poses'][name])[:2,3]
    return center-np.mean(points,axis=0) if points else center-np.asarray(c['arm_base'][:2])

def candidates(episode,c,method,diagnostic):
    # All methods use identical editable objects, translation magnitudes and gates.
    # G chooses nearest task-corridor obstacle, R samples, D uses actual contacts.
    available=[name for name in EDITABLE if name in c['object_poses']]
    if method=='D' and c['controller_gain_multiplier']!=1:return [],'refuse_scene_edit_for_known_controller_configuration'
    if method=='D':name=contact_object(episode)
    elif method=='G':
        midpoint=(np.asarray(c['start'][:2])+c['goal'][:2])/2
        name=min(available,key=lambda n:np.linalg.norm(np.asarray(c['object_poses'][n])[:2,3]-midpoint))
    else:name=None
    if method=='D' and name is None:return [],'no_local_scene_evidence'
    rng=np.random.default_rng(int(digest(dict(layout=c['layout_id'],task=c['task'],case=c['case_id'],method=method))[:16],16))
    proposals=[]
    for index,distance in enumerate([.08,.15]):
        target=str(rng.choice(available)) if method=='R' else name
        if method=='R':angle=rng.uniform(-np.pi,np.pi);direction=np.array([np.cos(angle),np.sin(angle)])
        elif method=='D':direction=evidence_direction(episode,target,c)
        else:direction=np.asarray(c['object_poses'][target])[:2,3]-c['arm_base'][:2]
        if np.linalg.norm(direction)<1e-9:direction=np.array([0.,-1.])
        delta=direction/np.linalg.norm(direction)*distance
        candidate=deepcopy(c);pose=np.asarray(candidate['object_poses'][target]);pose[:2,3]+=delta;candidate['object_poses'][target]=pose.tolist()
        gate=legal(candidate,[target]);proposals.append(dict(index=index,config=candidate,object_id=target,translation_xy_m=delta.tolist(),translation_norm_m=distance,rotation_degrees=0,edited_objects=1,legality=gate))
    return proposals,None

def prepare():
    cases=json.loads((ROOT/'cases.json').read_text());injected=json.loads((ROOT/'INJECTED_CASES.json').read_text());groups=[];natural_counts={s:0 for s in ['development','holdout']}
    for c in cases:
        if c['initialization_id']!='I0' or c['scene_variant']!='repaired':continue
        episode=ROOT/'experiments'/c['case_id'];d=diagnose(episode);r=json.loads((episode/'result.json').read_text())
        write_json(episode/'diagnosis.json',d)
        if not r['success'] and 'task_clearance' in d['labels'] and contact_object(episode) and natural_counts[c['split']]<6:
            groups.append(dict(group_id=c['case_id'],config=c,episode=str(episode),stratum='natural',diagnosis=d));natural_counts[c['split']]+=1
    # Explicitly separate known-fault cases when natural I0 scene failures are scarce.
    for row in injected:
        c=row['config'];episode=ROOT/'experiments'/c['case_id'];d=diagnose(episode);r=json.loads((episode/'result.json').read_text());write_json(episode/'diagnosis.json',d)
        if r['success'] or c['controller_gain_multiplier']!=1 or 'task_clearance' not in d['labels'] or not contact_object(episode):continue
        if sum(g['config']['split']==c['split'] for g in groups)>=6:continue
        groups.append(dict(group_id=c['case_id'],config=c,episode=str(episode),stratum='injected',diagnosis=d))
    write_json(ROOT/'REPAIR_GROUPS.json',groups)
    write_json(ROOT/'REPAIR_METHODS_FROZEN.json',dict(source=bound(Path(__file__)),diagnosis_source=bound(Path(__file__).with_name('diagnosis.py')),methods=['F','G','R','D'],operator='existing supported accessory/chair translation',editable_objects=EDITABLE,magnitudes_m=[.08,.15],candidates_each_method=2,selection='success then smaller edit then lower wall cost',validation_initializations=['I1','I2'],maximum_groups=12,selected_groups=len(groups),natural_group_counts=natural_counts,heldout_feedback='only fixed online two-candidate feedback; I1/I2 excluded from selection',no_manual_case_tuning=True,filter_method='exclude I0 failures; report retained coverage, no robot execution',source_groups=bound(ROOT/'REPAIR_GROUPS.json')))
    print('Repair eligible groups',[(g['group_id'],g['stratum']) for g in groups],flush=True)

def run_group(group):
    directory=ROOT/'repairs'/group['group_id'];directory.mkdir(parents=True,exist_ok=False);base=group['config'];episode=Path(group['episode']);all_cases=json.loads((ROOT/'cases.json').read_text());methods=[]
    for method in ['G','R','D']:
        proposals,refusal=candidates(episode,base,method,group['diagnosis']);write_json(directory/(method+'_proposals.json'),dict(proposals=proposals,refusal=refusal))
        evaluated=[]
        for p in proposals:
            c=p['config'];name=f"repair__{group['group_id']}__{method}__candidate{p['index']}";c['case_id']=name
            if not p['legality']['accepted']:
                ledger(dict(case_id=name,event='candidate_rejected',reasons=p['legality']['issues'],candidate_budget_consumed=True));evaluated.append(dict(proposal=p,result=None));continue
            result=run(c,ROOT/'experiments'/name);gc.collect();evaluated.append(dict(proposal=p,result=result))
        legal_runs=[r for r in evaluated if r['result'] is not None]
        if not legal_runs:methods.append(dict(method=method,selected=None,refusal=refusal or 'no_legal_candidate',evaluated=evaluated,validation=[]));continue
        best=min(legal_runs,key=lambda r:(not r['result']['success'],r['proposal']['translation_norm_m'],r['result']['wall_seconds']))
        valid=[]
        for init in ['I1','I2']:
            template=next(c for c in all_cases if c['layout_id']==base['layout_id'] and c['task']==base['task'] and c['initialization_id']==init and c['scene_variant']=='repaired')
            c=deepcopy(best['proposal']['config'])
            for key in ['start','goal','start_yaw_rad','seed','initialization_id','parent_local_coordinates']:c[key]=template[key]
            name=f"repair__{group['group_id']}__{method}__validate_{init}";c['case_id']=name
            result=run(c,ROOT/'experiments'/name);gc.collect();valid.append(dict(initialization=init,case_id=name,result=result))
        methods.append(dict(method=method,selected=best['proposal'],evaluated=evaluated,validation=valid))
    write_json(directory/'result.json',dict(group_id=group['group_id'],stratum=group['stratum'],split=base['split'],source_case=base['case_id'],methods=methods,filter=dict(retained=False,coverage=0),injected_unrepaired_I1_I2_baseline_available=group['stratum']=='natural'))
