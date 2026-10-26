"""Freeze a quiescent completed data ledger for final independent audits."""
from .work import E,c
from .dispatch import MOD,job
from . import controller_recovery_v4 as controller


def main():
    with controller.locked(E) as (merged,state):
        required=['complete_research_dataset_registry_02','complete_pipeline_cost_review_01']
        if state['active'] is not None or any(state['jobs'].get(k,{}).get('status')!='succeeded' for k in required):
            print({'awaiting_completed_data_reviews':True,'active':state['active']});return
        assert not any(v['status']=='pending' for v in state['jobs'].values())
        if 'final_resource_ledger_audit_01' in state['jobs']:
            print({'registered':[]});return
        snapshot=E/'evidence/final_preseal_audit';snapshot.mkdir(exist_ok=False)
        c.write(snapshot/'STATE.json',state);c.write(snapshot/'PLAN.json',c.read(E/'PLAN.json'))
    additions={}
    for key,module,output in [
        ('final_resource_ledger_audit_01','resource_ledger_audit','FINAL_RESOURCE_LEDGER_AUDIT.json'),
        ('final_immutable_input_audit_01','immutable_input_audit','FINAL_IMMUTABLE_INPUT_AUDIT.json')]:
        case=E/'cases'/(key+'.json');c.write(case,{'state_snapshot':str(snapshot/'STATE.json'),
            'plan_snapshot':str(snapshot/'PLAN.json'),'output':output})
        additions[key]=job(module,[case],[case,snapshot/'STATE.json',snapshot/'PLAN.json',MOD/'work.py',E/'RUN_CLOCK.json'],
            timeout=240,kind='seal',scope='existing_evidence_analysis',pool='export_seal')
    print({'registered':list(additions),'action':controller.extend_jobs(E,additions,
        'Final ledger recomputation and rehashing of every completed immutable input, with completed data reviews frozen')['action']})


if __name__=='__main__':main()
