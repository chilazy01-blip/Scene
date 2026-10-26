"""Export audited conditional trajectories through pinned LeRobot/GR00T APIs."""
from pathlib import Path
import json,hashlib
import numpy as np
from .dataset import ProprioTrajectory,sha

FIELDS={'observation.position':'joint_position','observation.velocity':'joint_velocity','observation.previous_action':'previous_reference','action':'action_reference','action.ctrl':'action_ctrl','next.observation.position':'next_joint_position','next.observation.velocity':'next_joint_velocity','source.time':'timestamp','source.dt':'dt','outcome.done':'done'}


def export_collection(bindings,destination,resume_validation=False):
    from decoupled_wbc.data.exporter import Gr00tDataExporter
    destination=Path(destination);assert not destination.exists() or resume_validation
    assert bindings and all(b['metadata']['kind'].startswith('complete_task') for b in bindings)
    names=bindings[0]['metadata']['action_names'];features={}
    for key,source in FIELDS.items():
        vector=source not in ('timestamp','dt','done');features[key]=dict(dtype='int64' if source=='done' else 'float64',shape=(10 if vector else 1,),names=names if vector else [source])
    features['outcome.task_success']=dict(dtype='int64',shape=(1,),names=['task_success'])
    modality=dict(state={k:{'original_key':key,'start':0,'end':10} for k,key in [('position','observation.position'),('velocity','observation.velocity'),('previous_action','observation.previous_action')]},action={'native_reference':{'original_key':'action','start':0,'end':10}},video={},annotation={})
    if destination.exists():
        info=json.loads((destination/'meta/info.json').read_text());assert info['script_config']['source_bindings']==bindings;assert info['total_episodes']==len(bindings)
        episodes=[dict(episode_index=i,source=b['sha256'],trial=b['metadata']['trial'],rows=b['metadata']['rows'],success=bool(b['metadata']['task_success'])) for i,b in enumerate(bindings)]
    else:
        writer=Gr00tDataExporter.create(save_root=destination,fps=100,features=features,modality_config=modality,task='move calibration object 0.12 m along x and release stably',script_config=dict(schema='conditional-sim-lerobot/v1',scope='simulation_only',source_bindings=bindings,action_units=bindings[0]['metadata']['action_units'],position_units=bindings[0]['metadata']['position_units'],source_time_semantics='exact float64 simulation seconds; LeRobot timestamp is frame/fps'),robot_type='Stretch effective assumed simulation',overwrite_existing=False)
        writer.meta.info['scene_qualification']=dict(scope='simulation_only',purpose='conditional_research',hardware_validated=False,production_training_qualified=False,cameras_present=False,learner_inputs_exclude_mass_capacity_live_object_pose=True)
        episodes=[]
        for episode,binding in enumerate(bindings):
            source=ProprioTrajectory(binding);success=bool(source.metadata['task_success'])
            for i in range(len(source)):
                row=source[i];frame={key:np.asarray(row[field],dtype=features[key]['dtype']).reshape(features[key]['shape']) for key,field in FIELDS.items()};frame['outcome.task_success']=np.array([success],dtype=np.int64);writer.add_frame(frame)
            if success:writer.save_episode()
            else:writer.save_episode_as_discarded()
            episodes.append(dict(episode_index=episode,source=binding['sha256'],trial=source.metadata['trial'],rows=len(source),success=success))
        writer.stop_video_writers()
    from decoupled_wbc.data.exporter import TypedLeRobotDataset
    native=TypedLeRobotDataset(repo_id='local/conditional-stretch',root=destination,episodes=list(range(len(bindings))),video_backend='pyav')
    assert len(native)==sum(x['rows'] for x in episodes)
    assert native.meta.info['discarded_episode_indices']==[x['episode_index'] for x in episodes if not x['success']]
    assert not native.meta.camera_keys
    # Real official typed consumer and DataLoader, every field of every row.
    import torch
    from torch.utils.data import DataLoader
    offset=0;errors={key:0. for key in features}
    for episode,binding in zip(episodes,bindings):
        source=ProprioTrajectory(binding);subset=torch.utils.data.Subset(native,range(offset,offset+len(source)));cursor=0
        for batch in DataLoader(subset,batch_size=256,num_workers=0):
            count=len(batch['index'])
            for key,field in FIELDS.items():
                expected=source.rows[field][cursor:cursor+count].astype(features[key]['dtype']).reshape(count,*features[key]['shape']);actual=batch[key].numpy();assert actual.size==expected.size;actual=actual.reshape(expected.shape);assert actual.dtype==expected.dtype and np.array_equal(actual,expected),(episode['trial'],key)
            assert np.all(batch['outcome.task_success'].numpy()==episode['success']);assert np.all(batch['episode_index'].numpy()==episode['episode_index']);cursor+=count
        assert cursor==len(source);offset+=len(source)
    manifest=dict(schema='conditional-sim-lerobot/v1',scope='simulation_only',purpose='conditional_research',production_training_qualified=False,hardware_validated=False,episodes=episodes,typed_rows_verified=offset,all_field_errors=errors,source_bindings=bindings,writer_sha256=sha(__import__(Gr00tDataExporter.__module__,fromlist=['__file__']).__file__),files=[dict(relative=str(p.relative_to(destination)),sha256=sha(p)) for p in sorted(destination.rglob('*')) if p.is_file()])
    (destination/'BINDING.json').write_text(json.dumps(manifest,indent=2));return manifest
