"""Native mixed-actuator trajectories; v1 inputs and evidence remain unchanged."""
from pathlib import Path
import json
import numpy as np
import h5py
from sage.experiments.embodied_trajectory_v1.dataset import (
    FIELDS, arrays, bound, failure_class, read, reference, require,
    source as legacy_source, TrajectoryDataset as LegacyDataset,
)
SCHEMA = 'embodied-native-trajectory/v2'

def source(spec):
    if spec['adapter'] != 'robocasa_native_v1':
        meta, data = legacy_source(spec)
        return {**meta, 'schema': SCHEMA}, data
    a = arrays(spec['raw'])
    b = read(spec['binding'])
    result = read(spec['result'])
    audit = read(spec['audit'])
    bound(spec['model'])
    rows = b['rows']
    require(audit['status'] == 'saved_audit_pass' and audit['verdict'] == result['status'], 'saved_audit')
    require(audit['unique_physics_steps'] == result['total_unique_steps'] == len(a['target']), 'audit_length')
    require(audit['failures'] == result['failures'], 'audit_failures')
    require(len(rows) == 43 and sorted(r['actuator'] for r in rows) == list(range(43)), 'native_mapping')
    ordered = sorted(rows, key=lambda r: r['actuator'])
    units = ['rad' if r['group'] == 'hand' else 'N*m' for r in ordered]
    require(all(r['ctrl_unit'] == unit for r, unit in zip(ordered, units)), 'native_control_units')
    names = [r['name'] for r in rows]
    n = len(a['target'])
    require(n > 0 and len(a['qpos']) == len(a['qvel']) == len(a['time']) == n + 1, 'trajectory_length')
    require(np.max(abs(np.diff(a['time']) - .002)) < 1e-10, 'time_alignment')
    require(a['target'].shape == a['ctrl_commands'].shape == (n, 43), 'channel_shape')
    require(len(set(names)) == 43, 'duplicate_names')
    proprio = np.concatenate([a['qpos'][:, [r['qpos'] for r in rows]], a['qvel'][:, [r['qvel'] for r in rows]]], axis=1)
    for value in [proprio, a['time'], a['target'], a['ctrl_commands'], a['qpos'], a['qvel']]:
        require(np.isfinite(value).all(), 'nonfinite_source')
    terminated = np.zeros(n, bool)
    truncated = np.zeros(n, bool)
    if result['failures']:
        terminated[-1] = True
    else:
        truncated[-1] = True
    meta = dict(schema=SCHEMA, id=spec['id'], embodiment='G1_RoboCasa_3dex',
                action_names=names, action_units=['rad']*43, action_semantics=['position_reference']*43,
                action_frame='native_mjcf_joint', proprio_names=[s+'_q' for s in names]+[s+'_dq' for s in names],
                proprio_units=['rad']*43+['rad/s']*43, dt=.002, source_status=result['status'], task_success=False,
                scope='failed_native_control_admission', failures=result['failures'], failure_classes=failure_class(result['failures']),
                actual_control_names=[r['name'] for r in ordered], actual_control_units=units,
                actual_control_semantics=['native_position_servo_reference' if r['group']=='hand' else 'native_motor_effort' for r in ordered],
                reference_sample='50Hz lower-body policy; hand reference at substep start; native body PD refreshed every 2ms; 14 hand position servos',
                split='development', transitions=n, camera_present=False, qualified_training=False, learning_effect='unknown',
                observation_timing='observation[i] precedes action[i], next observation[i+1] follows it', privileged_default=False)
    phases = np.array(['standing' if t < 1 else 'left_hand' if t < 3 else 'right_hand' for t in a['time'][:-1]], dtype='S32')
    return meta, dict(time=a['time'], proprio=proprio, action=a['target'], actual_control=a['ctrl_commands'],
                      qpos=a['qpos'], qvel=a['qvel'], terminated=terminated, truncated=truncated, phase=phases)

def export(spec, directory):
    meta, data = source(spec)
    directory = Path(directory)
    directory.mkdir(exist_ok=False)
    with h5py.File(directory/'episode.h5', 'x') as f:
        f.attrs['metadata'] = json.dumps(meta, sort_keys=True)
        for path, key in FIELDS.items():
            f.create_dataset(path, data=data[key], compression='gzip', shuffle=True)
    record = dict(schema=SCHEMA, source=spec, metadata=meta, hdf5=reference(directory/'episode.h5'),
                  implementation=reference(__file__), legacy_implementation=reference(__import__(LegacyDataset.__module__, fromlist=['__file__']).__file__))
    path = directory/'BINDING.json'
    path.write_text(json.dumps(record, indent=2))
    return reference(path)

class TrajectoryDataset(LegacyDataset):
    def __init__(self, binding, pin, purpose='proprio_development', required_modalities=('proprio',)):
        require(purpose in ['inspection', 'proprio_development'], 'purpose_not_qualified')
        record = read(dict(path=str(binding), sha256=pin))
        require(record['schema'] == SCHEMA, 'schema')
        bound(record['implementation'])
        bound(record['legacy_implementation'])
        meta, expected = source(record['source'])
        require(meta == record['metadata'], 'metadata_source_mismatch')
        require(tuple(required_modalities) == ('proprio',), 'camera_or_modality_missing')
        with h5py.File(bound(record['hdf5']), 'r') as f:
            require(json.loads(f.attrs['metadata']) == meta, 'hdf5_metadata')
            for path, key in FIELDS.items():
                require(np.array_equal(f[path][:], expected[key]), 'saved_mismatch:'+path)
            require('rgb' not in f['observation'], 'unexpected_camera')
            self.data = {key: f[path][:] for path, key in FIELDS.items() if key in ['time','proprio','action','terminated','truncated']}
        self.metadata = meta
