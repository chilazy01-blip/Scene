"""Reconstruct the retained source walk-to command and stopping event from saved states."""
import numpy as np
import mujoco
import h5py
from .work import E, c, finish

folder = E / 'jobs/C_development_03/episode'
m = mujoco.MjModel.from_binary_path(str(folder / 'MODEL.mjb'))
d = mujoco.MjData(m)
goal, heading, tolerance = np.array([-.40, .10]), .35, .07
start, stop = 6752, 6880
records, stop_events = [], []
with h5py.File(folder / 'TRACE.h5', 'r') as f:
    policy = f['policy/walker_onnx']
    rows = policy['physics_row'][:]
    command_key = next(iter(policy['input']))
    for row in range(start, stop + 1):
        mujoco.mj_setState(m, d, f['substep/integration_before'][row], mujoco.mjtState.mjSTATE_INTEGRATION)
        distance = float(np.linalg.norm(goal - d.qpos[:2]))
        if distance < tolerance:
            stop_events.append({'row': row, 'time': float(d.time), 'distance_m': distance})
        if row % 8:
            continue
        w, x, y, z = d.qpos[3:7]
        yaw = np.arctan2(2 * (w * z + x * y), 1 - 2 * (y*y + z*z))
        dx, dy = goal - d.qpos[:2]
        error = np.array([np.cos(yaw)*dx + np.sin(yaw)*dy, -np.sin(yaw)*dx + np.cos(yaw)*dy])
        magnitude = np.linalg.norm(error)
        scale = error / max(magnitude, 1e-6)
        speed = max(min(2 * magnitude, .4), .30)
        yaw_error = np.arctan2(np.sin(heading - yaw), np.cos(heading - yaw))
        candidate = np.clip([speed * scale[0], np.clip(speed * scale[1], -.3, .3),
                             np.clip(1.5 * yaw_error, -.6, .6)], [-.4, -.2, -.3], [.4, .2, .3]).astype('f4')
        if stop_events:
            candidate[:] = 0.
        idx = int(np.searchsorted(rows, row)); assert rows[idx] == row
        actual = policy['input'][command_key][idx].reshape(-1)[-3:]
        records.append({'row': row, 'time': float(d.time), 'base_xy': d.qpos[:2].tolist(),
                        'base_yaw_rad': float(yaw), 'distance_m': distance,
                        'saved_command': actual.tolist(), 'reconstructed_command': candidate.tolist(),
                        'max_error': float(np.max(abs(actual - candidate)))})
report = {'physics_steps': 0, 'policy_calls': 0, 'assumed_source_goal_xy': goal.tolist(),
          'assumed_source_goal_yaw': heading, 'source_position_tolerance_m': tolerance,
          'first_observed_position_tolerance_entry': stop_events[0] if stop_events else None,
          'records': records, 'command_reconstruction_passed': all(r['max_error'] == 0 for r in records),
          'scope': 'Read-only source-law reconstruction; no claim about a repaired stop or dynamic counterfactual.',
          'production_accepted': False}
c.write(E / 'C3_WALK_STOP_COMMAND_RECONSTRUCTION.json', report); finish(report)
