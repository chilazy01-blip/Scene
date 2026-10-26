"""Transparent narrow baseline: time-indexed demonstration mean plus learned residual.

The mean trajectory is computed exclusively from training demonstrations. RGB and
proprioception predict a residual. This is deliberately a development baseline,
not evidence of general visual manipulation or language-conditioned learning.
"""
from pathlib import Path
import json

import h5py
import numpy as np
import torch
from torch import nn
from torch.utils.data import TensorDataset, DataLoader

from .common import write, binding
from .environment import TaskEnvironment
from .dataset import save_episode


class ResidualPolicy(nn.Module):
    def __init__(self):
        super().__init__()
        self.vision = nn.Sequential(nn.Conv2d(3, 8, 5, 2, 2), nn.ReLU(),
                                   nn.Conv2d(8, 16, 3, 2, 1), nn.ReLU(),
                                   nn.AdaptiveAvgPool2d((3, 4)), nn.Flatten())
        self.head = nn.Sequential(nn.Linear(192+19, 96), nn.Tanh(), nn.Linear(96, 8))
        nn.init.zeros_(self.head[-1].weight); nn.init.zeros_(self.head[-1].bias)

    def forward(self, rgb, state):
        return self.head(torch.cat([self.vision(rgb), state], dim=1))


def load_split(data_root, split):
    images, states, times, actions = [], [], [], []
    sources = []
    for p in sorted(Path(data_root).glob('*/episode_record.json')):
        meta = json.loads(p.read_text())
        if meta['split'] != split or not meta['outcome']['success']: continue
        with h5py.File(p.parent/'episode.h5', 'r') as f:
            images.append(f['observation/rgb'][:-1, ::2, ::2, :])
            states.append(f['observation/proprio'][:-1]); times.append(f['observation/time'][:-1])
            actions.append(f['action'][:])
        sources.append(binding(p.parent/'episode.h5'))
    if not images: raise ValueError('no_successful_data:' + split)
    return np.stack(images), np.stack(states), np.stack(times), np.stack(actions), sources


def train(data_root, output, epochs=40, seed=918):
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(4); torch.manual_seed(seed); np.random.seed(seed)
    train_data = load_split(data_root, 'train'); val_data = load_split(data_root, 'validation')
    template = train_data[3].mean(axis=0).astype('float32')
    state_mean = train_data[1].reshape(-1,18).mean(0)
    state_std = np.maximum(train_data[1].reshape(-1,18).std(0), .05)
    scale = np.array([.03]*7 + [.01], dtype='float32')

    def tensors(data):
        rgb, state, time, action, _ = data
        x = torch.from_numpy(rgb.reshape(-1, *rgb.shape[2:]).transpose(0,3,1,2).copy()).float()/255
        s = np.concatenate([(state-state_mean)/state_std, time[..., None]/18.7], axis=-1)
        y = (action-template[None])/scale
        return TensorDataset(x, torch.tensor(s.reshape(-1,19), dtype=torch.float32),
                             torch.tensor(y.reshape(-1,8), dtype=torch.float32))
    train_set, val_set = tensors(train_data), tensors(val_data)
    loader = DataLoader(train_set, batch_size=256, shuffle=True, num_workers=0)
    val_loader = DataLoader(val_set, batch_size=512, shuffle=False, num_workers=0)
    model = ResidualPolicy(); optimizer = torch.optim.Adam(model.parameters(), lr=.001)
    history = []; best = float('inf')
    for epoch in range(epochs):
        model.train(); losses = []
        for rgb, state, target in loader:
            optimizer.zero_grad(); predicted = model(rgb, state)
            loss = (predicted-target).square().mean(); loss.backward(); optimizer.step()
            losses.append(float(loss.detach()))
        model.eval(); total=0.; n=0
        with torch.no_grad():
            for rgb, state, target in val_loader:
                total += float((model(rgb,state)-target).square().sum()); n += target.numel()
        validation_loss=total/n
        history.append(dict(epoch=epoch, train_loss=float(np.mean(losses)), validation_loss=validation_loss))
        if validation_loss < best:
            best = validation_loss
            torch.save(dict(model=model.state_dict(), template=template, state_mean=state_mean, state_std=state_std,
                            scale=scale, epoch=epoch, seed=seed), output/'policy.pt')
        if epoch % 10 == 0: print('training', history[-1], flush=True)
    write(output/'training.json', dict(architecture='time-indexed train demonstration mean + RGB/proprio residual BC',
          input='downsampled RGB, robot qpos/qvel, normalized elapsed time; no object state, task truth, reference plan or test data',
          selection='minimum held-out validation action MSE', seed=seed, epochs=epochs,
          history=history, training_sources=train_data[4], validation_sources=val_data[4],
          checkpoint=binding(output/'policy.pt'), limitation='single task, fixed duration; time template may dominate vision'))


class LearnedPolicy:
    def __init__(self, checkpoint, mode='learned'):
        torch.set_num_threads(2)
        # Only a checkpoint produced by this package is loaded, never untrusted files.
        self.saved = torch.load(checkpoint, map_location='cpu', weights_only=False)
        self.model=ResidualPolicy(); self.model.load_state_dict(self.saved['model']); self.model.eval()
        self.mode=mode; self.clipped_actions=0

    def __call__(self, observation, joint_ranges):
        k=min(round(observation['time']/.05), len(self.saved['template'])-1)
        action=self.saved['template'][k].copy()
        if self.mode != 'template_only':
            rgb=observation['rgb'][::2,::2].transpose(2,0,1).copy()
            if self.mode == 'zero_rgb': rgb=np.zeros_like(rgb)
            state=np.r_[(observation['proprio']-self.saved['state_mean'])/self.saved['state_std'], observation['time']/18.7]
            with torch.no_grad():
                delta=self.model(torch.tensor(rgb[None],dtype=torch.float32)/255,
                                 torch.tensor(state[None],dtype=torch.float32)).numpy()[0]
            action += delta*self.saved['scale']
        clipped=action.copy()
        clipped[:7]=np.clip(clipped[:7],joint_ranges[:,0]+.001,joint_ranges[:,1]-.001)
        clipped[7]=np.clip(clipped[7],0,.04)
        self.clipped_actions += int(not np.array_equal(clipped,action))
        return clipped


def evaluate(scene, output, seed, checkpoint, mode='learned', split='test'):
    output=Path(output); output.mkdir(parents=True,exist_ok=False)
    env=TaskEnvironment(scene); policy=LearnedPolicy(checkpoint,mode)
    try:
        obs=env.reset(seed)
        while not env.stopped:
            action=policy(obs,env.model.jnt_range[env.ctrl.joints]); obs=env.step(action)
        save_episode(env,output,policy=mode,split=split,checkpoint=binding(checkpoint))
        write(output/'policy_audit.json',dict(mode=mode,clipped_actions=policy.clipped_actions,
              ground_truth_access=False,reference_plan_used=False,task_goal_input=False,
              time_template_from_training_only=True))
        return env.evaluate()
    finally:
        env.close()
