"""Portable HDF5 episodes and a PyTorch-compatible temporal reader."""
from pathlib import Path
import json
import traceback

import h5py
import numpy as np

from .common import write, binding
from .environment import TaskEnvironment


def save_episode(env, output, *, policy, split, checkpoint=None):
    output = Path(output)
    t = len(env.actions)
    if len(env.observations) != t + 1 or len(env.states) != t + 1:
        raise ValueError('transition_alignment_failure')
    with h5py.File(output / 'episode.h5', 'w') as f:
        f.attrs.update(schema='scene-simulation-data/v0', policy=policy, split=split,
                       scene_id=env.config['scene_id'], seed=env.seed, success=bool(env.evaluate()['success']))
        f.create_dataset('action', data=np.asarray(env.actions).reshape(t, 8))
        f.create_dataset('observation/proprio', data=[o['proprio'] for o in env.observations])
        f.create_dataset('observation/time', data=[o['time'] for o in env.observations])
        if env.renderer is not None:
            f.create_dataset('observation/rgb', data=np.array([o['rgb'] for o in env.observations]),
                             compression='gzip', compression_opts=1, chunks=(1, env.height, env.width, 3))
        f.create_dataset('privileged/integration_state', data=env.states, compression='gzip')
        f.create_dataset('privileged/audit_1khz', data=env.audit_rows, compression='gzip')
        f['privileged/audit_1khz'].attrs['columns'] = json.dumps(
            ['state_time', 'solver_time', 'speed', 'support_force', 'finger_contact', 'bilateral_contact', 'goal_error', 'target_z'])
        f.attrs['state_spec'] = int(env.mask)
    write(output / 'episode_record.json', dict(schema='scene-simulation-data/v0', scene_id=env.config['scene_id'],
          seed=env.seed, split=split, policy=policy, outcome=env.evaluate(), metrics=env.metrics,
          actions=t, observations=t+1, instruction=env.active['instruction'],
          task=env.active, file=binding(output / 'episode.h5'), checkpoint=checkpoint,
          render_profile=env.render_profile,
          runtime_code={name:binding(Path(__file__).with_name(name)) for name in
                        ['environment.py','controller.py','dataset.py','common.py']},
          reference_ik_continuity_regularizer=.01 if policy.startswith('privileged_reference') else None))
    write(output / 'camera.json', env.camera_calibration())
    write(output / 'support_validation.json', env.support)
    if env.renderer is not None:
        write(output / 'render_backend.json', env.render_backend)


def collect(scene, output, seed, split, *, visual=True):
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    env = None
    try:
        env = TaskEnvironment(scene, render=visual)
        env.reset(seed)
        plan = env.plan_reference()
        write(output / 'controller_plan.json', plan)
        while not env.stopped:
            env.step(env.reference_action())
            if env.steps % 100 == 0:
                print('collection', seed, env.steps, '/374', flush=True)
        save_episode(env, output, policy='privileged_reference_joint_trajectory', split=split)
        return env.evaluate()
    except BaseException:
        write(output / 'failure.json', dict(status='infrastructure_error', traceback=traceback.format_exc(),
                                          seed=seed, split=split))
        raise
    finally:
        if env is not None: env.close()


class EpisodeDataset:
    """Only declared policy observations are returned; privileged fields excluded."""
    def __init__(self, root, split='train', successful_only=True):
        self.root = Path(root)
        self.rows = []
        for p in sorted(self.root.glob('*/episode_record.json')):
            meta = json.loads(p.read_text())
            if meta['split'] == split and (not successful_only or meta['outcome']['success']):
                self.rows.extend((p.parent / 'episode.h5', i) for i in range(meta['actions']))

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, index):
        path, k = self.rows[index]
        with h5py.File(path, 'r') as f:
            return dict(rgb=f['observation/rgb'][k], proprio=f['observation/proprio'][k],
                        time=f['observation/time'][k], action=f['action'][k],
                        next_rgb=f['observation/rgb'][k+1], next_proprio=f['observation/proprio'][k+1],
                        next_time=f['observation/time'][k+1])


def validate_dataset(root):
    rows = []
    keys = set()
    for p in sorted(Path(root).glob('*/episode_record.json')):
        meta = json.loads(p.read_text()); key = (meta['scene_id'], meta['seed'])
        if key in keys: raise ValueError('duplicate_scene_seed')
        keys.add(key)
        path = p.parent / 'episode.h5'
        if binding(path)['sha256'] != meta['file']['sha256']: raise ValueError('data_hash_mismatch')
        with h5py.File(path, 'r') as f:
            t = len(f['action']); times = f['observation/time'][:]
            assert t == meta['actions'] and len(times) == t+1
            assert np.allclose(times, np.arange(t+1)*.05, atol=1e-9, rtol=0)
            assert len(f['observation/rgb']) == t+1 and f['observation/rgb'].dtype == np.uint8
            assert f['observation/proprio'].shape == (t+1, 18)
            assert len(f['privileged/integration_state']) == t+1
            assert len(f['privileged/audit_1khz']) == 50*t
            for name in ['action', 'observation/proprio', 'privileged/integration_state', 'privileged/audit_1khz']:
                assert np.isfinite(f[name][:]).all(), name
            assert np.any(f['observation/rgb'][0] != f['observation/rgb'][-1])
        rows.append(dict(episode=p.parent.name, split=meta['split'], success=meta['outcome']['success'], transitions=t))
    if not rows: raise ValueError('empty_dataset')
    return dict(passed=True, episodes=len(rows), transitions=sum(r['transitions'] for r in rows), rows=rows)
