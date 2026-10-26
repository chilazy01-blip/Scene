"""Catalog immutable run artifacts while leaving final control closure separate."""
import os
import sys
import time
from pathlib import Path
from .work import E, c, finish


def main(config):
    cfg=c.read(config)
    work=Path(os.environ['CONTINUOUS_JOB_DIR'])
    state,plan=c.read(cfg['state_snapshot']),c.read(cfg['plan_snapshot'])
    assert state['active'] is None
    assert all(x['closed'] for x in state['methods'].values())
    assert state['spent']['training_updates']==0
    assert not any(x['status']=='pending' for x in state['jobs'].values())
    registry=c.read(cfg['RGBD_registry'])
    numeric=c.read(cfg['numeric_acceptance'])
    ledger=c.read(cfg['ledger_audit'])
    inputs=c.read(cfg['immutable_input_audit'])
    costs=c.read(cfg['cost_review'])
    assert registry['passed'] and numeric['passed'] and ledger['passed'] and inputs['passed']
    assert registry['production_view_episode_count']==0 and numeric['complete_audited_task_episodes']==8
    assert costs['new_full_task_count']==8 and costs['accepted_full_body_task_count']==0
    assert ledger['active_at_snapshot'] is None
    for key in plan['limits']:assert state['spent'][key]<=plan['limits'][key]
    output=E/cfg['output'];manifest_path=E/cfg['manifest_output']
    excluded_root={'STATE.json','CONTINUATION_CHECK.json','COORDINATOR_STATUS.json','CLOSURE.json',
                   'FINAL_SEAL.json','.lock','.controller.lock',output.name,manifest_path.name}
    files,links,excluded=[],[],[]
    cache={}
    for path in sorted(E.rglob('*')):
        relative=str(path.relative_to(E))
        if path.is_relative_to(work):
            if path.is_file() or path.is_symlink():excluded.append({'path':relative,'reason':'current_manifest_worker_outputs_bound_by_final_control_seal'})
            continue
        if path.parent==E and (path.name in excluded_root or path.suffix=='.tmp' or path.name.endswith('.lock')):
            if path.is_file():excluded.append({'path':relative,'reason':'mutable_control_or_manifest_self_reference'})
            continue
        if path.is_symlink():
            links.append({'path':relative,'link_target':os.readlink(path),'target_exists':path.exists(),
                          'target_kind':'directory' if path.is_dir() else 'file' if path.is_file() else 'missing'})
            continue
        if not path.is_file():continue
        stat=path.stat();key=(stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns)
        if key not in cache:cache[key]=c.sha(path)
        after=path.stat()
        assert (after.st_size,after.st_mtime_ns)==(stat.st_size,stat.st_mtime_ns),relative
        files.append({'path':relative,'bytes':stat.st_size,'sha256':cache[key]})
    manifest={'complete':True,'root':str(E),'files':files,'symlinks':links,'excluded':excluded,
        'retained_broken_symlinks':[x for x in links if not x['target_exists']], 'file_count':len(files),'logical_file_bytes':sum(x['bytes'] for x in files),
        'unique_inodes_hashed':len(cache),'source_state_snapshot_sha256':c.sha(cfg['state_snapshot']),
        'scope':'Immutable run artifacts; symlink targets outside the run retain original bindings checked by the separate immutable-input audit. Final mutable control files and this manifest job are bound by FINAL_SEAL after controller closure.'}
    c.write(manifest_path,manifest)
    report={'complete':True,'prepared_epoch':time.time(),'manifest_path':str(manifest_path),
        'manifest_sha256':c.sha(manifest_path),'manifest_file_count':len(files),
        'manifest_logical_file_bytes':manifest['logical_file_bytes'],
        'evidence':{name:{'path':cfg[name],'sha256':c.sha(cfg[name])} for name in
                    ['RGBD_registry','numeric_acceptance','ledger_audit','immutable_input_audit','cost_review','state_snapshot','plan_snapshot']},
        'complete_numeric_research_tasks':8,'complete_numeric_frames':numeric['actual_public_reader_rows'],
        'complete_RGBD_research_episodes':registry['total_complete_research_episodes'],
        'complete_RGBD_research_frames':registry['total_RGBD_frames'],
        'site_free_RGBD_episodes':registry['site_free_visual_episode_count'],
        'site_free_RGBD_frames':sum(x['rows'] for x in registry['episodes'] if not x['diagnostic_sites_visible']),
        'complete_RGBD_task_keys':[x['key'].split('_')[0] for x in registry['episodes']],
        'numeric_only_task_keys':sorted({x['key'] for x in numeric['episodes']}-{x['key'].split('_')[0] for x in registry['episodes']}),
        'qualified_production_episodes':0,'training_updates':0,'new_physics_steps':0,'new_render_passes':0,
        'all_methods_closed':True,'whole_run_closure_claim':False,
        'final_control_seal_required_after_original_deadline':True,'clock':plan['clock']}
    c.write(output,report)
    finish(report)


if __name__=='__main__':main(sys.argv[1])
