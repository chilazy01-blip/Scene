"""Bounded robot mounting checks include the high transfer and basket entry."""
import mujoco
import numpy as np
from copy import deepcopy
from sage.experiments.embodied_simdata_v0.controller import PandaController
from sage.experiments.embodied_scene_bridge.environment import owners, support_probe, vec
from sage.experiments.embodied_scene_bridge.contracts import require, write
from .contacts import ContactPolicy
from .cavity import bottom_probe, containment


def choose_mount(root, output, task, start_index=0, prior_candidates=None, task_aware_revision=False):
    model = mujoco.MjModel.from_xml_path(str(output/'model_unmounted.xml'))
    data = mujoco.MjData(model)
    ctrl = PandaController(model, data)
    ctrl.target_rot = np.asarray(task['target_rotation']) @ np.diag([1., -1., -1.])
    target_qi = model.jnt_qposadr[model.joint('task_target_free').id]
    finger_qi = [model.jnt_qposadr[model.joint(name).id] for name in ['finger_joint1', 'finger_joint2']]
    policy = ContactPolicy(model, owners(model), task)
    support = np.asarray(task['support_pose'])
    w, l, _ = task['support_dimensions_m']
    offsets = [(-w/2+.11, 0), (w/2-.11, 0), (-w/2+.11, -l/4), (w/2-.11, -l/4),
               (-w/4, -l/2+.11), (w/4, -l/2+.11), (-w/4, l/2-.11), (w/4, l/2-.11)]
    if task_aware_revision:
        local_start = (np.asarray(task['start'])-support[:3,3]) @ support[:3,:3]
        offsets += [(float(local_start[0])-.24,-l/2+.11),
                    (float(local_start[0])-.28,-l/2+.11)]
    base = model.body('base').id
    mount = model.geom('robot_mount').id
    start, goal = np.asarray(task['start']), np.asarray(task['goal'])
    height = task['grasp_height_offset_m']
    high = task['cavity']['highest_collision_z_world_m']+.03+task['target_dimensions_m'][2]/2
    waypoints = [('approach', start+[0,0,height+.12], start, .04, False),
                 ('grasp', start+[0,0,height], start, .04, True),
                 ('lift_clear', np.r_[start[:2], high+height], np.r_[start[:2], high], .019, True),
                 ('transfer_clear', np.r_[goal[:2], high+height], np.r_[goal[:2], high], .019, True),
                 ('entry_mid', goal+[0,0,height+.08], goal+[0,0,.08], .019, True),
                 ('place', goal+[0,0,height+.004], goal+[0,0,.004], .019, True),
                 ('release_open', goal+[0,0,height+.004], goal, .04, False),
                 ('retreat_clear', np.r_[goal[:2], high+height], goal, .04, False)]
    rows = deepcopy(prior_candidates or [])
    require(containment(task, goal, task['target_quat'])['inside'], 'nominal_goal_not_inside')
    for index, (x, y) in enumerate(offsets):
        if index < start_index:
            continue
        xyz = support[:3,3] + support[:3,:3] @ [x, y, 0.]
        xyz[2] = task['support_top_z_m']+.02
        direction = support[:3,3]-xyz
        yaw = np.arctan2(direction[1], direction[0])
        quat = [np.cos(yaw/2), 0, 0, np.sin(yaw/2)]
        model.body_pos[base] = xyz
        model.body_quat[base] = quat
        model.geom_pos[mount] = xyz-[0,0,.01]
        data.qpos[ctrl.qi] = ctrl.qhome
        data.qpos[finger_qi] = [.04, -.04]
        data.qpos[target_qi:target_qi+3] = start
        data.qpos[target_qi+3:target_qi+7] = task['target_quat']
        mujoco.mj_forward(model, data)
        row = dict(index=index, position_m=xyz.tolist(), quaternion_wxyz=quat,
                   home_collisions=policy.violations(data, .001, allow_fingers=False))
        try:
            row['mount_support'] = support_probe(model, data, task, xyz, half_xy=[.09, .09])
            row['start_support'] = support_probe(model, data, task, start)
            row['bottom_probe'] = bottom_probe(model, data, task)
            require(not row['home_collisions'], 'robot_home_collision')
            q = ctrl.qhome.copy()
            checks = []
            for name, position, object_position, grip, fingers in waypoints:
                q, error = ctrl.ik(position, q)
                data.qpos[ctrl.qi] = q
                data.qpos[finger_qi] = [grip, -grip]
                data.qpos[target_qi:target_qi+3] = object_position
                mujoco.mj_forward(model, data)
                bad = policy.violations(data, .001, allow_fingers=fingers)
                checks.append(dict(phase=name, position_m=position.tolist(), q=q.tolist(),
                                   residual=error, forbidden_contacts=bad))
            row['endpoint_ik'] = checks
            require(all(x['residual'] < .004 and not x['forbidden_contacts'] for x in checks), 'container_endpoint_IK_or_collision_unresolved')
            jitter_checks = []
            for dx, dy in [(-.02,-.02),(-.02,.02),(.02,-.02),(.02,.02)]:
                shifted = start + [dx,dy,0]
                q = ctrl.qhome.copy()
                for phase, position, object_position in [
                    ('approach', shifted+[0,0,height+.12], shifted),
                    ('grasp', shifted+[0,0,height], shifted),
                    ('lift_clear', np.r_[shifted[:2],high+height], np.r_[shifted[:2],high])]:
                    q, error = ctrl.ik(position,q)
                    data.qpos[ctrl.qi] = q
                    data.qpos[finger_qi] = [.04,-.04]
                    data.qpos[target_qi:target_qi+3] = object_position
                    mujoco.mj_forward(model,data)
                    bad = policy.violations(data,.001,allow_fingers=phase!='approach')
                    jitter_checks.append(dict(phase=phase,jitter_xy=[dx,dy],residual=error,forbidden_contacts=bad))
            row['jitter_corner_ik'] = jitter_checks
            require(all(x['residual'] < .004 and not x['forbidden_contacts'] for x in jitter_checks), 'initialization_corner_IK_or_collision_unresolved')
            row['status'] = 'endpoint_checks_passed_path_and_execution_unknown'
            rows.append(row)
            root.find("worldbody/body[@name='base']").set('pos', vec(xyz))
            root.find("worldbody/body[@name='base']").set('quat', vec(quat))
            root.find("worldbody/geom[@name='robot_mount']").set('pos', vec(xyz-[0,0,.01]))
            return dict(selected=row, candidates=rows, budget=len(offsets), scene_edits=0,
                        interpretation='Source support, basket entry and endpoint checks; no full task yet')
        except ValueError as exc:
            row.update(status='unknown_feasibility', reason=str(exc))
            rows.append(row)
    write(output/'mount_candidates.json', dict(selected=None, candidates=rows, budget=len(offsets)))
    raise ValueError('mount_budget_unsolved_not_proof_of_infeasibility')
