"""Register bounded numerical cases or their review from completed evidence."""
import sys
from pathlib import Path
from .work import E,c
from .dispatch import MOD,job
from . import controller_recovery_v4 as controller


def main(design_path):
    design_path=Path(design_path);design=c.read(design_path);state=c.read(E/'STATE.json');additions={}
    inherited=next(j for j in state['additional_jobs'].values() if 'sage.experiments.embodied_contact_recovery_v1.diagnostics_r5' in j['argv'])
    for window in design['windows']:
        keys=[]
        for value in window['cases']:
            path=Path(value);cfg=c.read(path);folder=Path(cfg['source_folder']);key=path.stem;keys.append(key)
            if key in state['jobs']:continue
            bindings={str(p):c.sha(p) for p in [folder/'MODEL.mjb',folder/'TRACE.h5']}
            files=[*inherited['inputs'],path,design_path,*bindings,E/'D_RECOVERY_EXTENSION_APPROVAL.json']
            additions[key]=job('diagnostics_r5',[path],files,timeout=90,kind='diagnostic',scope='object_pose_planning_research',reservation={'diagnostic_physics_steps':cfg['saved_steps']*cfg['subdivisions']},method='D_object_pose_planning',diagnostic={'bounded_contact_window':True,'max_sim_seconds':cfg['saved_steps']*.0025,'saved_state':bindings},disk_reservation_bytes=150*1024**2)
        review=window['prefix']+'_review'
        if review in state['jobs'] or not all(state['jobs'].get(k,{}).get('status')=='succeeded' for k in keys):continue
        case=E/'cases'/(review+'.json');cfg={'jobs':keys,'comparison_indices':[[0,1],[1,2],[0,2],[0,3]],'output':window['prefix'].upper()+'_NUMERICAL_REVIEW.json'}
        if case.exists():assert c.read(case)==cfg
        else:c.write(case,cfg)
        files=[case,design_path,*[E/'jobs'/key/name for key in keys for name in ['episode/MODEL.mjb','episode/TRACE.h5','RESULT.json','REQUEST.json']]]
        module='sole_numerical_review_r2' if window['contact']=='foot' else 'grasp_numerical_evidence';args=[case] if window['contact']=='foot' else ['review',case]
        additions[review]=job(module,args,files,timeout=120,kind='analysis',scope='existing_evidence_analysis')
    if additions:
        decision=controller.extend_jobs(E,additions,'Bound measured contact-specific numerical variations or independently review completed nominal/half/quarter/double-iteration evidence')
        with controller.locked(E) as (plan,state):
            state['jobs']={**{k:state['jobs'][k] for k in additions},**{k:v for k,v in state['jobs'].items() if k not in additions}};c.write(E/'STATE.json',state)
        print({'registered':list(additions),'decision':decision['action']})
    else:print({'registered':[],'waiting_for_actual_prerequisites':True})


if __name__=='__main__':main(sys.argv[1])
