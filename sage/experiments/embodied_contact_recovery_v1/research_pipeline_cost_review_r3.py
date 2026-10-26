"""Ledger-based production bottleneck review; zero accepted yield stays explicit."""
import sys
from pathlib import Path
from .work import E,c,finish


def main(config_path):
    cfg=c.read(config_path);snapshot=c.read(cfg['state_snapshot']);plan=c.read(cfg['plan_snapshot'])
    definitions={**plan['jobs'],**snapshot.get('additional_jobs',{})};tasks=[];zero_integration_attempts=[]
    for key,definition in definitions.items():
        state=snapshot['jobs'].get(key,{})
        if definition['kind']!='physics' or state.get('usage',{}).get('task_attempts',0)!=1:continue
        result=c.read(E/'jobs'/key/'RESULT.json')
        if state.get('usage',{}).get('task_physics_steps',0)==0 or result.get('trace_summary',result.get('summary',{})).get('physics_steps')==0:
            zero_integration_attempts.append({'job':key,'original_usage':state['usage'],'result_outcome':state['outcome'],'retained_not_scientific_task':True})
            continue
        tasks.append({'job':key,'method':definition.get('method'),'outcome':state['outcome'],
                      'actual_usage':state['usage'],'production_accepted':result.get('production_accepted',False),
                      'research_task_passed':result.get('research_task_passed',False)})
    episodes=[]
    for episode in cfg['episodes']:
        acceptance=c.read(episode['acceptance_report']);assert acceptance['passed']
        jobs=episode['direct_pipeline_jobs'];assert len(set(jobs))==len(jobs)
        usage={}
        for key in jobs:
            entry=snapshot['jobs'][key];assert entry['status'] in ['succeeded','failed']
            for resource,value in entry.get('usage',{}).items():usage[resource]=usage.get(resource,0)+value
        frames=acceptance['complete_episode_actual_public_reader_rows']
        episodes.append({'key':episode['key'],'actual_complete_RGBD_frames':frames,'direct_pipeline_jobs':jobs,
                         'actual_direct_pipeline_usage':usage,
                         'wall_service_seconds_per_complete_research_frame':usage.get('service_seconds',0)/frames,
                         'render_passes_per_complete_research_frame':usage.get('render_passes',0)/frames,
                         'accepted_production_episode':False,'cost_excludes_shared_diagnostic_and_control_engineering':True})
    accepted=sum(bool(t['production_accepted']) for t in tasks)
    report={'complete':True,'new_full_task_count':len(tasks),'tasks':tasks,'zero_integration_engineering_attempts':zero_integration_attempts,'accepted_full_body_task_count':accepted,
            'qualified_yield':accepted/len(tasks) if tasks else None,
            'cost_per_accepted_episode_service_seconds':None if accepted==0 else sum(t['actual_usage'].get('service_seconds',0) for t in tasks)/accepted,
            'zero_yield_cost_note':'No finite unit cost of accepted production data can be reported when accepted yield is zero.',
            'research_episode_data_engineering':episodes,'shared_and_prior_costs_are_not_reset':snapshot['spent'],
            'clock':plan['clock'],'method_states':{k:{'closed':v['closed'],'scientific_failures':v['scientific_failures']} for k,v in snapshot['methods'].items()},
            'physical_bottlenecks':cfg['physical_bottlenecks'],
            'reusable_engineering_completed':['All400Hz physics/control/contact/ONNX traces and independent reintegration','25Hz two-camera256RGBD immutable shards and provenance audit','Standard portable single-episode export with temporal masks and actuator units','Actual public RGBD consumer comparison on every exported frame'],
            'effective_scene_diversity_note':'Multiple trajectories in the same native scene do not count as multiple generated layouts. Generated development scenes are static-qualified only unless separately recorded actual tasks prove otherwise.',
            'task_learning_verified':False,'training_updates':snapshot['spent'].get('training_updates',0),'new_physics_steps':0,
            'state_snapshot_sha256':c.sha(cfg['state_snapshot']),'plan_snapshot_sha256':c.sha(cfg['plan_snapshot']),
            'whole_run_closure_claim':False}
    c.write(E/cfg['output'],report);finish(report)


if __name__=='__main__':main(sys.argv[1])
