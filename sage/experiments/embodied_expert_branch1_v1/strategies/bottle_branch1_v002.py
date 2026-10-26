"""Branch one v002: separate release entry readiness from ongoing support.

UNTESTED design candidate, derived in-file from V010; no old strategy imports.
Initial mesh/IK approach and V010 probe/lift/hover acquisition are retained.
The successful-hover reference is an immutable tuple, not a running maximum.
All later feedback proposals share a signed [floor, floor + .060 rad] envelope,
intersected with the .65 native bounds and .006 rad per policy-tick slew.
Only reference arrays and task bookkeeping are written. Physics belongs to the
parent executor; private kinematic queries in the retained planner are allowed.
V001 entry thresholds/dwell and release opening law are unchanged. An entry
certificate authorizes release only while fresh measured support/geometry hold;
entry quietness remains diagnostic during opening, not proof of support loss.
"""
import numpy as np
from scipy.spatial.transform import Rotation
from sage.experiments.embodied_native_sonic_body_grasp_v1.task_stand import Task as BaseTask
from sage.experiments.embodied_native_sonic_grasp_feedback_v1.continuous_lift import make_path
from sage.experiments.embodied_native_object_transport_v1.task_v3 import smooth
from sage.experiments.embodied_sonic_command_integration_v1.native_envelope import allocate
from sage.experiments.embodied_sonic_command_integration_v1.task_envelope import fast_update
from sage.experiments.embodied_native_sonic_grasp_feedback_v1.relative_grip_wrench import wrench
from sage.experiments.embodied_native_walk_motion_v2.engine import hand_ids
from sage.experiments.embodied_carry_v1.grasp import RIGHT_CLOSED


def upright(R, axis_index=2):
    axis = R[:, axis_index].copy()
    if axis_index == 0 and axis[2] < 0:
        axis = -axis
    cross = np.cross(axis, [0., 0., 1.])
    angle = np.arctan2(np.linalg.norm(cross), axis[2])
    if np.linalg.norm(cross) < 1e-9:
        return R.copy()
    return Rotation.from_rotvec(cross / np.linalg.norm(cross) * angle).as_matrix() @ R


