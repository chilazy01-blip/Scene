"""Time-aligned conditional simulation trajectories with privileged state split."""
from pathlib import Path
import hashlib,json
import h5py
import numpy as np
from sage.experiments.embodied_actuator_v1 import CHANNELS, StretchTransmission

UNITS=('rad/s','rad/s','m','m','rad','rad','rad','m','rad','rad')


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def actuator_state(m,tr,qpos,qvel):
    length=np.zeros((len(qpos),10));velocity=np.zeros_like(length)
    for a,name in enumerate(CHANNELS):
        pairs=tr.joints[name][:1] if name=='gripper' else tr.joints[name]
        for joint,_ in pairs:
            scale=1. if name=='arm' else m.actuator_gear[a,0]
            length[:,a]+=qpos[:,m.joint(joint).qposadr[0]]*scale
            velocity[:,a]+=qvel[:,m.joint(joint).dofadr[0]]*scale
    return length,velocity


def export_trajectory(directory,model,output,audit):
    directory=Path(directory);output=Path(output)
    r=json.loads((directory/'RESULT.json').read_text());start=json.loads((directory/'START.json').read_text())
    a=np.load(directory/'RAW.npz',allow_pickle=False);n=r['physics_steps']
    if not audit.get('audited') or audit['steps']!=n:raise ValueError('saved_trajectory_not_audited')
    tr=StretchTransmission(model);q,v=actuator_state(model,tr,a['qpos'],a['qvel'])
    index=np.arange(0,n,5);nxt=np.minimum(index+5,n);previous=np.maximum(index-5,0)
    previous_ref=a['reference'][previous].copy();previous_ref[0]=start['home']
    fields=dict(timestamp=index.astype(np.float64)*.002,dt=(nxt-index).astype(np.float64)*.002,joint_position=q[index],joint_velocity=v[index],previous_reference=previous_ref,action_reference=a['reference'][index],action_ctrl=a['ctrl'][index],next_joint_position=q[nxt],next_joint_velocity=v[nxt],done=nxt==n)
    if not all(np.isfinite(x).all() for x in fields.values()):raise ValueError('nonfinite_export')
    metadata=dict(schema='conditional-sim-trajectory/v1',scope='simulation_only',trial=directory.name,task_success=r['passed'],kind=r['kind'],action_names=CHANNELS,action_units=UNITS,action_frame='native actuator reference; wheel transmission velocity uses gear3',position_units=('rad','rad','m','m','rad','rad','rad','m','rad','rad'),frequency_hz=100,physics_dt=.002,gravity_compensation='internal feedforward included in ctrl and finite effort caps',privileged_excluded_from_observations=['qpos','qvel','body_pose','object_pose','mass','capability','failure_metrics'],qualified_production_training=False,hardware_validated=False,initial_object_pose_source='simulator task metadata, privileged',camera_status='separate sparse replay capture, not padded into this dataset',rows=len(index),source_sha256={name:sha(directory/name) for name in ['RAW.npz','RESULT.json','START.json','MODEL.json','model.xml','household.xml'] if (directory/name).exists()})
    metadata=json.loads(json.dumps(metadata))  # canonical JSON types on both sides
    with h5py.File(output,'x') as f:
        f.attrs['metadata']=json.dumps(metadata,sort_keys=True)
        for key,value in fields.items():f.create_dataset('trajectory/'+key,data=value,compression='gzip')
        for key in ['qpos','qvel']:f.create_dataset('privileged/'+key,data=a[key][index],compression='gzip')
        f.create_dataset('privileged/physics_row',data=index)
        if 'phase' in a:f.create_dataset('privileged/phase',data=a['phase'][index])
    return dict(path=str(output.resolve()),sha256=sha(output),metadata=metadata)


class ProprioTrajectory:
    def __init__(self,binding,purpose='conditional_research'):
        if purpose!='conditional_research':raise ValueError('not_qualified_for_production_or_hardware')
        if sha(binding['path'])!=binding['sha256']:raise ValueError('dataset_hash_mismatch')
        with h5py.File(binding['path'],'r') as f:
            self.metadata=json.loads(f.attrs['metadata'])
            if self.metadata!=binding['metadata']:raise ValueError('dataset_metadata_mismatch')
            self.rows={key:f['trajectory'][key][:] for key in f['trajectory']}
        if self.metadata['qualified_production_training'] or self.metadata['scope']!='simulation_only':raise ValueError('invalid_scope_upgrade')
    def __len__(self):return self.metadata['rows']
    def __getitem__(self,i):return {key:value[i].copy() for key,value in self.rows.items()}
