from copy import deepcopy
import json
import numpy as np
from sage.experiments.embodied_scene_v1.package import bound
from .config import ROOT,PACKAGE,write_json

def prepare():
    cases=json.loads((ROOT/'cases.json').read_text());byid={c['case_id']:c for c in cases}
    sensitivity=[];faults=[];truth=[];recheck=[]
    for lid in ['L00','L01']:
        if not any(c['layout_id']==lid for c in cases):continue
        for task in ['navigate','pick_place']:
            base=byid[f'{lid}__I0__{task}__C1']
            for mass in ([.65,1.,1.4] if task=='pick_place' else [1.]):
                for friction in [.5,1.,1.5]:
                    c=deepcopy(base);name=f'sensitivity__{lid}__{task}__m{mass}__f{friction}'
                    c.update(case_id=name,mass_multiplier=mass,friction_multiplier=friction,explicit_contact_pairs=True)
                    sensitivity.append(dict(config=c,output=name,stage='S4_sensitivity'))
    for fi,family in enumerate(['false_collider_cavity_occupancy','task_clearance_obstruction','controller_configuration_perturbation']):
        for k,lid in enumerate(['L00','L01','L04','L05']):
            key=f'{lid}__I0__pick_place__C1'
            if key not in byid:continue
            c=deepcopy(byid[key]);name=f'injected__J{fi*4+k:02d}';c['case_id']=name
            if fi==0:c['scene_variant']='baseline'
            elif fi==1:
                mug=np.asarray(c['object_poses']['desk_mug']);mug[:2,3]=c['goal'][:2];c['object_poses']['desk_mug']=mug.tolist()
            else:c['controller_gain_multiplier']=.25
            faults.append(dict(config=c,output=name,stage='S4_injected'))
            truth.append(dict(case_id=name,family=family,source_case=key,split=c['split'],rule=['use original desk hull instead of existing C1 cuboids','place existing desk mug at task goal XY while preserving upright source geometry and table support','multiply joint PD kp/kd by .25; action schedule and physical model fixed'][fi],no_severity_adaptation=True))
    for task in ['navigate','pick_place']:
        for lid in ['L00','L04']:
            key=f'{lid}__I0__{task}__C1'
            if key in byid:
                c=deepcopy(byid[key]);c['case_id']='visual_recheck__'+key;c['physics_only']=False
                recheck.append(dict(config=c,output=c['case_id'],stage='S4_visual_recheck',source_case=key))
    for name,value in [('SENSITIVITY_CASES.json',sensitivity),('INJECTED_CASES.json',faults),('FAULT_TRUTH.json',truth),('VISUAL_RECHECK_CASES.json',recheck)]:
        path=ROOT/name
        if path.exists():raise ValueError('Branch already frozen')
        write_json(path,value)
    write_json(ROOT/'BRANCH_FREEZE.json',dict(files=[bound(ROOT/n) for n in ['SENSITIVITY_CASES.json','INJECTED_CASES.json','FAULT_TRUTH.json','VISUAL_RECHECK_CASES.json']],diagnostic_does_not_receive_truth=True,parameter_rules_frozen_before_results=True))
    print('Frozen sensitivity/injection/full-visual branches',len(sensitivity),len(faults),len(recheck),flush=True)