class Task(BaseTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.orientation_axis_id = 0 if self.case['object_id'] == 'book' else 2
        self.shape_ready = False
        self.ready_fine_align_started = False
        self.acquired_probe_reference_floor = None
        self.shape_touch = None
        self.shape_goal = None
        self.shape_offset_object = None
        self.shape_orientation_object = None
        if (self.case['case_id'] not in ('S02_bottle', 'S03_bottle') or
                self.case['object_id'] != 'bottle' or
                abs(float(self.case['loaded_native_reference_ratio']) - .65) > 1e-12 or
                tuple(self.case['orientation_axis']) != (0, 0, 1)):
            raise ValueError('branch1_v002 requires the admitted S02/S03 bottle cases')
        self.hover_preload_reference = None
        self.hover_relative_rotation = None
        self.airborne_clearance_confirmed = False
        self.preload_table_handoff = False
        self.target_support_count = 0
        self.target_support_tick = None
        self.target_support_evidence = None
        self.release_entry_certificate = None
        self.release_support_observation_consecutive = False
        self.hand_reference_tick = None
        self.hand_reference_tick_origin = None
        self.contract_role_state = None

    def change(self, stage, tick, data, metrics):
        # A phase request cannot certify support or create a successful grasp.
        if stage == 'release':
            # Consume only this tick's place/lower observation and its dwell.
            # Changing phase cannot issue or refresh measured evidence.
            if not (self.stage == 'place' and self.preload_table_handoff and
                    self.target_support_tick == tick and
                    self.target_support_count >= 21 and
                    self.target_support_evidence is not None and
                    self.target_support_evidence['entry_ready']):
                self.failure = 'branch1_release_without_target_handoff'
                self.events.append(dict(kind='branch1_release_entry_rejected', tick=tick,
                    observation_tick=self.target_support_tick,
                    consecutive_observations=self.target_support_count,
                    evidence=self.target_support_evidence, action='hold_reference_and_stop'))
                return
            self.release_entry_certificate = dict(
                first_observation_tick=tick-self.target_support_count+1,
                last_observation_tick=tick,
                consecutive_observations=self.target_support_count,
                evidence=self.target_support_evidence)
            self.events.append(dict(kind='branch1_release_entry_certificate', tick=tick,
                certificate=self.release_entry_certificate,
                validity='entry dwell plus each consecutive measured release support observation',
                no_physics_substep_continuity_claim=True))
        super().change(stage, tick, data, metrics)
        if stage == 'load_probe' and self.finger_reference is not None:
            # Preserve V010's acquisition-only running floor through hover.
            self.acquired_probe_reference_floor = self.finger_reference.copy()
            self.events.append(dict(kind='expert_acquired_neck_preload_latched', tick=tick,
                reference_rad=self.finger_reference.tolist(), forces=dict(metrics['forces']),
                original_acceptance_anchor_unchanged=True))
        if stage == 'tuck' and self.hover_preload_reference is None:
            clear = (self.probe_passed and self.grasp_test_passed and
                     not metrics['desk_supported'] and
                     metrics['object_bottom_m'] > self.case['support_top_m'] + .025)
            if not clear or self.finger_reference is None:
                self.failure = 'branch1_missing_qualified_hover_preload'
                return
            self.hover_preload_reference = tuple(float(v) for v in self.finger_reference)
            pid = self.model.body('payload').id
            W = data.xmat[self.wrist].reshape(3, 3)
            C = data.xmat[pid].reshape(3, 3)
            self.hover_relative_rotation = tuple(map(tuple, W.T @ C))
            self.airborne_clearance_confirmed = True
            self.events.append(dict(kind='branch1_hover_preload_frozen', tick=tick,
                finger_names=list(hand_ids(self.model)['names']),
                reference_rad=list(self.hover_preload_reference),
                reversible_extra_closure_rad=.060, floor_will_not_ratchet=True,
                original_acceptance_anchor_unchanged=True))
        if stage in ('release', 'retract', 'settle', 'done'):
            self.acquired_probe_reference_floor = None
            # Keep the frozen tuple as diagnostic evidence; it no longer guards
            # intentional supported release or the subsequent open-hand phases.

    def begin_hand_reference_tick(self, tick):
        if self.hand_reference_tick != tick:
            h = hand_ids(self.model)
            self.hand_reference_tick = tick
            self.hand_reference_tick_origin = (
                np.zeros(len(h['names'])) if self.finger_reference is None
                else self.finger_reference.copy())

    def project_hand_reference(self, tick):
        # One common origin limits the sum of callbacks, not just each callback.
        self.begin_hand_reference_tick(tick)
        if self.finger_reference is None:
            return
        from sage.experiments.embodied_carry_v1.grasp import group
        h = hand_ids(self.model)
        proposed = self.finger_reference.copy()
        old = self.hand_reference_tick_origin
        guarded = (self.hover_preload_reference is not None and
                   self.stage in ('tuck', 'carry', 'target_stop', 'place'))
        for i, name in enumerate(h['names']):
            if name in RIGHT_CLOSED:
                end = RIGHT_CLOSED[name] * .65
                sign = float(np.sign(end))
                progress = sign * proposed[i]
                low, high = 0., abs(end)
                if guarded:
                    low = sign * self.hover_preload_reference[i]
                    high = min(high, low + .060)
                progress = np.clip(progress, low, high)
                target = sign * progress
            else:
                target = proposed[i]
            self.finger_reference[i] = old[i] + np.clip(target - old[i], -.006, .006)
        self.group_values = {
            g: max([abs(self.finger_reference[i] / RIGHT_CLOSED[n])
                    for i, n in enumerate(h['names'])
                    if n in RIGHT_CLOSED and group(n) == g], default=0.)
            for g in ('thumb', 'index', 'middle')}
        self.closure = max(self.group_values.values())
        if guarded and tick % 5 == 0 and not np.array_equal(proposed, self.finger_reference):
            self.events.append(dict(kind='branch1_preload_reference_projection', tick=tick,
                stage=self.stage, proposed_rad=proposed.tolist(),
                reference_rad=self.finger_reference.tolist(),
                fixed_floor_rad=list(self.hover_preload_reference),
                maximum_extra_closure_rad=.060, maximum_tick_slew_rad=.006,
                reference_only=True))

    def target_support_sample(self, tick, data, m):
        # Desk support during close/probe/lift never counts as target handoff.
        if (self.stage not in ('place', 'release') or
                getattr(self, 'place_step', None) != 'lower' or
                not self.airborne_clearance_confirmed):
            return False, dict(reason='phase_or_qualified_liftoff_missing',
                entry_ready=False, persistent_support=False)
        pid = self.model.body('payload').id
        C = data.xmat[pid].reshape(3, 3)
        cosine = float((C @ np.asarray(self.case['orientation_axis']))[2])
        weight = float(self.model.body_mass[pid] * abs(self.model.opt.gravity[2]))
        # Match the measured object/table pair, not hand/table incidental contact.
        target_normal = sum(float(row['normal_force_n']) for row in m['contacts']
            if (any(p['name'] == 'payload_surface' for p in row['pair']) and
                any(p['body'] == 'generated_desk' for p in row['pair'])))
        fid = self.mujoco.mj_name2id(self.model, self.mujoco.mjtObj.mjOBJ_FLEX,
                                   'payload_surface')
        start, count = int(self.model.flex_vertadr[fid]), int(self.model.flex_vertnum[fid])
        vertices = np.asarray(data.flexvert_xpos[start:start + count])
        bottom = float(vertices[:, 2].min())
        base = vertices[vertices[:, 2] <= bottom + .003]
        desk = self.model.body('generated_desk').id
        table = np.asarray(data.flexvert_xpos)[np.asarray(self.model.flex_vertbodyid) == desk]
        top_z = float(self.case['support_top_m'])
        top = table[table[:, 2] >= top_z - .003]
        if len(top) == 0 or len(base) == 0:
            return False, dict(reason='support_geometry_missing',
                entry_ready=False, persistent_support=False,
                target_contact_normal_n=target_normal, weight_n=weight,
                desk_supported=bool(m['desk_supported']),
                object_axis_cosine=cosine, object_bottom_above_table_m=bottom-top_z)
        inside = bool(np.all(base[:, :2] >= top[:, :2].min(0) + .005) and
                      np.all(base[:, :2] <= top[:, :2].max(0) - .005))
        target_error = float(np.linalg.norm(np.asarray(m['object_m'])[:2] -
                                           np.asarray(self.case['target_object_xyz_m'])[:2]))
        planned_error = float(np.linalg.norm(np.asarray(m['object_m'])[:2] -
                                            self.place_goal[:2]))
        velocity = np.zeros(6)
        self.mujoco.mj_objectVelocity(self.model, data, self.mujoco.mjtObj.mjOBJ_BODY,
                                     pid, velocity, 0)
        angular_speed = float(np.linalg.norm(velocity[:3]))
        object_speed = float(np.linalg.norm(m['object_velocity_m_s']))
        root_speed = float(np.linalg.norm(data.qvel[:3]))
        persistent_predicates = dict(
            desk_supported=bool(m['desk_supported']),
            target_load_bearing=bool(target_normal >= .8 * weight),
            base_inside_target_table=inside,
            bottom_height_in_band=bool(-.003 <= bottom-top_z <= .006),
            original_target_in_range=bool(target_error < .10),
            planned_target_in_range=bool(planned_error < .10),
            object_upright=bool(cosine > .985))
        entry_motion_predicates = dict(
            angular_quiet=bool(angular_speed < .25),
            object_linear_quiet=bool(object_speed < .04),
            root_linear_quiet=bool(root_speed < .06),
            wrist_reference_reached=bool(self.reached(tick, data)))
        persistent_support = all(persistent_predicates.values())
        ready = bool(persistent_support and all(entry_motion_predicates.values()))
        return ready, dict(target_contact_normal_n=target_normal, weight_n=weight,
            object_axis_cosine=cosine, object_bottom_above_table_m=bottom - top_z,
            base_inside_target_table=inside, target_error_xy_m=target_error,
            planned_error_xy_m=planned_error, desk_supported=bool(m['desk_supported']),
            object_angular_speed_rad_s=angular_speed, object_speed_m_s=object_speed,
            root_speed_m_s=root_speed, persistent_predicates=persistent_predicates,
            entry_motion_predicates=entry_motion_predicates,
            failed_persistent_predicates=[k for k, v in persistent_predicates.items() if not v],
            failed_entry_motion_predicates=[k for k, v in entry_motion_predicates.items() if not v],
            persistent_support=bool(persistent_support), entry_ready=ready, ready=ready)

    def observe_target_handoff(self, tick, data, m):
        if self.target_support_tick == tick:
            return
        ready, evidence = self.target_support_sample(tick, data, m)
        previous = self.preload_table_handoff
        consecutive = self.target_support_tick == tick - 1
        self.target_support_tick = tick
        if self.stage == 'release':
            # Preserve the consumed entry dwell; do not requalify quietness or
            # treat a phase change as a new observation. A missed policy sample
            # expires authorization even if the current sample has support.
            self.release_support_observation_consecutive = consecutive
            self.preload_table_handoff = bool(previous and
                self.release_entry_certificate is not None and consecutive and
                evidence['persistent_support'])
        else:
            self.target_support_count = (self.target_support_count + 1
                                         if ready and consecutive else int(ready))
            # 21 distinct policy observations span 20 intervals (.400 seconds).
            self.preload_table_handoff = self.target_support_count >= 21
        self.target_support_evidence = evidence
        if self.stage == 'release' or (self.stage == 'place' and
                                       getattr(self, 'place_step', None) == 'lower'):
            self.events.append(dict(kind='branch1_target_support_predicates', tick=tick,
                stage=self.stage, evidence=evidence,
                entry_consecutive_observations=self.target_support_count,
                consecutive_observation=consecutive,
                release_authorized=self.preload_table_handoff,
                entry_motion_is_diagnostic_only=self.stage == 'release',
                no_physics_substep_continuity_claim=True))
        if previous != self.preload_table_handoff:
            self.events.append(dict(kind='branch1_target_handoff_contract', tick=tick,
                stage=self.stage, certified=self.preload_table_handoff,
                consecutive_observations=self.target_support_count,
                evidence=evidence, no_physics_substep_continuity_claim=True))

    def observe_loaded_contract(self, tick, data, m):
        if self.stage not in ('load_probe', 'lift', 'loaded_hover', 'tuck',
                              'carry', 'target_stop', 'place'):
            return
        missing = tuple(g for g in ('thumb', 'index', 'middle') if m['forces'][g] <= .01)
        state = (self.stage, missing, bool(m['desk_supported']))
        if tick % 5 == 0 or state != self.contract_role_state:
            C = np.asarray(m['object_rotation']).reshape(3, 3)
            relative_error = None
            if self.hover_relative_rotation is not None:
                W = data.xmat[self.wrist].reshape(3, 3)
                relative_error = float(np.linalg.norm(Rotation.from_matrix(
                    np.asarray(self.hover_relative_rotation).T @ W.T @ C).as_rotvec()))
            self.events.append(dict(kind='branch1_loaded_phase_observation', tick=tick,
                stage=self.stage, missing_roles=list(missing), forces=dict(m['forces']),
                hand_contact=bool(m['hand_contact']), desk_supported=bool(m['desk_supported']),
                object_axis_cosine=float((C @ np.asarray(self.case['orientation_axis']))[2]),
                robot_root_up_cosine=float(m['up']),
                object_in_wrist_m=list(m['object_local_m']),
                relative_rotation_drift_rad=relative_error,
                target_handoff_certified=self.preload_table_handoff,
                diagnostic_only=True, unique_cause_claim=False))
        self.contract_role_state = state

    def ready_arm(self, tick, data):
        # Tall-object staging uses this shape's own pinch frame and clear top.
        from sage.experiments.embodied_transport_native_v1.contacts import contact_pair
        from sage.experiments.embodied_transport_hybrid_v1.control import ARM
        from sage.experiments.embodied_data_stability_v1 import sonic_native_dynamic_shadow as native
        if not self.shape_ready:
            self.shape_reference(tick, data)
        if self.failure:
            return
        goal = self.shape_goal + np.array([0., 0., .10])
        R = self.grasp_R.copy()
        fit = self.ik.solve(data.qpos, goal, R, max_evaluations=150)
        if fit['position_error_m'] > .01 or fit['orientation_error_rad'] > .05:
            self.events.append(dict(kind='expert_shape_ready_IK_rejected', tick=tick, goal_m=goal.tolist(), rotation=R.tolist(), private_IK=fit))
            self.failure = 'shape_ready_reference_unreachable'
            return
        origin = data.qpos[self.armq].copy()
        target = np.asarray(fit['angles_rad'])
        folded = np.array([-1.2, -.2, 0., 1.6, 0., 0., 0.])
        private = self.mujoco.MjData(self.model)
        checked = []
        selected = None
        for route in ([origin, target], [origin, folded, target]):
            bad = []
            samples = 0
            for start, end in zip(route[:-1], route[1:]):
                count = max(2, int(np.ceil(np.max(np.abs(end-start))/.025)))
                for fraction in np.linspace(0., 1., count+1):
                    private.qpos[:] = data.qpos
                    private.qpos[self.armq] = start+(end-start)*fraction
                    self.mujoco.mj_forward(self.model, private)
                    samples += 1
                    for contact in private.contact:
                        pair = contact_pair(self.model, contact)
                        names = [v['name'] for v in pair]
                        moving = any(v['body'].startswith(('right_shoulder', 'right_elbow', 'right_wrist', 'right_hand')) for v in pair)
                        obstacle = ('payload_surface' in names or 'native_floor' in names or any(n.startswith('scene_collision_') for n in names))
                        if moving and obstacle and contact.dist < .001:
                            bad.append(dict(pair=pair, distance_m=float(contact.dist), fraction=float(fraction)))
                            break
                    if bad:
                        break
                if bad:
                    break
            checked.append(dict(samples=samples, bad=bad[:5], knot_count=len(route)))
            if not bad:
                selected = route
                break
        self.events.append(dict(kind='expert_shape_ready_geometry_route', tick=tick, goal_m=goal.tolist(), rotation=R.tolist(), checks=checked, passed=selected is not None, new_physics_steps=0, physical_model_unchanged=True))
        if selected is None:
            # Bounded geometric planning only; actual dynamics remain broker-owned.
            rng = np.random.default_rng(20261026)
            cache = {}
            checks = [0]
            rejected = []
            desk = self.model.body('generated_desk').id
            dv = np.asarray(data.flexvert_xpos)[np.asarray(self.model.flex_vertbodyid)==desk]
            top = dv[dv[:,2]>=self.case['support_top_m']-.003]
            lowxy,highxy = top[:,:2].min(0),top[:,:2].max(0)
            moving_meshes=[]
            for gid in range(self.model.ngeom):
                body=self.model.body(int(self.model.geom_bodyid[gid])).name
                if not body.startswith(('right_shoulder','right_elbow','right_wrist','right_hand')) or not (self.model.geom_contype[gid] or self.model.geom_conaffinity[gid]):continue
                if int(self.model.geom_type[gid])!=int(self.mujoco.mjtGeom.mjGEOM_MESH):continue
                mid=int(self.model.geom_dataid[gid]);adr=int(self.model.mesh_vertadr[mid]);count=int(self.model.mesh_vertnum[mid])
                cloud=np.asarray(self.model.mesh_vert[adr:adr+count]);cloud=cloud[np.linspace(0,count-1,min(count,90)).astype(int)]
                moving_meshes.append((gid,cloud))
            def valid(q):
                key=tuple(np.round(q,10))
                if key in cache:return cache[key]
                if checks[0]>=4000:return False
                checks[0]+=1
                private.qpos[:]=data.qpos
                private.qpos[self.armq]=q
                self.mujoco.mj_forward(self.model,private)
                bad=[]
                for contact in private.contact:
                    pair=contact_pair(self.model,contact)
                    moving=any(v['body'].startswith(('right_shoulder','right_elbow','right_wrist','right_hand')) for v in pair)
                    obstacle=any(v['name']=='payload_surface' or v['name']=='native_floor' or v['name'].startswith('scene_collision_') for v in pair)
                    if moving and obstacle and contact.dist<.001:
                        bad.append(dict(pair=pair,distance_m=float(contact.dist)));break
                if not bad:
                    for gid,cloud in moving_meshes:
                        world=cloud@private.geom_xmat[gid].reshape(3,3).T+private.geom_xpos[gid]
                        near=np.all(world[:,:2]>=lowxy-.04,axis=1)&np.all(world[:,:2]<=highxy+.04,axis=1)&(world[:,2]<self.case['support_top_m']+.04)&(world[:,2]>self.case['support_top_m']-.05)
                        if np.any(near):bad.append(dict(reference_table_margin_m=.04,body=self.model.body(int(self.model.geom_bodyid[gid])).name));break
                ok=not bad;cache[key]=ok
                if bad and len(rejected)<24:rejected.append(dict(angles_rad=q.tolist(),bad=bad))
                return ok
            def edge(a,b,resolution=.05):
                count=max(1,int(np.ceil(np.max(np.abs(b-a))/resolution)))
                return all(valid(a+(b-a)*(i/count)) for i in range(1,count+1))
            def extend(tree,target):
                nodes,parents=tree;i=int(np.argmin([np.linalg.norm(v-target) for v in nodes]));delta=target-nodes[i]
                candidate=nodes[i]+delta*min(1.,.35/max(np.max(np.abs(delta)),1e-12))
                if not edge(nodes[i],candidate):return None,False
                nodes.append(candidate);parents.append(i);return len(nodes)-1,bool(np.max(np.abs(candidate-target))<1e-9)
            def backtrack(tree,i):
                path=[]
                while i>=0:path.append(tree[0][i]);i=tree[1][i]
                return path[::-1]
            path=None;iterations=0
            start_ok,goal_ok=valid(origin),valid(target)
            if start_ok and goal_ok:
                trees=[([origin],[-1]),([target],[-1])]
                for iterations in range(800):
                    if checks[0]>=3100:break
                    ia=iterations%2;ib=1-ia
                    if rng.random()<.25:sample=trees[ib][0][-1]
                    elif rng.random()<.85:sample=np.clip((origin+target)/2+rng.normal(size=7)*[1.,.8,1.,.9,1.,.8,1.],self.ik.lower,self.ik.upper)
                    else:sample=rng.uniform(self.ik.lower,self.ik.upper)
                    index,_=extend(trees[ia],sample)
                    if index is None:continue
                    endpoint=trees[ia][0][index]
                    for attempt in range(30):
                        other,reached=extend(trees[ib],endpoint)
                        if other is None:break
                        if reached:
                            left,right=backtrack(trees[ia],index),backtrack(trees[ib],other)
                            path=left+right[-2::-1]
                            if ia==1:path=path[::-1]
                            break
                    if path is not None:break
            if path is not None:
                short=[path[0]];cursor=0
                while cursor<len(path)-1:
                    index=cursor+1
                    for j in range(len(path)-1,cursor,-1):
                        if checks[0]>=3500:break
                        if edge(path[cursor],path[j]):index=j;break
                    short.append(path[index]);cursor=index
                path=short
                if not all(edge(a,b,.025) for a,b in zip(path[:-1],path[1:])):path=None
            self.events.append(dict(kind='expert_neck_ready_reference_RRT',tick=tick,passed=path is not None,collision_checks=checks[0],maximum_checks=4000,start_valid=start_ok,goal_valid=goal_ok,iterations=iterations,rejection_examples=rejected,knots_rad=None if path is None else [v.tolist() for v in path],new_physics_steps=0,reference_only=True,physical_model_unchanged=True))
            selected=path
        if selected is None:
            self.failure = 'shape_ready_reference_route_blocked'
            return
        durations = [max(20, int(np.ceil(1.875*np.max(np.abs(b-a))/(.5*.02)))) for a,b in zip(selected[:-1], selected[1:])]
        if sum(durations) > 600:
            self.failure = 'bounded_reference_route_duration'
            return
        self.path = None
        self.joint_path = dict(tick=tick, duration=sum(durations), target=target, goal_m=goal.copy(), R=R.copy())
        cursor = tick
        for a,b,count in zip(selected[:-1], selected[1:], durations):
            fraction = smooth(np.arange(count)/count)[:,None]
            self.q[cursor:cursor+count,ARM+7] = (1-fraction)*a+fraction*b
            cursor += count
        self.q[cursor:,ARM+7] = selected[-1]
        self.v = native._reference_velocities(self.q)
        self.events.append(dict(kind='expert_shape_ready_joint_reference', tick=tick, knots_rad=[v.tolist() for v in selected], durations=durations, all29body_sonic=True))

    def shape_reference(self, tick, data):
        # All state assignments below are to a private kinematic query, never data.
        from scipy.optimize import least_squares,linprog
        from sage.experiments.embodied_carry_v1.grasp import group
        mj, model = self.mujoco, self.model
        private = mj.MjData(model)
        private.qpos[:] = data.qpos
        h = hand_ids(model)
        ix = np.array([i for i, n in enumerate(h['names']) if n in RIGHT_CLOSED])
        fq = h['qpos'][ix]
        ends = np.array([RIGHT_CLOSED[h['names'][i]] * .65 for i in ix])
        seed = ends * (.3 / .65)
        private.qpos[fq] = seed
        mj.mj_kinematics(model, private)
        pid = model.body('payload').id
        C = data.xmat[pid].reshape(3, 3).copy()
        O = data.xpos[pid].copy()
        fid = mj.mj_name2id(model, mj.mjtObj.mjOBJ_FLEX, 'payload_surface')
        a, n = int(model.flex_vertadr[fid]), int(model.flex_vertnum[fid])
        vertices = np.asarray(model.flex_vert[a:a+n]).copy()
        lo, hi = vertices.min(0), vertices.max(0)
        center = (lo + hi) / 2
        half = (hi - lo) / 2
        distal = ('right_hand_thumb_2_link', 'right_hand_index_1_link', 'right_hand_middle_1_link')
        geoms = []
        for gid in range(model.ngeom):
            body = model.body(int(model.geom_bodyid[gid])).name
            if (body.startswith('right_hand_') or body == 'right_wrist_yaw_link') and (model.geom_contype[gid] or model.geom_conaffinity[gid]):
                mid = int(model.geom_dataid[gid])
                if int(model.geom_type[gid]) != int(mj.mjtGeom.mjGEOM_MESH):
                    continue
                cloud = np.asarray(model.mesh_vert[int(model.mesh_vertadr[mid]):int(model.mesh_vertadr[mid])+int(model.mesh_vertnum[mid])]).copy()
                cloud = cloud[np.linspace(0, len(cloud)-1, min(180, len(cloud))).astype(int)]
                geoms.append((gid, body, cloud))

        def clouds(angles):
            private.qpos[fq] = angles
            mj.mj_kinematics(model, private)
            W = private.xmat[self.wrist].reshape(3, 3)
            return [(body, (v @ private.geom_xmat[g].reshape(3, 3).T + private.geom_xpos[g] - private.xpos[self.wrist]) @ W) for g, body, v in geoms]

        initial_clouds = clouds(seed)
        tips = [next(v for b, v in initial_clouds if b == name) for name in distal]
        centers = np.array([v.mean(0) for v in tips])
        axis = np.linalg.svd(tips[1]-centers[1], full_matrices=False)[2][0]
        if axis @ centers[1] < 0:
            axis = -axis
        across = (centers[1]+centers[2])/2-centers[0]
        across -= axis * (axis @ across)
        across /= np.linalg.norm(across)
        G = np.diag([1., -1., -1.]) @ np.column_stack([across, np.cross(axis, across), axis]).T
        # Bottle approach uses its vertical axis and actual pelvis heading.
        # The book branch below defines its own cover/edge pinch frame.
        if self.case['object_id'] == 'bottle':
            heading = data.xmat[self.model.body('pelvis').id].reshape(3,3)[:,0].copy()
            heading[2] = 0.
            heading /= np.linalg.norm(heading)
            up_axis = C[:,2].copy()
            heading -= up_axis*(heading@up_axis)
            heading /= np.linalg.norm(heading)
            approach_frame = np.column_stack([heading,np.cross(up_axis,heading),up_axis])
            G = C.T@approach_frame@G
        tip_goal = center.copy()
        if self.case['object_id'] == 'book':
            tip_goal[2] = hi[2] - .012
        else:
            tip_goal[2] = hi[2] - .0125
        p0 = tip_goal - (centers @ G.T).mean(0)
        radius = min(half[:2])
        profile_edges = np.linspace(lo[2],hi[2],51)
        profile_z = (profile_edges[:-1]+profile_edges[1:])/2
        profile_radius = np.array([max(np.linalg.norm(vertices[(vertices[:,2]>=a)&(vertices[:,2]<=b),:2]-center[:2],axis=1),default=np.nan) for a,b in zip(profile_edges[:-1],profile_edges[1:])])
        valid_profile = np.isfinite(profile_radius)
        profile_radius = np.interp(profile_z,profile_z[valid_profile],profile_radius[valid_profile])

        collision_radius = float(model.flex_radius[fid])

        def sdf(points):
            if self.case['object_id'] == 'book':
                return np.max(np.abs(points-center)-half, axis=1)-collision_radius
            return np.maximum.reduce([np.linalg.norm(points[:, :2]-center[:2], axis=1)-np.interp(points[:,2],profile_z,profile_radius),
                                      lo[2]-points[:, 2], points[:, 2]-hi[2]])-collision_radius

        initial = np.r_[seed, p0, np.zeros(3)]
        flo = np.minimum(0, ends)+1e-6
        fhi = np.maximum(0, ends)-1e-6
        lower = np.r_[flo, p0-.045, np.full(3, -.35)]
        upper = np.r_[fhi, p0+.045, np.full(3, .35)]
        initial = np.clip(initial, lower+1e-7, upper-1e-7)

        def residual(x):
            Q = Rotation.from_rotvec(x[10:]).as_matrix() @ G
            points = [(b, v @ Q.T+x[7:10]) for b, v in clouds(x[:7])]
            gaps = [float(sdf(next(v for b, v in points if b == name)).min()) for name in distal]
            err = [(v+.00015)/.0015 for v in gaps]
            for name in distal:
                cloud = next(v for body,v in points if body==name)
                contact_z = cloud[int(np.argmin(sdf(cloud))),2]
                err.extend([max(.103-contact_z,0.)/.004,max(contact_z-.122,0.)/.004])
            for body, v in points:
                # Separate the reference geometric target from a physical claim.
                err.append(max(-.0006-float(sdf(v).min()), 0.)/.001)
                world = v @ C.T+O
                err.append(max(self.case['support_top_m']+.001-float(world[:, 2].min()), 0.)/.002)
            err.extend(.12*(x[7:10]-p0)/.025)
            err.extend(.08*x[10:]/.2)
            err.extend(.025*(x[:7]-seed)/.3)
            return np.asarray(err)

        fit = least_squares(residual, initial, bounds=(lower, upper), max_nfev=90,
                            diff_step=1e-4, ftol=1e-6, xtol=1e-7, gtol=1e-6)
        x = fit.x
        Q = Rotation.from_rotvec(x[10:]).as_matrix() @ G
        fitted = [(b, v @ Q.T+x[7:10]) for b, v in clouds(x[:7])]
        gaps = {name:float(sdf(next(v for b, v in fitted if b == name)).min()) for name in distal}
        depth = max(0., -min(float(sdf(v).min()) for b, v in fitted))
        clearance = min(float((v @ C.T+O)[:, 2].min())-self.case['support_top_m'] for b, v in fitted)
        goal = O+C@x[7:10]
        orientation = C@Q
        ik = self.ik.solve(data.qpos, goal, orientation, max_evaluations=150)
        # Refine with actual arm and finger FK so a virtual hand fit cannot hide
        # a large reach error. Only this private reference data is assigned.
        seed_arm = np.asarray(ik['angles_rad'])
        fk_initial = np.r_[seed_arm,x[:7]]
        fk_low = np.r_[self.ik.lower+1e-6,flo]
        fk_high = np.r_[self.ik.upper-1e-6,fhi]
        fk_initial = np.clip(fk_initial,fk_low+1e-7,fk_high-1e-7)
        wanted_goal,wanted_R = goal.copy(),orientation.copy()

        def fk_points(values):
            private.qpos[self.armq] = values[:7]
            local_clouds = clouds(values[7:])
            W = private.xmat[self.wrist].reshape(3,3)
            P = private.xpos[self.wrist]
            return [(body,(v@W.T+P-O)@C) for body,v in local_clouds]

        def fk_residual(values):
            points = fk_points(values)
            err = [(float(sdf(next(v for b,v in points if b==name)).min())+.0002)/.0015 for name in distal]
            for name in distal:
                cloud = next(v for body,v in points if body==name)
                contact_z = cloud[int(np.argmin(sdf(cloud))),2]
                err.extend([max(.103-contact_z,0.)/.004,max(contact_z-.122,0.)/.004])
            for body,v in points:
                err.append(max(-.0006-float(sdf(v).min()),0.)/.001)
                err.append(max(self.case['support_top_m']+.001-float((v@C.T+O)[:,2].min()),0.)/.002)
            err.extend(.08*(private.xpos[self.wrist]-wanted_goal)/.03)
            err.extend(.04*Rotation.from_matrix(wanted_R.T@private.xmat[self.wrist].reshape(3,3)).as_rotvec()/.3)
            err.extend(.015*(values[7:]-x[:7])/.3)
            err.extend(.008*(values[:7]-seed_arm)/.4)
            return np.asarray(err)

        fk_fit = least_squares(fk_residual,fk_initial,bounds=(fk_low,fk_high),max_nfev=120,
                               diff_step=1e-4,ftol=1e-6,xtol=1e-7,gtol=1e-6)
        fitted = fk_points(fk_fit.x)
        gaps = {name:float(sdf(next(v for b,v in fitted if b==name)).min()) for name in distal}
        depth = max(0.,-min(float(sdf(v).min()) for b,v in fitted))
        clearance = min(float((v@C.T+O)[:,2].min())-self.case['support_top_m'] for b,v in fitted)
        goal = private.xpos[self.wrist].copy()
        orientation = private.xmat[self.wrist].reshape(3,3).copy()
        Q = C.T@orientation
        x[:7] = fk_fit.x[7:]
        x[7:10] = C.T@(goal-O)
        from sage.experiments.embodied_native_sonic_loaded_grasp_v1.quality import contacts,required_preload
        self.mujoco.mj_forward(model,private)
        native_rows,native_info = contacts(self.mujoco,model,private,True)
        native_preload = required_preload(native_rows,native_info['weight_n'],np.asarray(native_info['com_m']))
        from sage.experiments.embodied_transport_native_v1.contacts import contact_pair
        native_scene_bad = []
        for contact in private.contact:
            pair = contact_pair(model,contact)
            moving = any(v['body'].startswith(('right_shoulder','right_elbow','right_wrist','right_hand')) for v in pair)
            scene = any(v['name'].startswith('scene_collision_') or v['name']=='native_floor' for v in pair)
            if moving and scene and contact.dist < 0.:
                native_scene_bad.append(dict(pair=pair,distance_m=float(contact.dist)))
        native_depth = max([-row['distance_m'] for row in native_rows],default=0.)
        seed_qpos = data.qpos.copy()
        seed_qpos[self.armq] = fk_fit.x[:7]
        ik = self.ik.solve(seed_qpos,goal,orientation,max_evaluations=80)
        eligible = bool(max(abs(v) for v in gaps.values()) < .004 and depth < .002 and
                        clearance >= -.001 and ik['position_error_m'] < .01 and ik['orientation_error_rad'] < .05 and native_preload['feasible'] and len(set(row['role'] for row in native_rows)) == 3 and native_depth < .002 and not native_scene_bad)
        motor_plan = dict(feasible=False,reason='geometry not admitted')
        self.shape_motor_goal = None
        if eligible:
            from sage.experiments.embodied_carry_v1.grasp import group
            hd = h['dofs'][ix]
            Wcols,Tcols,roles = [],[],[]
            for contact in private.contact:
                pair = contact_pair(model,contact)
                names = [v['name'] for v in pair]
                if 'payload_surface' not in names or contact.dist>=0.:
                    continue
                side = names.index('payload_surface')
                role = group(pair[1-side]['body'])
                if role not in ('thumb','index','middle'):
                    continue
                J = np.zeros((3,model.nv))
                self.mujoco.mj_jac(model,private,J,None,contact.pos,int(model.geom_bodyid[contact.geom[1-side]]))
                D = np.asarray(contact.frame).reshape(3,3)
                sign = 1. if side==1 else -1.
                u,v = contact.friction[:2]
                for ray in ([1,u,0],[1,-u,0],[1,0,v],[1,0,-v]):
                    F = sign*D.T@ray
                    Wcols.append(np.r_[F,np.cross(contact.pos-private.xipos[pid],F)])
                    Tcols.append(J[:,hd].T@F)
                    roles.append(role)
            if Wcols:
                Wmat,Tmat = np.asarray(Wcols).T,np.asarray(Tcols).T
                A = np.array([[float(g==role) for role in roles] for g in ('thumb','index','middle')])
                requested = np.full(3,max(1.,float(native_info['weight_n'])))
                offset = private.qfrc_bias[hd]-private.qfrc_passive[hd]+np.sign(ends)*model.dof_frictionloss[hd]
                act = h['actuators'][ix]
                tau_lo = np.maximum(model.actuator_ctrlrange[act,0],h['kp'][ix]*(np.minimum(0,ends)-x[:7]))
                tau_hi = np.minimum(model.actuator_ctrlrange[act,1],h['kp'][ix]*(np.maximum(0,ends)-x[:7]))
                solution = linprog(np.ones(len(roles)),A_ub=np.r_[A,-A,Tmat,-Tmat],b_ub=np.r_[np.full(3,6.),-requested,tau_hi-offset,-tau_lo+offset],A_eq=Wmat,b_eq=np.zeros(6),bounds=(0,None),method='highs')
                if solution.success:
                    goal_reference = x[:7]+(Tmat@solution.x+offset)/h['kp'][ix]
                    self.shape_motor_goal = np.zeros(len(h['names']))
                    self.shape_motor_goal[ix] = goal_reference
                    motor_plan = dict(feasible=True,motor_reference_rad=goal_reference.tolist(),physical_touch_rad=x[:7].tolist(),normal_targets_n=dict(zip(('thumb','index','middle'),requested.tolist())),allocated_group_normals_n=dict(zip(('thumb','index','middle'),(A@solution.x).tolist())),equilibrium_wrench_error=float(np.max(np.abs(Wmat@solution.x))),native_dry_friction_nm=model.dof_frictionloss[hd].tolist(),required_motor_torque_nm=(Tmat@solution.x+offset).tolist(),reference_bound_ratio=.65)
                else:
                    motor_plan = dict(feasible=False,reason=solution.message,normal_targets_n=requested.tolist())
            eligible = bool(eligible and motor_plan['feasible'])
        self.events.append(dict(kind='expert_shape_reference_admission', tick=tick,
            object_id=self.case['object_id'], bounds_local_m=[lo.tolist(), hi.tolist()],
            semantic_axis=self.case['orientation_axis'], finger_target_touch_rad=x[:7].tolist(),
            bottle_neck_contact_band_local_z_m=[.103,.122], reference_payload_collision_radius_m=collision_radius, radius_profile_m=np.column_stack([profile_z,profile_radius]).tolist(),
            finger_names=[h['names'][i] for i in ix], wrist_goal_m=goal.tolist(), wrist_R=orientation.tolist(),
            mesh_vertex_gaps_m=gaps, envelope_depth_m=depth, hand_desk_clearance_m=clearance,
            optimizer_cost=float(fit.cost), optimizer_nfev=int(fit.nfev), private_IK=ik,
            kinematic_refinement_cost=float(fk_fit.cost), kinematic_refinement_nfev=int(fk_fit.nfev),
            native_geometry_contacts=native_rows, native_preload_capacity=native_preload,
            native_contact_depth_m=native_depth, native_scene_bad=native_scene_bad,
            native_motor_preload_plan=motor_plan,
            reference_admitted=eligible, new_physics_steps=0,
            limitation='Sampled native-hand vertex reference screen against measured object envelope; actual native contacts and full dynamic gates remain mandatory.'))
        if not eligible:
            self.failure = self.case['object_id']+'_shape_reference_not_admitted'
            return
        self.shape_offset_object = x[7:10].copy()
        self.shape_orientation_object = Q.copy()
        self.shape_touch = np.zeros(len(h['names']))
        self.shape_touch[ix] = x[:7]
        self.shape_goal = goal
        self.grasp_R = orientation
        self.shape_ready = True
        weight = float(model.body_mass[pid]*abs(model.opt.gravity[2]))
        self.preload_targets = {g:max(1.0, weight) for g in ('thumb', 'index', 'middle')}
        self.normal_targets = self.preload_targets.copy()

    def force_update(self, tick, data, m):
        self.begin_hand_reference_tick(tick)
        if not self.grasp_test_passed or self.stage not in ('tuck', 'carry', 'target_stop', 'place'):
            result = super().force_update(tick, data, m)
            self.project_hand_reference(tick)
            return result
        if self.stage == 'place':
            self.project_hand_reference(tick)
            return
        from sage.experiments.embodied_carry_v1.grasp import group
        h = hand_ids(self.model)
        pid = self.model.body('payload').id
        W = data.xmat[self.wrist].reshape(3,3)
        C = data.xmat[pid].reshape(3,3)
        mass = float(self.model.body_mass[pid])
        weight = mass*abs(float(self.model.opt.gravity[2]))
        if not hasattr(self, 'contact_pose_anchor'):
            self.contact_pose_anchor = W.T@(data.xipos[pid]-data.xpos[self.wrist])
            self.contact_relative_R = W.T@C
            self.contact_minimum = {g:max(float(self.normal_targets[g]),float(m['forces'][g])) for g in ('thumb','index','middle')}
        hv, cv = np.zeros(6), np.zeros(6)
        J = np.zeros((3,self.model.nv))
        Jr = np.zeros_like(J)
        self.mujoco.mj_jac(self.model,data,J,Jr,data.xpos[self.wrist],self.wrist)
        hv[:3],hv[3:] = Jr@data.qvel,J@data.qvel
        self.mujoco.mj_jac(self.model,data,J,Jr,data.xipos[pid],pid)
        cv[:3],cv[3:] = Jr@data.qvel,J@data.qvel
        target = wrench(weight,mass,data.xpos[self.wrist],W,self.contact_pose_anchor,
                        self.contact_relative_R,data.xipos[pid],C,hv,cv)
        proposal = allocate(self.mujoco,self.model,data,self.contact_minimum,target,.65)
        ix = np.array([i for i,n in enumerate(h['names']) if n in RIGHT_CLOSED])
        ends = np.array([RIGHT_CLOSED[h['names'][i]]*.65 for i in ix])
        if proposal['feasible']:
            self.finger_reference[ix] = fast_update(self.finger_reference[ix],np.asarray(proposal['desired_contact_torque_nm']),np.asarray(proposal['measured_contact_torque_nm']),h['kp'][ix],ends)
        self.project_hand_reference(tick)
        self.feedback_allocation = proposal
        self.group_values = {g:max([abs(self.finger_reference[i]/RIGHT_CLOSED[n]) for i,n in enumerate(h['names']) if n in RIGHT_CLOSED and group(n)==g],default=0.) for g in ('thumb','index','middle')}
        self.closure = max(self.group_values.values())
        if tick%5 == 0:
            self.events.append(dict(kind='expert_shape_loaded_native_feedback',tick=tick,stage=self.stage,allocation=proposal,reference_rad=self.finger_reference.tolist(),reference_bound_ratio=.65))

    def normal_control(self, tick, data, m):
        self.begin_hand_reference_tick(tick)
        # Independent targets for this shape, driven by measured native normals.
        from sage.experiments.embodied_carry_v1.grasp import group
        h = hand_ids(self.model)
        if self.finger_reference is None:
            self.finger_reference = np.zeros(len(h['names']))
        if not self.shape_ready:
            return
        if self.loaded_balance_started is not None and not hasattr(self, 'tracking_goals'):
            self.tracking_goals = {g:max(float(self.normal_targets[g]), float(m['forces'][g])) for g in ('thumb', 'index', 'middle')}
        for i, name in enumerate(h['names']):
            if name not in RIGHT_CLOSED:
                continue
            end = RIGHT_CLOSED[name]*.65
            role = group(name)
            goal = self.shape_motor_goal[i] + np.sign(end)*np.clip((self.normal_targets[role]-m['forces'][role])*.03, -.06, .15)
            goal = np.clip(goal, min(0., end), max(0., end))
            self.finger_reference[i] += np.clip(goal-self.finger_reference[i], -.006, .006)
        if self.stage in ('load_probe','lift','loaded_hover') and self.acquired_probe_reference_floor is not None:
            for i,name in enumerate(h['names']):
                if name not in RIGHT_CLOSED:
                    continue
                if RIGHT_CLOSED[name] > 0:
                    self.finger_reference[i] = max(self.finger_reference[i],self.acquired_probe_reference_floor[i])
                else:
                    self.finger_reference[i] = min(self.finger_reference[i],self.acquired_probe_reference_floor[i])
            self.acquired_probe_reference_floor = self.finger_reference.copy()
        self.project_hand_reference(tick)
        self.group_values = {g:max([abs(self.finger_reference[i]/RIGHT_CLOSED[n]) for i,n in enumerate(h['names']) if n in RIGHT_CLOSED and group(n)==g],default=0.) for g in ('thumb','index','middle')}
        self.closure = max(self.group_values.values())
        if tick%5 == 0:
            self.events.append(dict(kind='expert_shape_native_normal_feedback', tick=tick,
                forces=dict(m['forces']), targets_n=self.normal_targets.copy(), reference_rad=self.finger_reference.tolist()))

    def plan(self, tick, data, goal, R, duration, label):
        p, old_R = self.desired(tick)
        self.path = make_path(tick, p, old_R, goal, R, duration)
        self.joint_path = None
        self.events.append(dict(kind='bottle_frame_reference', tick=tick, label=label,
                                origin=p.tolist(), goal=np.asarray(goal).tolist(),
                                rotation=R.tolist(), duration=duration))
        self.synchronize(tick, data, force=True)

    def move(self, tick, data, goal, rotation, duration=65):
        if self.stage in ('preinsert', 'lower', 'insert'):
            if not self.shape_ready:
                self.shape_reference(tick, data)
            if self.failure:
                return
            from sage.experiments.embodied_native_object_transport_v1.task_v3 import Task as CartesianTask
            pid = self.model.body('payload').id
            C = data.xmat[pid].reshape(3, 3)
            goal = data.xpos[pid]+C@self.shape_offset_object
            goal = goal+np.array([0., 0., {'preinsert':.10, 'lower':.05, 'insert':0.}[self.stage]])
            self.grasp_R = C@self.shape_orientation_object
            return CartesianTask.move(self, tick, data, goal, self.grasp_R,
                                      {'preinsert':90, 'lower':50, 'insert':50}[self.stage])
        if self.stage != 'place':
            return super().move(tick, data, goal, rotation, duration)
        pid = self.model.body('payload').id
        W = data.xmat[self.wrist].reshape(3, 3)
        C = data.xmat[pid].reshape(3, 3)
        self.place_relative_R = W.T @ C
        self.place_local = W.T @ (data.xpos[pid] - data.xpos[self.wrist])
        self.place_com_local = W.T @ (data.xipos[pid] - data.xpos[self.wrist])
        self.place_cup_R = upright(C, self.orientation_axis_id)
        self.place_wrist_R = self.place_cup_R @ self.place_relative_R.T
        self.place_goal = np.asarray(self.case['target_object_xyz_m']).copy()
        requested = self.place_goal.copy()
        desk = self.model.body('generated_desk').id
        desk_vertices = np.asarray(data.flexvert_xpos)[np.asarray(self.model.flex_vertbodyid) == desk]
        top = desk_vertices[desk_vertices[:, 2] >= float(self.case['support_top_m']) - .003]
        fid = self.mujoco.mj_name2id(self.model, self.mujoco.mjtObj.mjOBJ_FLEX, 'payload_surface')
        start = int(self.model.flex_vertadr[fid])
        count = int(self.model.flex_vertnum[fid])
        vertices = np.asarray(data.flexvert_xpos[start:start + count])
        local_vertices = (vertices - data.xpos[pid]) @ C
        planned = local_vertices @ self.place_cup_R.T
        base = planned[planned[:, 2] <= planned[:, 2].min() + .003]
        lower = top[:, :2].min(axis=0) - base[:, :2].min(axis=0) + .020
        upper = top[:, :2].max(axis=0) - base[:, :2].max(axis=0) - .020
        self.place_goal[:2] = np.clip(self.place_goal[:2], lower, upper)
        self.edge_projected = bool(np.linalg.norm(self.place_goal[:2] - requested[:2]) > .001)
        self.support_next = tick
        self.events.append(dict(kind='mesh_base_supported_target', tick=tick,
                                requested_cup_origin=requested.tolist(), planned_cup_origin=self.place_goal.tolist(),
                                feasible_origin_lower_xy=lower.tolist(), feasible_origin_upper_xy=upper.tolist(),
                                desk_top_bounds=[top[:, :2].min(axis=0).tolist(), top[:, :2].max(axis=0).tolist()],
                                cup_base_bounds=[base[:, :2].min(axis=0).tolist(), base[:, :2].max(axis=0).tolist()],
                                margin_m=.020, projected=self.edge_projected))
        self.airborne_support_finished = False
        self.place_step = 'align'
        self.place_step_start = tick
        self.release_origin = None
        self.support_corrections = 0
        self.support_next = tick
        self.plan(tick, data, self.place_goal + [0., 0., .035] -
                  self.place_wrist_R @ self.place_local,
                  self.place_wrist_R, 90, 'upright_above_target')

    def airborne_grip(self, tick, data, m):
        self.begin_hand_reference_tick(tick)
        self.airborne_support_finished = self.preload_table_handoff
        if m['desk_supported'] or self.airborne_support_finished:
            # Hold preload during tentative support; resume wrench feedback if
            # it disappears. Never latch controller shutdown on contact flicker.
            self.project_hand_reference(tick)
            return
        h = hand_ids(self.model)
        pid = self.model.body('payload').id
        R = data.xmat[self.wrist].reshape(3, 3)
        C = data.xmat[pid].reshape(3, 3)
        mass = float(self.model.body_mass[pid])
        weight = mass * abs(float(self.model.opt.gravity[2]))
        hv = np.zeros(6)
        cv = np.zeros(6)
        J = np.zeros((3, self.model.nv))
        Jr = np.zeros_like(J)
        self.mujoco.mj_jac(self.model, data, J, Jr, data.xpos[self.wrist], self.wrist)
        hv[:3], hv[3:] = Jr @ data.qvel, J @ data.qvel
        self.mujoco.mj_jac(self.model, data, J, Jr, data.xipos[pid], pid)
        cv[:3], cv[3:] = Jr @ data.qvel, J @ data.qvel
        target = wrench(weight, mass, data.xpos[self.wrist], R, self.place_com_local,
                        self.place_relative_R, data.xipos[pid], C, hv, cv)
        proposal = allocate(self.mujoco, self.model, data, self.contact_minimum,
                            target, float(self.case['loaded_native_reference_ratio']))
        if proposal['feasible']:
            ix = np.array(proposal['right_finger_indices'])
            ends = np.array([RIGHT_CLOSED[h['names'][i]] * self.case['loaded_native_reference_ratio'] for i in ix])
            self.finger_reference[ix] = fast_update(self.finger_reference[ix],
                np.asarray(proposal['desired_contact_torque_nm']),
                np.asarray(proposal['measured_contact_torque_nm']), h['kp'][ix], ends)
        self.project_hand_reference(tick)
        if tick % 5 == 0:
            self.events.append(dict(kind='airborne_place_native_grip_feedback', tick=tick,
                                    feasible=bool(proposal['feasible']), wrench=target.tolist(),
                                    reference_rad=self.finger_reference.tolist()))

    def observe(self, tick, data, m):
        pid = self.model.body('payload').id
        C = data.xmat[pid].reshape(3, 3)
        vel = np.zeros(6)
        self.mujoco.mj_objectVelocity(self.model, data, self.mujoco.mjtObj.mjOBJ_BODY,
                                     pid, vel, 0)
        up = float(abs(C[2, 0]) if self.orientation_axis_id == 0 else C[2, 2])
        if tick % 5 == 0:
            self.events.append(dict(kind='cup_support_transfer', tick=tick,
                                    stage=self.stage, cup_up=up,
                                    angular_velocity=vel[:3].tolist(),
                                    cup_position=data.xpos[pid].tolist(),
                                    desk_supported=m['desk_supported'],
                                    hand_contact=m['hand_contact'],
                                    forces=dict(m['forces']),
                                    hand_reference=self.finger_reference.tolist()))
        return C, vel, up

    def update(self, tick, data, m):
        self.begin_hand_reference_tick(tick)
        if self.done or self.failure:
            return
        self.observe_target_handoff(tick, data, m)
        self.observe_loaded_contract(tick, data, m)
        if self.stage == 'release':
            evidence = self.target_support_evidence
            if not self.preload_table_handoff:
                # Bounded response: stop opening and fail visibly; no relatch,
                # anchor reset, simulated recovery or hidden unsupported release.
                if not evidence['persistent_support']:
                    self.failure = 'branch1_target_support_lost_during_release'
                elif not self.release_support_observation_consecutive:
                    self.failure = 'branch1_release_support_observation_gap'
                else:
                    self.failure = 'branch1_release_certificate_invalid'
                self.events.append(dict(kind='branch1_release_contract_lost', tick=tick,
                    failure=self.failure, evidence=evidence,
                    entry_certificate=self.release_entry_certificate,
                    action='hold_reference_and_stop'))
                return
        try:
            return self.update_phase(tick, data, m)
        finally:
            self.project_hand_reference(tick)

    def update_phase(self, tick, data, m):
        if (self.stage == 'ready_arm' and not self.done and not self.failure and
                self.joint_path is not None and not self.ready_fine_align_started and
                tick >= self.joint_path['tick']+self.joint_path['duration'] and
                not self.reached(tick,data)):
            goal = np.asarray(self.joint_path['goal_m']).copy()
            R = np.asarray(self.joint_path['R']).copy()
            W = data.xmat[self.wrist].reshape(3,3).copy()
            origin = data.xpos[self.wrist].copy()
            self.path = make_path(tick,origin,W,goal,R,40)
            self.joint_path['duration'] = tick-self.joint_path['tick']+40
            self.ready_fine_align_started = True
            self.events.append(dict(kind='expert_ready_pose_feedback_alignment',tick=tick,
                origin_m=origin.tolist(),goal_m=goal.tolist(),rotation=R.tolist(),duration=40,
                measured_position_error_m=float(np.linalg.norm(goal-origin)),
                measured_orientation_error_rad=float(np.linalg.norm(Rotation.from_matrix(R@W.T).as_rotvec())),
                original_ready_position_threshold_m=.025,original_ready_angle_threshold_rad=.15,
                original_phase_timeout_unchanged=True,all29body_sonic=True))
            self.synchronize(tick,data,force=True)
        if self.stage == 'settle':
            if self.done or self.failure:
                return
            if tick-self.start > self.case['stage_timeouts_ticks']['settle']:
                self.failure = 'settle_timeout'
                return
            ready = (m['desk_supported'] and not m['hand_contact'] and
                     np.linalg.norm(m['object_velocity_m_s']) < .02 and
                     np.linalg.norm(data.qvel[:3]) < .06)
            self.stable = self.stable+1 if ready else 0
            if self.stable >= 51:
                self.events.append(dict(kind='expert_full_settle_observation_window',tick=tick,
                                        observations=51,complete_intervals=50,
                                        unchanged_final_substep_gate=True))
                self.done = True
                self.change('done',tick,data,m)
            return
        if self.stage not in ('place', 'release', 'retract'):
            return super().update(tick, data, m)
        if self.done or self.failure:
            return
        age = tick - self.start
        self.last_object_local = m['object_local_m']
        self.last_object_local_world = np.asarray(m['object_m'])
        C, vel, up = self.observe(tick, data, m)
        if self.stage == 'place':
            self.airborne_grip(tick, data, m)
            if age > 600:
                self.failure = 'cup_upright_place_timeout'
                return
            slip = float(np.linalg.norm(np.asarray(m['object_local_m']) - self.anchor))
            self.max_slip = max(self.max_slip, slip)
            if slip > .04:
                self.failure = 'object_slipped'
                return
            if self.place_step == 'align':
                ready = self.reached(tick, data) and up > .985 and np.linalg.norm(vel[:3]) < (.6 if self.edge_projected else .3)
                self.stable = self.stable + 1 if ready else 0
                if self.stable >= (5 if self.edge_projected else 10):
                    self.stable = 0
                    self.place_step = 'lower'
                    self.place_step_start = tick
                    self.support_next = tick + 85
                    self.plan(tick, data, self.place_goal -
                              self.place_wrist_R @ self.place_local,
                              self.place_wrist_R, 65, 'upright_lower_to_support')
            else:
                ready = (self.reached(tick, data) and m['desk_supported'] and
                         up > .985 and np.linalg.norm(vel[:3]) < .25 and
                         np.linalg.norm(np.asarray(m['object_m'])[:2] - self.place_goal[:2]) < .10)
                self.stable = self.stable + 1 if ready else 0
                if (self.stable == 0 and tick >= self.support_next and
                        self.support_corrections < 5 and
                        (up < .985 or not m['desk_supported'])):
                    p, R = self.desired(tick)
                    W = data.xmat[self.wrist].reshape(3, 3)
                    pid = self.model.body('payload').id
                    local = W.T @ (data.xpos[pid] - data.xpos[self.wrist])
                    tilt = Rotation.from_matrix(upright(C, self.orientation_axis_id) @ C.T).as_rotvec()
                    magnitude = np.linalg.norm(tilt)
                    correction = (tilt * min(.7, .10 / max(magnitude, 1e-9))
                                  if up < .985 else np.zeros(3))
                    G = Rotation.from_rotvec(correction).as_matrix() @ R
                    goal = p - (G - R) @ local
                    weight = float(self.model.body_mass[pid] * abs(self.model.opt.gravity[2]))
                    relief = (np.clip((m['forces']['desk'] - weight) * .0006, 0., .003)
                              if m['desk_supported'] else (-.001 if up > .985 else .001))
                    goal[2] += relief
                    nominal_z = self.place_goal[2] - (G @ self.place_local)[2]
                    goal[2] = np.clip(goal[2], nominal_z - .010, nominal_z + .015)
                    self.support_corrections += 1
                    self.support_next = tick + 65
                    self.events.append(dict(kind='measured_cup_support_correction', tick=tick,
                                            attempt=self.support_corrections, cup_up=up,
                                            correction_rad=correction.tolist(), relief_m=float(relief),
                                            cup_in_wrist_m=local.tolist(), forces=dict(m['forces'])))
                    self.plan(tick, data, goal, G, 40, 'measured_cup_support_correction')
                if (self.stable >= (8 if self.support_corrections else 20) and
                        self.preload_table_handoff):
                    self.change('release', tick, data, m)
                    self.release_start = tick
                    self.release_origin = self.finger_reference.copy()
        elif self.stage == 'release':
            # Native position targets only; maintain wrist pose during transfer.
            f = float(smooth(age / 100.))
            self.finger_reference = self.release_origin * (1. - f)
            self.closure = self.case['grip_closure'] * (1. - f)
            if age >= 115 and m['desk_supported'] and not m['hand_contact']:
                self.change('retract', tick, data, m)
                p, R = self.desired(tick)
                self.plan(tick, data, p + [-.15, 0., .08], R, 60, 'open_hand_retract')
            elif age > 200:
                self.failure = 'supported_release_timeout'
        elif self.stage == 'retract':
            self.finger_reference[:] = 0.
            if self.reached(tick, data):
                self.change('settle', tick, data, m)
            elif age > 250:
                self.failure = 'retract_timeout'
