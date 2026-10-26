"""Portable immutable-shard assembly with independent saved-source audit."""
import os
import sys
from pathlib import Path
import numpy as np
import h5py
import mujoco
from .work import c, finish


def main(config_path):
    cfg = c.read(config_path)
    work = Path(os.environ['CONTINUOUS_JOB_DIR'])
    root = work / 'assembled'
    (root / 'chunks').mkdir(parents=True)
    source = Path(cfg['source_episode'])
    numeric = Path(cfg['numeric_source'])
    audit = Path(cfg['source_audit_job'])
    trace_hash, numeric_hash = c.sha(source / 'TRACE.h5'), c.sha(numeric)
    assert c.read(audit / 'AUDIT.json')['passed']
    assert c.read(audit / 'REQUEST.json')['inputs'][str(source / 'TRACE.h5')] == trace_hash
    assert c.read(audit / 'AUDIT.json')['independent_process_continuous_reintegration_and_policy_recompute']
    records, paths, cursor, boundaries = [], None, 0, set()
    for j, folder_name in enumerate(cfg['shard_jobs']):
        folder = Path(folder_name)
        binding = c.read(folder / 'SHARD_BINDING.json')
        assert binding['complete'] and binding['shard_sha256'] == c.sha(folder / 'shard.h5')
        assert binding['first_frame'] == cursor and binding['rows'] == binding['stop_frame'] - cursor
        assert binding['numeric_source_sha256'] == numeric_hash and binding['source_trace_sha256'] == trace_hash
        assert binding['RGBD_hz'] == 25 and binding['size'] == [256, 256]
        boundaries.update([cursor, binding['stop_frame'] - 1])
        cursor = binding['stop_frame']
        target = root / 'chunks' / f'{j:04d}.h5'
        os.link(folder / 'shard.h5', target)
        with h5py.File(target, 'r') as f:
            assert f.attrs['complete']
            schema = []
            f.visititems(lambda name, obj: schema.append((name, obj.shape[1:], str(obj.dtype)))
                         if isinstance(obj, h5py.Dataset) else None)
            if paths is None:
                paths = schema
            assert paths == schema
        records.append({'relative_path': str(target.relative_to(root)), 'rows': binding['rows'],
                        'first_frame': binding['first_frame'], 'sha256': binding['shard_sha256']})
    assert cursor == cfg['expected_rows']
    with h5py.File(root / 'canonical.h5', 'w', libver='latest') as out, h5py.File(numeric, 'r') as n:
        complete_episode = cursor == len(n['source_substep_indices'])
        assert complete_episode == cfg['complete_source_episode']
        for key, value in n.attrs.items():
            out.attrs[key] = value
        out.attrs['segment_truncated'] = not complete_episode
        for name, tail, dtype in paths:
            layout = h5py.VirtualLayout(shape=(cursor, *tail), dtype=np.dtype(dtype))
            for record in records:
                start, count = record['first_frame'], record['rows']
                layout[start:start + count] = h5py.VirtualSource(record['relative_path'], name, shape=(count, *tail))
            out.create_virtual_dataset(name, layout)
    # Stream every field through the VDS and independently opened chunks. This
    # covers all boundaries without requiring full-episode image arrays in RAM.
    with h5py.File(root / 'canonical.h5', 'r') as merged:
        for record in records:
            start, count = record['first_frame'], record['rows']
            with h5py.File(root / record['relative_path'], 'r') as shard:
                for name, _, _ in paths:
                    for offset in range(0, count, 16):
                        length = min(16, count - offset)
                        assert np.array_equal(merged[name][start + offset:start + offset + length],
                                              shard[name][offset:offset + length]), name
    m = mujoco.MjModel.from_binary_path(str(source / 'MODEL.mjb'))
    d = mujoco.MjData(m)
    names = [m.joint(j).name for j in range(m.njnt) if m.jnt_type[j] == mujoco.mjtJoint.mjJNT_HINGE]
    qa = [m.jnt_qposadr[m.joint(n).id] for n in names]
    va = [m.jnt_dofadr[m.joint(n).id] for n in names]
    aids = [m.actuator(n).id for n in names]
    errors, rays = {}, []
    cameras = ['overhead', 'wrist_cam']
    samples = boundaries | set(np.linspace(0, cursor - 1, 12, dtype=int))
    mujoco.mj_step = lambda *a, **kw: (_ for _ in ()).throw(AssertionError('no_integration'))
    def compare(key, actual, expected):
        error = float(np.max(abs(np.asarray(actual, dtype=float) - np.asarray(expected, dtype=float))))
        errors[key] = max(errors.get(key, 0.), error)
    with h5py.File(root / 'canonical.h5', 'r') as h, h5py.File(source / 'TRACE.h5', 'r') as f:
        indices = h['source_substep_indices'][:]
        assert np.array_equal(indices, np.arange(cursor) * 16)
        steps = len(f['substep/time_before'])
        for i, k in enumerate(indices):
            mujoco.mj_setState(m, d, f['substep/integration_before'][k], mujoco.mjtState.mjSTATE_INTEGRATION)
            compare('timestamp', h['trajectory/timestamp'][i], f['substep/time_before'][k])
            compare('joint_position', h['trajectory/joint_position'][i], d.qpos[qa])
            compare('joint_velocity', h['trajectory/joint_velocity'][i], d.qvel[va])
            compare('base_quaternion', h['trajectory/base_orientation_wxyz'][i], d.qpos[3:7])
            compare('base_gyro', h['trajectory/base_gyro_rps'][i], d.qvel[3:6])
            compare('previous_command_valid', h['trajectory/previous_command_valid'][i], int(k > 0))
            compare('previous_command', h['trajectory/previous_command'][i],
                    f['substep/ctrl'][k - 1][aids] if k else np.zeros(43))
            compare('done', h['trajectory/done'][i], int(complete_episode and i == cursor - 1))
            for j in range(2):
                row = int(k + j * 8)
                valid = row < steps
                compare('action_valid', h['trajectory/action_valid'][i, j], int(valid))
                compare('action', h['trajectory/action_chunk'][i, j],
                        f['substep/ctrl'][row][aids] if valid else np.zeros(43))
                compare('action_time', h['trajectory/action_timestamps'][i, j],
                        f['substep/time_before'][row] if valid else d.time + .02 * j)
            mujoco.mj_forward(m, d)
            rb = np.zeros(9); mujoco.mju_quat2Mat(rb, d.qpos[3:7]); rb = rb.reshape(3, 3)
            for camera in cameras:
                group = h['cameras/' + camera]
                cid = m.camera(camera).id
                rotation = d.cam_xmat[cid].reshape(3, 3) @ np.diag([1., -1., -1.])
                origin = d.cam_xpos[cid].copy()
                focal = 128. / np.tan(np.radians(m.cam_fovy[cid]) / 2.)
                K = np.array([[focal, 0., 128.], [0., focal, 128.], [0., 0., 1.]])
                compare('intrinsics', group['K'][i], K)
                T = np.eye(4); T[:3, :3] = rb.T @ rotation; T[:3, 3] = rb.T @ (origin - d.qpos[:3])
                compare('extrinsics', group['optical_to_base'][i], T)
                depth, valid = group['depth_m'][i], group['valid'][i]
                assert np.isfinite(depth).all() and np.all(depth > 0.)
                near = float(m.vis.map.znear * m.stat.extent)
                far = float(m.vis.map.zfar * m.stat.extent)
                assert np.array_equal(valid, ((depth > near) & (depth < far * (1 - 1e-5))).astype('u1'))
                if i not in samples:
                    continue
                for u, v in [(96, 96), (128, 128), (160, 160), (112, 176), (176, 112)]:
                    if not valid[v, u]:
                        continue
                    ray = np.array([(u + .5 - 128.) / focal, (v + .5 - 128.) / focal, 1.])
                    length = np.linalg.norm(ray); direction = rotation @ ray / length
                    distance = mujoco.mj_ray(m, d, origin + direction * near * length, direction,
                                             np.array([1, 1, 1, 0, 0, 0], np.uint8), 1, -1, np.zeros(1, np.int32))
                    if distance < 0:
                        continue
                    expected = (distance + near * length) / length
                    rays.append({'frame': int(i), 'camera': camera, 'pixel': [u, v],
                                 'absolute_error_m': abs(float(depth[v, u]) - expected)})
    assert all(value <= (1e-12 if key in ['extrinsics', 'intrinsics'] else 0.) for key, value in errors.items()), errors
    assert rays and max(x['absolute_error_m'] for x in rays) < .003, rays
    binding = {'completed': True, 'rows': cursor, 'chunks': records, 'cameras': cameras,
               'canonical_sha256': c.sha(root / 'canonical.h5'), 'canonical_independent_audit_passed': True,
               'source_trace_sha256': trace_hash, 'source_numeric_sha256': numeric_hash,
               'source_audit_sha256': c.sha(audit / 'AUDIT.json'),
               'physical_source_independent_reintegration': True,
               'all_shard_fields_exact': True, 'independent_source_maximum_errors': errors,
               'ray_depth_checks': rays, 'max_ray_depth_error_m': max(x['absolute_error_m'] for x in rays),
               'complete_physical_task_record': complete_episode, 'segment_truncated': not complete_episode,
               'task_success': False, 'production_accepted': False, 'task_learning_verified': False,
               'joint_names': names, 'new_physics_steps': 0, 'new_render_passes': 0,
               'scope': 'Previously independently reintegrated failed task; all-row numeric/camera/mask audit, sampled geometric depth rays, immutable shard hashes and streamed VDS equality. No image rerender is claimed here.'}
    c.write(root / 'BINDING.json', binding)
    finish(binding)


if __name__ == '__main__':
    main(sys.argv[1])
