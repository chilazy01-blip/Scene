"""Measure encoder creep and relative object motion in the saved C3 alignment."""
import numpy as np
import h5py
import mujoco
from scipy.spatial.transform import Rotation
from .work import E, c, finish

folder = E / 'jobs/C_development_03/episode'
m = mujoco.MjModel.from_binary_path(str(folder / 'MODEL.mjb'))
d = mujoco.MjData(m)
obj, sid = m.body('red_block').id, m.site('right_palm').id
aids = np.array([a for a in range(m.nu) if m.actuator(a).name.startswith('right_hand')])
qa = m.jnt_qposadr[m.actuator_trnid[aids, 0]]
va = m.jnt_dofadr[m.actuator_trnid[aids, 0]]
loss = c.read(E / 'C3_PLACEMENT_LOSS_CAUSAL_ANALYSIS_R3.json')['first_zero_hand_contacts_during_alignment_row']
records = []
with h5py.File(folder / 'TRACE.h5', 'r') as f:
    start = int(f['feedback/physics_row'][0])
    rows = sorted(set([start, *range(start, loss + 1, 80), loss - 1, loss]))
    ref_p = ref_r = ref_q = None
    for k in rows:
        mujoco.mj_setState(m, d, f['substep/integration_before'][k], mujoco.mjtState.mjSTATE_INTEGRATION)
        mujoco.mj_forward(m, d)
        wrist = d.site_xmat[sid].reshape(3, 3)
        relative_p = wrist.T @ (d.xpos[obj] - d.site_xpos[sid])
        relative_r = wrist.T @ d.xmat[obj].reshape(3, 3)
        if ref_p is None:
            ref_p, ref_r, ref_q = relative_p.copy(), relative_r.copy(), d.qpos[qa].copy()
        contacts = []
        for ct in d.contact:
            bodies = [int(m.geom_bodyid[g]) for g in [ct.geom1, ct.geom2]]
            if obj in bodies and ct.dist <= 0:
                contacts.extend(m.body(b).name for b in bodies if m.body(b).name.startswith('right_hand'))
        ctrl = f['substep/ctrl'][k][aids]
        records.append({'row': k, 'time': float(d.time), 'finger_actual_q': d.qpos[qa].tolist(),
                        'finger_delta_from_alignment_start_rad': (d.qpos[qa] - ref_q).tolist(),
                        'finger_actual_v': d.qvel[va].tolist(), 'finger_actual_ctrl': ctrl.tolist(),
                        'finger_command_error_rad': (ctrl - d.qpos[qa]).tolist(),
                        'finger_actual_force_Nm': f['substep/actuator_force'][k][aids].tolist(),
                        'object_in_palm_m': relative_p.tolist(),
                        'relative_translation_drift_m': float(np.linalg.norm(relative_p - ref_p)),
                        'relative_rotation_drift_deg': float(np.degrees(np.linalg.norm(Rotation.from_matrix(relative_r @ ref_r.T).as_rotvec()))),
                        'object_tilt_deg': float(np.degrees(np.arccos(np.clip(d.xmat[obj].reshape(3, 3)[2, 2], -1, 1)))),
                        'contact_bodies': contacts})
    deltas = np.array([r['finger_delta_from_alignment_start_rad'] for r in records])
    summary = {'max_abs_encoder_change_per_joint_rad': np.max(abs(deltas), axis=0).tolist(),
               'max_relative_rotation_drift_deg': max(r['relative_rotation_drift_deg'] for r in records),
               'max_relative_translation_drift_m': max(r['relative_translation_drift_m'] for r in records)}
report = {'physics_steps': 0, 'policy_calls': 0, 'source': str(folder), 'start_row': start, 'loss_row': loss,
          'actuator_names': [m.actuator(a).name for a in aids], 'summary': summary, 'records': records,
          'interpretation_limit': 'Saved trajectory association only; encoder creep causality needs controlled dynamic comparison. C remains closed.',
          'production_accepted': False}
c.write(E / 'C3_GRASP_RELATIVE_MOTION_ANALYSIS.json', report)
finish(report)
