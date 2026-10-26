"""Advance only concrete saved-data sealing stages, then leave closure to the clock."""
import time
from .work import E,c
from .dispatch import MOD,job
from . import controller_recovery_v4 as controller
from .register_complete_research_pipeline_r5 import main as pipeline
from .register_final_data_reviews import main as reviews
from .register_final_audits import main as audits


def main():
    assert c.read(E/'STATE.json')['active'] is None,'another dispatcher owns a worker'
    while time.time()<c.read(E/'RUN_CLOCK.json')['deadline_epoch']:
        state=c.read(E/'STATE.json')
        assert state['active'] is None
        if state['jobs'].get('final_evidence_index_01',{}).get('status')=='succeeded':
            print({'data_and_audits_sealed':True,'whole_run_still_active_until_original_exit':True});return
        for key in ['final_resource_ledger_audit_01','final_immutable_input_audit_01','final_evidence_index_01']:
            if state['jobs'].get(key,{}).get('status')=='failed':raise RuntimeError('Inspect retained failed seal worker: '+key)
        for key,entry in state['jobs'].items():
            if entry['status']=='failed' and (key.startswith(('D1_clean_full_RGBD_','D2_clean_full_RGBD_')) or key in ['complete_research_dataset_registry_02','complete_pipeline_cost_review_01']):
                raise RuntimeError('Inspect retained failed data worker: '+key)
        pipeline('D_development_01','D1')
        pipeline('D_development_02','D2')
        reviews()
        state=c.read(E/'STATE.json')
        if not any(x['status']=='pending' for x in state['jobs'].values()):audits()
        state=c.read(E/'STATE.json')
        if all(state['jobs'].get(k,{}).get('status')=='succeeded' for k in ['final_resource_ledger_audit_01','final_immutable_input_audit_01']) and 'final_evidence_index_01' not in state['jobs']:
            assert c.read(E/'FINAL_RESOURCE_LEDGER_AUDIT.json')['passed']
            assert c.read(E/'FINAL_IMMUTABLE_INPUT_AUDIT.json')['passed']
            snapshot=E/'evidence/final_index_snapshot';snapshot.mkdir(exist_ok=False)
            c.write(snapshot/'STATE.json',state);c.write(snapshot/'PLAN.json',c.read(E/'PLAN.json'))
            cfg={'state_snapshot':str(snapshot/'STATE.json'),'plan_snapshot':str(snapshot/'PLAN.json'),
                'RGBD_registry':str(E/'COMPLETE_RESEARCH_RGBD_DATASET_REGISTRY_R2.json'),
                'numeric_acceptance':str(E/'COMPLETE_NUMERIC_RESEARCH_COLLECTION_ACCEPTANCE.json'),
                'ledger_audit':str(E/'FINAL_RESOURCE_LEDGER_AUDIT.json'),
                'immutable_input_audit':str(E/'FINAL_IMMUTABLE_INPUT_AUDIT.json'),
                'cost_review':str(E/'COMPLETE_RESEARCH_PIPELINE_COST_REVIEW.json'),
                'output':'PREPARED_EVIDENCE_SEAL.json','manifest_output':'EVIDENCE_FILE_MANIFEST.json'}
            case=E/'cases/final_evidence_index_01.json';c.write(case,cfg)
            files=[case,MOD/'work.py',MOD/'resource_ledger_audit.py',MOD/'immutable_input_audit.py',
                   *[E/name for name in ['COMPLETE_TASK_EVIDENCE_REVIEW.json','RECOVERY_EVIDENCE_FIGURE_REVIEW.json','RUN_CLOCK.json']],
                   *[value for key,value in cfg.items() if key not in ['output','manifest_output']]]
            controller.extend_jobs(E,{'final_evidence_index_01':job('seal_evidence_index',[case],files,
                timeout=600,kind='seal',scope='existing_evidence_analysis',pool='export_seal')},
                'Catalog complete immutable saved-data evidence after independent ledger/input audits; preserve original-clock closure authority')
        result=controller.run_one(E)
        if result['action'] not in ['dispatch','replan','seal_window']:
            print({'decision':result['action'],'reason':result.get('reason')});return
        if result['action']=='seal_window' and not any(x['status']=='pending' for x in c.read(E/'STATE.json')['jobs'].values()):
            # Loop once to register any just-enabled concrete successor.
            continue
        if result['action']=='replan' and not any(x['status']=='pending' for x in c.read(E/'STATE.json')['jobs'].values()):
            continue
    print({'original_deadline_reached':True,'close_only_after_reconciliation':True})


if __name__=='__main__':main()
