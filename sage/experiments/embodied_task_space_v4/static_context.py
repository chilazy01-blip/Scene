"""Native MuJoCo static context reconstructed from sealed FB0 metadata.

This is a geometry-only adapter. It cannot instantiate a policy or advance
physics, and it does not provide a dynamic control or tracking certificate.
"""
from pathlib import Path
import hashlib
import importlib.abc
import json
import os
import sys


def install_static_guards(output):
    output = Path(output).resolve()
    blocked = []

    class ForbiddenRuntime(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname.split('.')[0] in {'torch', 'onnxruntime'}:
                blocked.append(fullname)
                raise RuntimeError('policy_runtime_not_allowed_in_static_worker')
            return None

    assert not any(name in sys.modules for name in ('torch', 'onnxruntime'))
    sys.meta_path.insert(0, ForbiddenRuntime())

    def audit(event, args):
        if event == 'socket.connect':
            blocked.append(event)
            raise RuntimeError('offline_only')
        if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(args[0])).resolve()
            mode, flags = args[1:3]
            write = (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (
                isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)))
            if write and str(path) != '/dev/null' and not path.is_relative_to(output):
                raise RuntimeError('outside_new_root_write')
    sys.addaudithook(audit)
    import mujoco

    def deny(name):
        def call(*args, **kwargs):
            blocked.append(name)
            raise RuntimeError(name + '_forbidden')
        return call

    for name in ('mj_step', 'mj_step1', 'mj_step2', 'mj_integratePos', 'Renderer'):
        if hasattr(mujoco, name):
            setattr(mujoco, name, deny(name))
    return blocked


class StaticContext:
    def __init__(self, bootstrap):
        import numpy as np
        import mujoco
        root = Path(bootstrap)
        binding = json.loads((root / 'BINDING.json').read_text())
        hashes = {entry['path']: entry['sha256'] for entry in binding['files']}
        paths = [root / 'evidence/MODEL_CONTRACT.json',
                 root / 'full_task/task_contact_valid.xml',
                 root / 'full_task/INITIAL_CONTACT_VALID.npz']
        for path in paths:
            assert hashlib.sha256(path.read_bytes()).hexdigest() == hashes[str(path)], path
        assert np.__version__ == '1.26.4' and mujoco.__version__ == '3.3.2'
        contract = json.loads(paths[0].read_text())
        self.rows = contract['rows']
        assert len(self.rows) == 43 and [row['pin'] for row in self.rows] == list(range(43))
        self.names = [row['name'] for row in self.rows]
        self.m = mujoco.MjModel.from_xml_path(str(paths[1]))
        self.d = mujoco.MjData(self.m)
        m, d = self.m, self.d
        assert m.nu == 43 and m.opt.timestep == contract['dt'] and m.neq == 0
        assert not np.any(m.body_gravcomp) and not np.any(d.qfrc_applied) and not np.any(d.xfrc_applied)
        for row in self.rows:
            joint = m.joint(row['label']).id
            actuator = m.actuator(row['label']).id
            assert (joint, actuator) == (row['joint'], row['actuator'])
            assert (int(m.jnt_qposadr[joint]), int(m.jnt_dofadr[joint])) == (row['qpos'], row['qvel'])
            assert m.jnt_type[joint] == mujoco.mjtJoint.mjJNT_HINGE
            assert m.actuator_trnid[actuator, 0] == joint
            assert np.array_equal(m.actuator_gear[actuator], [1, 0, 0, 0, 0, 0])
            assert m.actuator_dyntype[actuator] == 0 and m.actuator_gaintype[actuator] == 0
            assert m.jnt_range[joint, 0] <= row['lower'] <= row['upper'] <= m.jnt_range[joint, 1]
            if row['group'] == 'hand':
                assert m.actuator_biastype[actuator] == 1
                assert np.array_equal(m.actuator_gainprm[actuator, :3], [15, 0, 0])
                assert np.array_equal(m.actuator_biasprm[actuator, :3], [0, -15, -.5])
                assert np.array_equal(m.actuator_ctrlrange[actuator], m.jnt_range[joint])
                effort = min(-m.actuator_forcerange[actuator, 0], m.actuator_forcerange[actuator, 1])
            else:
                assert m.actuator_biastype[actuator] == 0 and m.actuator_gainprm[actuator, 0] == 1
                effort = min(-m.actuator_ctrlrange[actuator, 0], m.actuator_ctrlrange[actuator, 1])
            assert effort == row['effort']
        for key in ('qpos', 'qvel', 'actuator', 'kp', 'kd', 'lower', 'upper', 'effort', 'velocity_limit'):
            setattr(self, key, np.array([row[key] for row in self.rows]))
        self.hand = np.array([row['group'] == 'hand' for row in self.rows])
        self.body = ~self.hand
        self.lower_indices = np.array([row['pin'] for row in self.rows if row['group'] == 'lower'])
        assert len(self.lower_indices) == 15 and int(self.hand.sum()) == 14
        self.nominal = np.asarray(contract['nominal'])
        assert self.nominal.shape == (43,) and np.isfinite(self.nominal).all()
        assert np.all(self.nominal >= self.lower) and np.all(self.nominal <= self.upper)
        with np.load(paths[2], allow_pickle=False) as saved:
            for key in ('qpos', 'qvel', 'ctrl'):
                getattr(d, key)[:] = saved[key]
        self.feet = {side: [g for g in range(m.ngeom)
                     if m.body(m.geom_bodyid[g]).name == 'robot0_' + side + '_ankle_roll_link'
                     and (m.geom_contype[g] or m.geom_conaffinity[g])]
                     for side in ('left', 'right')}
        assert self.feet == contract['feet']
        self.foot_ids = set(self.feet['left'] + self.feet['right'])
        self.floor = m.geom('floor').id
        self.robot_bodies = {b for b in range(m.nbody)
                            if m.body(b).name.startswith(('robot0_', 'gripper0_'))}
        mujoco.mj_forward(m, d)
        self.initialized = True
        self.static_only = True
