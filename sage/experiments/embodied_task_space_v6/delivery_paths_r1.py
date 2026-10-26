"""Resolve data only from the active, independently audited physical trial.

This gate rejects zero-step/audited-failure records and cross-candidate paths.
It does not produce a physical certificate or a qualified data episode.
"""
from pathlib import Path
import hashlib,json,math

class DeliveryNotAdmitted(RuntimeError):pass

def require(condition,reason):
    if not condition:raise DeliveryNotAdmitted(reason)

def read(path):
    try:return json.loads(Path(path).read_text())
    except (OSError,ValueError) as exc:raise DeliveryNotAdmitted('missing_or_invalid:'+str(path)) from exc

def digest(path):
    h=hashlib.sha256()
    try:
        with Path(path).open('rb') as f:
            for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    except OSError as exc:raise DeliveryNotAdmitted('missing_bound_file:'+str(path)) from exc
    return h.hexdigest()

def resolve(active,stage):
    active=Path(active).resolve();require(stage in ('render','export'),'delivery_stage')
    binding=read(active/'PHYSICAL_BINDING.json');files=binding.get('files',{})
    require(binding.get('scope')=='local_full_task_physics_and_audit_v1' and binding.get('active_root')==str(active) and isinstance(files,dict) and files,'physical_binding_identity')
    for path,h in files.items():require(Path(path).is_absolute() and digest(path)==h,'physical_bound_bytes_changed:'+path)
    def bound(path):
        path=Path(path);require(not path.is_symlink() and path.resolve().is_relative_to(active),'cross_candidate_artifact')
        require(str(path.resolve()) in files,'physical_artifact_not_bound:'+str(path));return read(path)
    trial=active/'trial';result=bound(trial/'RESULT.json');audit=bound(active/'PHYSICS_AUDIT.json');updates=bound(trial/'UPDATES.json')
    require(result.get('full_task_success') is True and audit.get('full_task_success') is True and audit.get('passed') is True,'physical_success_not_audited')
    steps=result.get('physics_steps');require(type(steps) is int and 0<steps<=74500 and steps%10==0,'physical_step_count')
    require(result.get('committed_steps')==steps and audit.get('saved_steps_audited')==steps,'incomplete_raw_commit_or_audit')
    require(result.get('policy_forwards')==len(updates)==steps//10 and audit.get('actual_commands_reconstructed')==len(updates),'physical_command_count')
    require(audit.get('causal_clock_reconstructed') is True and audit.get('first_physical_failure')==[] and result.get('failures')==[],'causal_trial_not_passed')
    require(result.get('state_writes_after_initialization')==0 and result.get('external_forces') is False,'physical_state_assignment_or_external_force')
    for key,limit in [('input',2e-6),('target',1e-12),('ctrl',1e-12),('raw',1e-12),('contact',1e-6)]:
        value=audit.get('max_errors',{}).get(key,math.inf);require(isinstance(value,(int,float)) and math.isfinite(value) and 0<=value<limit,'physical_audit_metric:'+key)
    raw=trial/'RAW.h5';require(not raw.is_symlink() and raw.resolve().is_relative_to(active) and files.get(str(raw.resolve()))==digest(raw),'raw_source_not_bound_to_active_trial')
    rows=(steps+49)//50;require(rows<=1490,'image_timestamp_budget')
    records=[]
    if stage=='export':
        for path in sorted((active/'rgbd').glob('chunk_[0-9][0-9][0-9][0-9].json')):
            row=read(path);chunk=Path(row['path']).resolve();require(chunk.parent==active/'rgbd' and digest(chunk)==row.get('sha256') and row.get('passed') is True,'rgbd_chunk_identity')
            records.append(row)
        require(records and records[0]['start']==0 and records[-1]['stop']==rows and all(a['stop']==b['start'] for a,b in zip(records,records[1:])),'complete_rgbd_clock_required')
        require(all(0<r['stop']-r['start']<=100 and r.get('render_passes')==6*(r['stop']-r['start']) for r in records),'rgbd_render_count')
        require(sum(r['render_passes'] for r in records)<=8940,'render_pass_budget')
    return dict(active_root=str(active),trial=str(trial),raw=str(raw),raw_sha256=files[str(raw)],updates=str(trial/'UPDATES.json'),physical_binding_sha256=digest(active/'PHYSICAL_BINDING.json'),physics_steps_recorded=steps,image_timestamps=rows,rgbd_records=records,new_physics_admitted=False,data_episode_qualified=False)
