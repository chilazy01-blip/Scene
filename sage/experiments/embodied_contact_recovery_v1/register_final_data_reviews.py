"""Register final data catalog and cost review only after actual reader acceptance."""
import copy
from pathlib import Path
from .work import E,c
from .dispatch import MOD,job
from . import controller_recovery_v4 as controller


def main():
    state=c.read(E/'STATE.json')
    episodes=[]
    for key in ['C3','D1','D2','D3','D4','D5']:
        clean=key!='C3'
        acceptance=E/(key+('_CLEAN_FULL_RGBD_RESEARCH_DATASET_ACCEPTANCE.json' if clean else '_FULL_RGBD_RESEARCH_DATASET_ACCEPTANCE.json'))
        if not acceptance.exists() or not c.read(acceptance)['passed']:
            print({'waiting_for_actual_acceptance':key});return
        root=E/'jobs'/(key+('_clean_full_RGBD_export_01' if clean else '_full_RGBD_export_01'))/'dataset'
        episodes.append({'key':key+('_failed_site_free' if clean else '_failed_with_diagnostic_sites'),
                         'dataset_root':str(root),'acceptance_report':str(acceptance)})
    additions={}
    registry_key='complete_research_dataset_registry_02'
    if registry_key not in state['jobs']:
        old=state['additional_jobs']['complete_research_dataset_registry_01']
        case=E/'cases'/(registry_key+'.json')
        cfg={'episodes':episodes,'visual_site_contamination_review':str(E/'RGBD_DIAGNOSTIC_SITE_CONTAMINATION_REVIEW.json'),
             'output':'COMPLETE_RESEARCH_RGBD_DATASET_REGISTRY_R2.json'}
        c.write(case,cfg)
        files=[Path(p) for p in old['inputs'] if not Path(p).is_relative_to(E)]
        files += [case,Path(cfg['visual_site_contamination_review'])]
        for item in episodes:
            files += [Path(item['acceptance_report']),*[p for p in Path(item['dataset_root']).rglob('*') if p.is_file()]]
        new=copy.deepcopy(old);new.update(kind='seal',pool='export_seal')
        new['argv'][-1]=str(case);new['inputs']={str(p):c.sha(p) for p in files}
        additions[registry_key]=new
    cost_key='complete_pipeline_cost_review_01'
    if cost_key not in state['jobs']:
        old=state['additional_jobs']['interim_pipeline_cost_review_r2']
        cfg=c.read(old['argv'][-1])
        snapshot=E/'evidence/complete_pipeline_cost';snapshot.mkdir(exist_ok=False)
        for name in ['STATE.json','PLAN.json']:c.write(snapshot/name,c.read(E/name))
        cfg['state_snapshot']=str(snapshot/'STATE.json');cfg['plan_snapshot']=str(snapshot/'PLAN.json')
        for key in ['D1','D2','D4','D5']:
            names=[k for k in state['jobs'] if k.startswith((key+'_clean_',key+'_complete_numeric_export_',key+'_contact_quality_frame_index_')) and state['jobs'][k]['status'] in ['succeeded','failed']]
            assert names and all(state['jobs'][k]['status'] in ['succeeded','failed'] for k in names)
            cfg['episodes'].append({'key':key,'acceptance_report':str(E/(key+'_CLEAN_FULL_RGBD_RESEARCH_DATASET_ACCEPTANCE.json')),'direct_pipeline_jobs':names})
        cfg['episodes'].sort(key=lambda x:['C3','D1','D2','D3','D4','D5'].index(x['key']))
        cfg['output']='COMPLETE_RESEARCH_PIPELINE_COST_REVIEW.json'
        cfg['physical_bottlenecks']=[
            'All8 new complete development tasks failed unchanged quality gates; C closed3/3 and D closed5/5.',
            'Local measured grasp/carry improvements did not compose into an accepted complete task; D4/D5 failed initial foot contact before grasp.',
            'Latest foot half/quarter timestep position/speed checks failed while hand local checks passed; full-task numerical qualification remains absent.',
            'Inherited material/friction and force/transient limits lack empirical calibration.',
            'All5 D visual records hide diagnostic sites; legacy C3 still contains site visualization. Every episode remains failed research data.',
            'Generated layouts are static-qualified only; comparison and fresh final tests were not admitted; task-learning updates0.']
        case=E/'cases'/(cost_key+'.json');c.write(case,cfg)
        files=[case,snapshot/'STATE.json',snapshot/'PLAN.json',MOD/'work.py']
        files += [Path(x['acceptance_report']) for x in cfg['episodes']]
        files += [E/'jobs'/k/'RESULT.json' for k,j in {**c.read(E/'PLAN.json')['jobs'],**state['additional_jobs']}.items()
                  if j['kind']=='physics' and (E/'jobs'/k/'RESULT.json').exists()]
        additions[cost_key]=job('research_pipeline_cost_review_r3',[case],files,timeout=180,kind='seal',
                               scope='existing_evidence_analysis',pool='export_seal')
    if additions:print({'registered':list(additions),'action':controller.extend_jobs(E,additions,'Final complete research-data registry and source-bound cost review; use designated export/seal reserve')['action']})
    else:print({'registered':[]})


if __name__=='__main__':main()
