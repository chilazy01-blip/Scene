"""Keep completed transitions and explicitly represent interrupted actions."""
import json
import os
from pathlib import Path

import h5py
import numpy as np


def finite_json(value):
    if isinstance(value, dict):
        return {k: finite_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [finite_json(v) for v in value]
    if isinstance(value, (float, np.floating)) and not np.isfinite(value):
        return None
    return value


class Recorder:
    def __init__(self, env, directory):
        self.env = env
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.actions, self.phases, self.attempts, self.interrupted = [], [], [], []
        self.states = [env.state()]
        self.proprio = [env.observe()['proprio']]
        self.times = [float(env.data.time)]

    def journal(self, value):
        with (self.directory/'ACTION_JOURNAL.jsonl').open('a') as stream:
            stream.write(json.dumps(finite_json(value), allow_nan=False) + '\n')
            stream.flush()
            os.fsync(stream.fileno())

    def step(self, action, phase):
        env = self.env
        action = np.asarray(action, dtype=float).copy()
        if action.shape != (8,) or not np.isfinite(action).all():
            raise ValueError('invalid_action_before_dispatch')
        row = dict(index=len(self.attempts), action=action.tolist(), phase=phase,
                   start_native_steps=env.native_steps, start_time_s=float(env.data.time),
                   completed_transition_index=len(self.actions), status='pending')
        self.attempts.append(row)
        self.journal(dict(event='intent', **row))
        error = None
        try:
            return env.step(action)
        except BaseException as exc:
            error = type(exc).__name__ + ':' + str(exc)
            raise
        finally:
            steps = env.native_steps - row['start_native_steps']
            state = env.state()
            proprio = env.observe()['proprio']
            now = float(env.data.time)
            row.update(executed_substeps=int(steps), end_time_s=now, error=error,
                       terminal_state_finite=bool(np.isfinite(state).all()))
            if steps == 50:
                row['status'] = 'completed' if error is None else 'completed_with_error'
                self.actions.append(action)
                self.phases.append(phase)
                self.states.append(state)
                self.proprio.append(proprio)
                self.times.append(now)
            else:
                row['status'] = 'interrupted' if steps else 'rejected_before_physics'
                self.interrupted.append(dict(attempt_index=row['index'], action=action,
                    phase=phase, state=state, proprio=proprio, time_s=now,
                    executed_substeps=int(steps), start_state_index=len(self.states)-1))
            self.journal(dict(event='outcome', **row))

    def dump(self, path, seed, result, binding):
        env = self.env
        with h5py.File(path, 'w') as h:
            h.attrs.update(schema='M2-episode/v2', source='privileged_OMPL_planned_expert',
                success=result['status']=='success', seed=seed, physics_dt_s=.001,
                action_dt_s=.05, state_spec=int(env.mask),
                protocol_sha256=binding.get('protocol_sha256', ''),
                source_manifest_sha256=binding.get('manifest_sha256', ''))
            h.create_dataset('action', data=np.asarray(self.actions).reshape(-1,8), compression='gzip')
            h.create_dataset('observation/proprio', data=np.asarray(self.proprio), compression='gzip')
            h.create_dataset('observation/time', data=self.times)
            h.create_dataset('privileged/state', data=np.asarray(self.states), compression='gzip')
            h.create_dataset('privileged/phase', data=np.asarray(self.phases,dtype=h5py.string_dtype()))
            h.create_dataset('privileged/audit_1khz', data=np.asarray(env.audit_rows).reshape(-1,11),compression='gzip')
            h.create_dataset('privileged/contacts_1khz', data=np.asarray(env.contact_rows).reshape(-1,11),compression='gzip')
            terminal=h.create_group('terminal')
            terminal.create_dataset('state',data=env.state())
            terminal.create_dataset('proprio',data=env.observe()['proprio'])
            terminal.attrs.update(time_s=float(env.data.time),native_steps=env.native_steps)
            attempts=h.create_group('attempted')
            attempts.create_dataset('action',data=np.asarray([x['action'] for x in self.attempts]).reshape(-1,8))
            attempts.create_dataset('executed_substeps',data=[x['executed_substeps'] for x in self.attempts])
            attempts.create_dataset('status',data=np.asarray([x['status'] for x in self.attempts],dtype=h5py.string_dtype()))
            for i,row in enumerate(self.interrupted):
                group=h.create_group(f'interrupted/{i}')
                for field in ['action','state','proprio']:group.create_dataset(field,data=row[field])
                for field in ['attempt_index','phase','time_s','executed_substeps','start_state_index']:group.attrs[field]=row[field]
        return dict(completed_actions=len(self.actions),observations=len(self.states),
                    attempted_actions=len(self.attempts),interrupted_actions=len(self.interrupted),
                    recorded_substeps=sum(x['executed_substeps'] for x in self.attempts),
                    actual_native_steps=env.native_steps)
