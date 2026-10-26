"""Strict, source-pinned numerical HMG ingestion; separate from FB2 admission.

The 35D action is [upper_body(31), navigation(3), height(1)], matching
upstream train_policy_example.py. Simulator goal columns are labels only.
No simulator state, future observation, task phase or success enters inputs.
"""
from pathlib import Path
import hashlib
import json

import numpy as np
import pyarrow.parquet as pq

STATE = 'observation.state'
SOURCES = ('observation.sim.target_upper_body_pose',
           'teleop.navigate_command', 'teleop.base_height_command')
ACTION_NAMES = [f'target_upper_body_pose_{i}' for i in range(31)] + [
    'navigate_x', 'navigate_y', 'navigate_yaw', 'base_height']
SYSTEM = ('timestamp', 'frame_index', 'episode_index', 'task_index')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_arrays(arrays, info, contract):
    """Fail closed on missing, mixed-episode, reordered, or malformed records."""
    features = info['features']
    for key, size in [(STATE, 43), *zip(SOURCES, (31, 3, 1))]:
        if features.get(key, {}).get('shape') != [size]:
            raise ValueError('metadata_shape:' + key)
        if key not in arrays or arrays[key].shape != (contract['rows'], size):
            raise ValueError('array_shape:' + key)
        if not np.isfinite(arrays[key]).all():
            raise ValueError('nonfinite:' + key)
    if features[STATE].get('names') != contract['joint_names']:
        raise ValueError('joint_order')
    if info.get('fps') != contract['fps']:
        raise ValueError('fps')
    count = contract['rows']
    for key in SYSTEM:
        if key not in arrays or arrays[key].shape != (count,):
            raise ValueError('index_shape:' + key)
        if not np.isfinite(arrays[key]).all():
            raise ValueError('nonfinite:' + key)
    if not np.array_equal(arrays['frame_index'], np.arange(count)):
        raise ValueError('frame_order')
    for key in ('episode_index', 'task_index'):
        if not np.all(arrays[key] == contract[key]):
            raise ValueError('mixed_or_wrong:' + key)
    if not np.allclose(arrays['timestamp'], np.arange(count) / contract['fps'],
                       atol=contract['timestamp_tolerance_s'], rtol=0):
        raise ValueError('timestamp_alignment')


def read_source(root, contract):
    root = Path(root)
    for name, expected in contract['files'].items():
        if digest(root / name) != expected:
            raise ValueError('source_hash:' + name)
    info = json.loads((root / 'info.json').read_text())
    table = pq.read_table(root / 'episode_000000.parquet', columns=[STATE, *SOURCES, *SYSTEM])
    arrays = {key: np.asarray(table[key].to_pylist()) for key in table.column_names}
    # Scalar features may be represented by one-element lists in source Parquet.
    for key in SYSTEM:
        arrays[key] = arrays[key].reshape(-1)
    if arrays[SOURCES[-1]].ndim == 1:
        arrays[SOURCES[-1]] = arrays[SOURCES[-1]][:, None]
    validate_arrays(arrays, info, contract)
    return arrays, info


def public_training_arrays(arrays):
    # Drop the final recorded row: it lacks a following recorded transition.
    state = np.asarray(arrays[STATE][:-1], dtype=np.float32)
    action = np.concatenate([arrays[key][:-1] for key in SOURCES], axis=-1).astype(np.float32)
    if not np.isfinite(state).all() or not np.isfinite(action).all():
        raise ValueError('float32_overflow')
    return state, action


def export_lerobot(root, arrays, info, contract):
    """Actual installed upstream writer; numerical subset explicitly has no RGB."""
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    root = Path(root)
    state, action = public_training_arrays(arrays)
    dataset = LeRobotDataset.create(
        repo_id='local/hmg_external_numeric_smoke', fps=contract['fps'], root=root,
        robot_type='unitree_g1_43d', use_videos=False, video_backend='pyav',
        features={STATE: dict(dtype='float32', shape=(43,), names=contract['joint_names']),
                  'action': dict(dtype='float32', shape=(35,), names=ACTION_NAMES)})
    for index in range(len(state)):
        dataset.add_frame({STATE: state[index], 'action': action[index]},
                          task='Move a box from the table to the shelf.',
                          timestamp=float(arrays['timestamp'][index]))
    dataset.save_episode()
    provenance = dict(schema='external-numeric-training-subset/v1', source=contract,
        learner_observations=[STATE], targets=['action'], action_names=ACTION_NAMES,
        action_source_columns=list(SOURCES), source_frame_range_inclusive=[0, len(state)-1],
        terminal_source_row_excluded=len(state), source_rows=len(state)+1,
        image_available=False, depth_available=False, exact_episode_scene_available=False,
        serialized_row_alignment_verified=True, physical_sensor_latency_verified=False,
        episode_task_success_independently_verified=False, origin='external',
        qualified_self_generated=False, admitted_fb2=False, training_scope='interface_smoke_only')
    (root / 'PROVENANCE.json').write_text(json.dumps(provenance, indent=2)+'\n')
    return state, action


def masked_mse(prediction, target, pad_mask):
    """Padded horizon positions never enter the loss, including their targets."""
    import torch
    if prediction.shape != target.shape or pad_mask.shape != target.shape[:-1]:
        raise ValueError('loss_shape')
    valid = ~pad_mask.bool()
    if not torch.any(valid):
        raise ValueError('empty_target_mask')
    return (prediction[valid] - target[valid]).square().mean()
