from pathlib import Path
import hashlib
import h5py
import numpy as np
from scipy.spatial.transform import Rotation
from .contract import SCHEMA,arrays,action_blocks,check_times,statistics,source_evidence
from sage.experiments.embodied_scene_quality_v2.contracts import read,read_ref,reference,bound,require,write_new
from sage.experiments.embodied_task_clearance_v1.visibility import assess,masks


def create_binding(protocol,prepared,root):
    root=Path(root);p=read(protocol)
    value=dict(schema='temporal-dataset-binding/v1',request_id=p['request_id'],split='development',protocol=reference(protocol),
        prepared=reference(prepared),render=reference(root/'RENDER.json'),camera=reference(root/'CAMERA.json'),hdf5=reference(root/'episode.h5'),
        source_binding=p['source_binding'],implementation={str(f):reference(f) for f in sorted(Path(__file__).parent.glob('*.py'))},
        qualified_collection=False,qualified_export=False,learning_effect='unknown')
    write_new(root/'BINDING.json',value);return value


def validate(binding_path,pin,purpose,request_id):
    require(purpose in ['inspection','development_dataset'],'unsupported_purpose:'+purpose)
    b=read(bound(binding_path,pin));require(b['schema']=='temporal-dataset-binding/v1','binding_schema')
    require(b['split']=='development' and not b['qualified_collection'] and not b['qualified_export'],'scope_changed')
    p=read_ref(b['protocol']);require(request_id==b['request_id']==p['request_id'],'request_identity')
    for ref in b['implementation'].values():bound(ref['path'],ref['sha256'])
    require(b['source_binding']==p['source_binding'],'source_binding_changed');source_evidence(p)
    prepared=read_ref(b['prepared']);require(prepared['passed'] and prepared['protocol']==b['protocol'],'preparation_identity')
    a=arrays(bound(prepared['prepared']['path'],prepared['prepared']['sha256']));raw=arrays(p['source_raw']['path'])
    expected=action_blocks(raw['reference_positions'],raw['reference_velocities'],raw['controls'],prepared['gripper_actuator_ids'])
    require(np.array_equal(expected,a['action']),'prepared_action_changed')
    lookup={int(step):i for i,step in enumerate(raw['snapshot_steps'])};states=raw['states'][[lookup[int(k)] for k in p['observation']['frame_steps']]]
    require(np.array_equal(states,a['states']),'prepared_states_changed')
    q=states[:,1:1+prepared['nq']][:,prepared['qpos_ids']];v=states[:,1+prepared['nq']:1+prepared['nq']+prepared['nv']][:,prepared['dof_ids']]
    require(np.array_equal(np.column_stack([q,v]),a['proprio']),'prepared_proprio_changed')
    render=read_ref(b['render']);camera=read_ref(b['camera']);sourcecam=read_ref(p['source_camera'])
    require(camera['position']==sourcecam['position'] and camera['quaternion_wxyz']==sourcecam['quaternion'] and camera['camera_id']==sourcecam['camera_id'],'camera_changed')
    require(render['protocol']==b['protocol'] and render['prepared']==b['prepared'] and render['complete'] and len(render['frames'])==351,'render_incomplete')
    limits=p['observation'];failures=[];checked=0
    require(render['hdf5']==b['hdf5'],'render_data_identity')
    focal=.5*limits['height']/np.tan(np.deg2rad(prepared['fovy_deg'])*.5)
    expected_k=np.array([[focal,0,limits['width']/2],[0,focal,limits['height']/2],[0,0,1]])
    transform=np.eye(4);transform[:3,:3]=Rotation.from_quat(np.asarray(prepared['quaternion'])[[1,2,3,0]]).as_matrix();transform[:3,3]=prepared['position']
    require(camera['width']==limits['width'] and camera['height']==limits['height'] and camera['fovy_deg']==prepared['fovy_deg'],'camera_resolution')
    require(np.allclose(camera['intrinsics'],expected_k,rtol=0,atol=1e-12) and np.allclose(camera['mujoco_camera_to_world'],transform,rtol=0,atol=1e-12) and np.allclose(camera['optical_camera_to_world'],transform@np.diag([1.,-1.,-1.,1.]),rtol=0,atol=1e-12),'camera_calibration')
    with h5py.File(bound(b['hdf5']['path'],b['hdf5']['sha256']),'r') as f:
        require(f.attrs['schema']==SCHEMA and f.attrs['split']=='development' and f.attrs['request_id']==request_id,'dataset_identity')
        require(bool(f.attrs['physical_episode_success']) and not f.attrs['production_qualified'] and f.attrs['source_raw_sha256']==p['source_raw']['sha256'],'dataset_scope')
        require(int(f.attrs['frames_written'])==351 and f['observation/rgb'].shape==(351,limits['height'],limits['width'],3),'frame_count')
        require(f['action'].shape==(350,50,15),'action_shape')
        require(f['observation/rgb'].dtype==np.uint8 and f['observation/proprio'].shape==(351,18),'observation_format')
        require(f.attrs['controller_formula']==p['action']['controller_formula'] and f.attrs['reference_sample']==p['action']['reference_sample'],'action_semantics')
        check_times(f['observation/time'][:],f['observation/step'][:])
        fields={'action':a['action'],'observation/proprio':a['proprio'],'observation/time':a['times'],'observation/step':a['steps'],
            'audit/integration_state':a['states'],'audit/actual_actuator_control':a['controls'],'audit/phase_ids':a['phase_ids'],
            'audit/observation_phase':a['observation_phase'],'audit/substep_start':a['substep_start'],'audit/substep_end':a['substep_end']}
        for name,expected_array in fields.items():
            actual=f[name][:];require(np.array_equal(actual,expected_array),'data_changed:'+name);require(np.isfinite(actual).all(),'nonfinite_data:'+name)
        for i,row in enumerate(render['frames']):
            require(row['frame']==i and row['step']==int(a['steps'][i]) and row['time_s']==float(a['times'][i]),'frame_identity')
            require(row['phase']==prepared['phase_names'][int(a['observation_phase'][i])],'frame_phase')
            rgb=f['observation/rgb'][i];mean,std=statistics(rgb)
            require(hashlib.sha256(rgb.tobytes()).hexdigest()==row['rgb_sha256'],'rgb_changed')
            require(np.array_equal(mean,row['channel_mean']) and np.array_equal(std,row['channel_std']),'rgb_statistics_changed')
            visible,alone=masks(f['audit/full_segmentation'][i],f['audit/target_only_segmentation'][i],prepared['target_geom_ids'],prepared['geom_object_type'])
            score=assess(visible,alone,limits);score['scope']='one saved full-robot trajectory frame; all registered frames required'
            require(score==row['assessment'],'visibility_summary_changed')
            if not score['passed']:failures.append(i)
            checked+=1
        require(np.any(f['observation/rgb'][0]!=f['observation/rgb'][-1]),'no_image_change')
    require(failures==render['failed_frames'] and render['passed']==(not failures),'render_summary_changed')
    if purpose=='development_dataset':require(not failures,'temporal_visibility_failed')
    return dict(passed=True,scope='development_only',purpose=purpose,transitions=350,observations=351,checked_frames=checked,
        physical_episode_success=True,temporal_visibility_passed=not failures,failed_frames=failures,
        development_dataset_qualified=not failures,qualified_collection=False,qualified_export=False,learning_effect='unknown',
        action_shape=[50,15],rgb_dtype='uint8',rgb_range=[0,255],observation_fields=['rgb','proprio','time'],privileged_fields_exposed=False),b


class EpisodeDataset:
    """Read transitions only after real provenance and observation validation."""
    def __init__(self,binding,pin,purpose='development_dataset',request_id='O01'):
        self.verification,self.binding=validate(binding,pin,purpose,request_id)
        self.path=self.binding['hdf5']['path']
    def __len__(self):return 350
    def __getitem__(self,index):
        if not isinstance(index,(int,np.integer)) or index<0 or index>=len(self):raise IndexError(index)
        with h5py.File(self.path,'r') as f:
            return dict(rgb=f['observation/rgb'][index],proprio=f['observation/proprio'][index],time=float(f['observation/time'][index]),
                action=f['action'][index],next_rgb=f['observation/rgb'][index+1],next_proprio=f['observation/proprio'][index+1],next_time=float(f['observation/time'][index+1]))
