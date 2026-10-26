"""Bounded engineering workers for the approved contact-recovery run."""
from pathlib import Path
import os
import sys
import time
from sage.experiments.embodied_continuous_v2 import controller as c

P = Path('/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/feasibility_guard_v4/prepared/payload_data_20261009')
R = P / 'native_parallel_12h_20261011'
E = P / 'contact_recovery_run_20261011'


def finish(report, usage=None):
    job = Path(os.environ['CONTINUOUS_JOB_DIR'])
    c.write(job / 'RESULT.json', {'outcome': 'success', **report})
    c.write(job / 'USAGE_FINAL.json', {'complete': True, 'request_sha256': c.sha(job / 'REQUEST.json'),
                                     'usage': usage or {}})


def runtime():
    import importlib
    import resource
    manifest = c.read(R / 'shared/ENV37_MANIFEST.json')
    modules = {}
    for name in ['mujoco', 'numpy', 'onnxruntime', 'h5py', 'scipy']:
        m = importlib.import_module(name)
        modules[name] = {'version': m.__version__, 'path': m.__file__}
    assert all(modules[x['package']]['version'] == x['version'] for x in manifest['packages'])
    assert all(c.sha(x['wheel']) == x['sha256'] for x in manifest['packages'])
    affinity = sorted(os.sched_getaffinity(0))
    memory = resource.getrlimit(resource.RLIMIT_AS)
    assert len(affinity) <= 4 and memory[1] <= 5.5 * 1024**3
    report = {'passed': True, 'modules': modules, 'affinity': affinity,
              'address_space_limits_bytes': memory, 'new_download_bytes': 0,
              'physics_steps': 0, 'manifest_sha256': c.sha(R / 'shared/ENV37_MANIFEST.json')}
    c.write(E / 'RUNTIME_RESOURCE_ADMISSION.json', report)
    finish(report)


def first_failure():
    import numpy as np
    import h5py
    import mujoco
    folder = R / 'jobs/A_target_02/episode'
    model = mujoco.MjModel.from_binary_path(str(folder / 'MODEL.mjb'))
    with h5py.File(folder / 'TRACE.h5', 'r') as f:
        contacts = f['contacts/rows'][:]
        bad = contacts[contacts[:, 3] < -.01]
        assert len(bad)
        row = bad[0]
        k, g1, g2 = map(int, row[:3])
        names = [model.geom(g).name for g in [g1, g2]]
        all_pairs = {}
        for x in bad:
            a, b = int(x[1]), int(x[2])
            key = '|'.join([model.geom(a).name or str(a), model.geom(b).name or str(b)])
            if key not in all_pairs:
                all_pairs[key] = {'first_step': int(x[0]), 'max_penetration_m': 0., 'contact_rows': 0}
            all_pairs[key]['max_penetration_m'] = max(all_pairs[key]['max_penetration_m'], float(-x[3]))
            all_pairs[key]['contact_rows'] += 1
        aid = [i for i in range(model.nu) if 'right_hand' in model.actuator(i).name]
        joint = model.joint('red_block_joint').id
        qa = int(model.jnt_qposadr[joint])
        report = {'no_integration': True, 'source': str(folder), 'first_over_10mm': {
            'step': k, 'time_before': float(f['substep/time_before'][k]), 'geoms': names,
            'penetration_m': float(-row[3]), 'contact_force_local': row[7:13].tolist(),
            'object_pose': f['substep/qpos'][k, qa:qa+7].tolist(),
            'actual_ctrl': f['substep/ctrl'][k].tolist(),
            'finger_actuators': [model.actuator(i).name for i in aid],
            'finger_ctrl': f['substep/ctrl'][k, aid].tolist(),
            'finger_actual_force': f['substep/actuator_force'][k, aid].tolist()},
            'violating_pairs': all_pairs,
            'object': {'mass_kg': float(model.body_mass[model.body('red_block').id]),
                       'inertia': model.body_inertia[model.body('red_block').id].tolist()},
            'contact_material': {model.geom(g).name: {'friction': model.geom_friction[g].tolist(),
                 'solref': model.geom_solref[g].tolist(), 'solimp': model.geom_solimp[g].tolist(),
                 'size': model.geom_size[g].tolist()} for g in [g1, g2, model.geom('table_white_top').id]},
            'dt': float(model.opt.timestep), 'integrator': int(model.opt.integrator),
            'production_accepted': False,
            'calibration_status': 'model parameters recorded; source/calibration and transient evidence pending'}
        start, end = max(0,k-80), min(k+80,len(f['substep/qpos']))
        out = E / 'evidence/FIRST_PENETRATION_WINDOW.npz'
        np.savez_compressed(out, qpos=f['substep/qpos'][start:end], qvel=f['substep/qvel'][start:end],
                            ctrl=f['substep/ctrl'][start:end], time=f['substep/time_before'][start:end],
                            source_rows=np.arange(start,end), contacts=contacts[(contacts[:,0]>=start)&(contacts[:,0]<end)])
    c.write(E / 'FIRST_QUALITY_FAILURE_AND_REPAIR.json', report)
    finish(report)


if __name__ == '__main__':
    {'runtime': runtime, 'first_failure': first_failure}[sys.argv[1]]()
