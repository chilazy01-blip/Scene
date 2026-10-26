"""Measured, coordinated task controller for prospective v2 experiments.

The native policy supplies balance/navigation. Stopped placement adds a bounded
planned leg correction to that policy, explicitly logged for independent replay.
This is a new controller, not an exact replay of the source demonstration.
"""
import numpy as np
import mujoco
from scipy.spatial.transform import Rotation, Slerp

from ..geometry import Arms, yaw, wrap
from .geometry import SceneQuery, JointPlacementPlanner
from .progress import CoordinatedPath, ControlRejected, MotionLimits, validate_ik
from .withdrawal import plan_withdrawal


class TaskController:
    def __init__(self, model, contract, demo, reference, initial, check_deadline):
        self.query = SceneQuery(model, contract)
        self.arms = Arms(model, contract)
        self.c, self.ref, self.demo = contract, reference, demo
        self.qmap = self.query.qmap
        self.upper = np.arange(12,43)
        self.fingers = np.array(contract['inspection']['groups']['left_hand']+contract['inspection']['groups']['right_hand'])
        self.check_deadline = check_deadline
        self.phase = 'pick'
        self.last_command = initial.qpos[self.qmap].copy()
        self.anchor = None
        self.support_ticks = self.settle_ticks = self.release_ticks = 0
        self.plans = []
        self.leg_correction = np.zeros(12)
        self.grasp_origin = None
        self.current_phase = 0.
        self.preparing = False
        self.height_bias = 0.
        self.last_height_command = float(initial.qpos[2])
        # Commands and expected joint states are distinct for loaded position
        # actuators. Both use the same scalar path progress and derivative bounds.
        cache = {}
        def sample(phase):
            if phase in cache:return cache[phase]
            q = reference['qpos'][phase].copy()
            goal = np.asarray(demo['goals'][phase]['target_upper_body_pose']).copy()
            goal += reference['delta'][phase,self.qmap[self.upper]]
            if phase >= 320:
                dz = max(0.,float(reference['qpos'][330,52]-q[52]))
                poses = self.arms.poses(q)
                targets = {side:(p+np.array([0.,0.,dz]),r) for side,(p,r) in poses.items()}
                changed, errors = self.arms.solve(q,targets,iterations=32)
                self._validate(changed,errors)
                goal += changed[self.qmap[self.upper]]-q[self.qmap[self.upper]]
                q = changed
                q[52] += dz
            cache[phase]=(q,goal)
            return cache[phase]
        arm_ids=np.array(contract['inspection']['groups']['left_arm']+contract['inspection']['groups']['right_arm'])
        def refine(a,b):
            qa,_=sample(a);qb,_=sample(b)
            angle=2*np.arccos(np.clip(abs(np.dot(qa[53:57],qb[53:57])),0,1))
            joint_delta=float(np.max(np.abs(qa[self.qmap[arm_ids]]-qb[self.qmap[arm_ids]])))
            if b-a>1 and (angle>.04 or joint_delta>.08 or np.linalg.norm(qa[50:53]-qb[50:53])>.015):
                mid=(a+b)//2
                return refine(a,mid)[:-1]+refine(mid,b)
            return [a,b]
        phases=[0]
        coarse=[0,*range(20,431,20),430]
        for a,b in zip(coarse,coarse[1:]):phases.extend(refine(a,b)[1:])
        self.source_phases=np.asarray([0,*phases])
        states=[initial.qpos.copy()]+[sample(p)[0] for p in phases]
        commands=[initial.qpos[self.qmap[self.upper]].copy()]+[sample(p)[1] for p in phases]
        self.states = np.asarray(states)
        self.path = CoordinatedPath(commands, tracking_waypoints=self.states[:,self.qmap[self.upper]])
        self.last_goal_upper = commands[0].copy()
        self.start_height = float(initial.qpos[2])

    def begin_checkpoint(self,data,previous_command,kind):
        """Reconcile a moving retained checkpoint before planning from it.

        Commands remain fixed until observed velocities/contact support settle.
        No state is restored here and no trajectory progress is inferred from
        elapsed time. The new path starts at the subsequently measured pose.
        """
        if kind not in {'place','release'}:raise ValueError('invalid_checkpoint_phase')
        self.phase=self.regression_kind=kind
        self.last_goal_upper=np.asarray(previous_command)[12:43].copy()
        self.states=np.stack([data.qpos.copy(),data.qpos.copy()])
        self.path=CoordinatedPath([self.last_goal_upper,self.last_goal_upper],tracking_waypoints=self.states[:,self.qmap[self.upper]])
        self.anchor=data.qpos[:3].copy()
        self.last_height_command=float(data.qpos[2])
        self.preparing=True
        self.preparation_ticks=self.preparation_stable_ticks=0
        self.preparation_last_time=None

    def _validate(self,q,errors):
        self.query.set(q)
        jp = np.zeros((3,self.query.m.nv));jr=jp.copy()
        for side,ids in self.arms.ids.items():
            mujoco.mj_jacBody(self.query.m,self.query.d,jp,jr,self.arms.body[side])
            errors[side]['condition'] = float(np.linalg.cond(np.vstack([jp[:,self.qmap[ids]-1],jr[:,self.qmap[ids]-1]*.3])))
        validate_ik(errors)

    def _planned_state(self, segment=None, progress=None):
        segment = self.path.segment if segment is None else segment
        progress = self.path.u if progress is None else progress
        if segment >= len(self.states)-1:
            return self.states[-1].copy()
        a,b = self.states[segment:segment+2]
        q = a*(1-progress)+b*progress
        for sl in (slice(3,7),slice(53,57)):
            qb = b[sl] if np.dot(a[sl],b[sl]) >= 0 else -b[sl]
            q[sl] = a[sl]*(1-progress)+qb*progress
            q[sl] /= np.linalg.norm(q[sl])
        return q

    def _path_step(self, data):
        segment = self.path.segment
        def safe(previous,command,stop):
            # Geometry predicts measured configurations. Actuator preload is
            # never mistaken for an attainable collision-free configuration.
            if segment >= len(self.states)-1:
                return True
            a,b = np.asarray(self.path.path[segment:segment+2])
            delta = b-a;den = float(delta@delta)
            configs = [data.qpos.copy()]
            for value in (previous,command,stop):
                u = 0. if den<1e-15 else float(np.clip((np.asarray(value)-a)@delta/den,0,1))
                q = self._planned_state(segment,u)
                # Keep the planned base, object and palms in the same frame.
                # The leading measured configuration checks the residual bridge;
                # this sampled prediction does not certify native WBC tracking.
                configs.append(q)
            source_supports = [self.c['names'][g] for g in self.query.active if self.c['names'][g].startswith('table_collider_')]
            self.last_sweep = self.query.sweep(configs,self.phase,margin=.003,source_supports=source_supports)
            return self.last_sweep['passed']
        command, meta = self.path.step(data.qpos[self.qmap[self.upper]],safe)
        self.last_goal_upper = np.asarray(command)
        return meta

    def _placement(self,data):
        self.height_bias=self.last_height_command-float(data.qpos[2])
        result = JointPlacementPlanner(self.query,max_evaluations=80).plan(data.qpos.copy(),data.qpos.copy(),self.check_deadline)
        self.plans.append(result)
        if not result['passed']:
            raise ControlRejected('joint_placement_infeasible')
        end = np.asarray(next(x['qpos'] for x in result['candidates'] if x['passed']))
        start = data.qpos.copy()
        palms0,palms1 = self.arms.poses(start),self.arms.poses(end)
        rotations={s:Slerp([0,1],Rotation.from_matrix([palms0[s][1],palms1[s][1]])) for s in palms0}
        states=[start]
        for fraction in np.linspace(0,1,7)[1:]:
            self.check_deadline()
            q=start*(1-fraction)+end*fraction
            for sl in (slice(3,7),slice(53,57)):q[sl]/=np.linalg.norm(q[sl])
            targets={s:(palms0[s][0]*(1-fraction)+palms1[s][0]*fraction,rotations[s](fraction).as_matrix()) for s in palms0}
            q,errors=self.arms.solve(q,targets,iterations=32);self._validate(q,errors)
            if not self.query.sweep([states[-1],q],'place',margin=.003)['passed']:
                raise ControlRejected('placement_sweep_infeasible')
            states.append(q)
        self.states=np.asarray(states)
        bias=self.last_goal_upper-start[self.qmap[self.upper]]
        commands=self.states[:,self.qmap[self.upper]]+bias
        self.path=CoordinatedPath(commands,tracking_waypoints=self.states[:,self.qmap[self.upper]])
        self.placement_start=start
        self.phase='place'

    def _release(self,data):
        self.height_bias=self.last_height_command-float(data.qpos[2])
        open_fingers=self.ref['qpos'][-1,self.qmap[self.fingers]]
        result=plan_withdrawal(self.query,data.qpos.copy(),open_fingers,self.check_deadline,phase='release')
        self.plans.append(result)
        if not result['passed']:raise ControlRejected('release_sweep_infeasible')
        self.states=np.asarray(result['states'])
        bias=self.last_goal_upper-self.states[0,self.qmap[self.upper]]
        commands=np.array([q[self.qmap[self.upper]]+bias*(1-f) for q,f in zip(self.states,np.linspace(0,1,len(self.states)))])
        self.path=CoordinatedPath(commands,tracking_waypoints=self.states[:,self.qmap[self.upper]])
        self.phase='release'

    def target(self,data,evidence=None):
        self.check_deadline()
        if self.preparing:
            self.preparation_ticks+=1
            if evidence is not None:
                if evidence.get('force_semantics')!='integrated_step_world_force':
                    raise ControlRejected('checkpoint_requires_integrated_evidence')
                stamp=evidence.get('time',float('nan'))
                if not np.isfinite(stamp) or (self.preparation_last_time is not None and abs(stamp-self.preparation_last_time-.02)>1e-8):
                    raise ControlRejected('stale_checkpoint_observation')
                self.preparation_last_time=stamp
            stable=evidence is not None and all(evidence['foot_load'][s]>=5 for s in ('left','right'))
            stable=stable and np.max(np.abs(data.qvel[self.qmap[self.upper]-1]))<.05 and np.linalg.norm(data.qvel[:3])<.08 and np.linalg.norm(data.qvel[3:6])<.18
            if evidence is not None:
                if self.regression_kind=='place':
                    stable=stable and all(evidence['hand_contacts_by_side'][s]>0 for s in ('left','right')) and (evidence['hand_vertical_load']>=.8*evidence['weight'] or evidence['board_vertical_load']>=.9*evidence['weight'])
                else:
                    stable=stable and evidence['hand_contacts']==0 and evidence['board_vertical_load']>=.9*evidence['weight']
                stable=stable and evidence['object_linear']<.03 and evidence['object_angular']<.1
            self.preparation_stable_ticks=self.preparation_stable_ticks+1 if stable else 0
            if self.preparation_stable_ticks>=10:
                self.preparing=False
                if self.regression_kind=='place':self._placement(data)
                else:self._release(data)
            else:
                if self.preparation_ticks>150:raise ControlRejected('checkpoint_settling_timeout')
                goal=dict(navigate_cmd=np.zeros(3),base_height_command=np.array([self.last_height_command]),target_upper_body_pose=self.last_goal_upper.copy())
                return goal,dict(phase=self.phase,source_phase=0.,progress=dict(finished=False,lag=None),preparing=True,
                                 observed_stable_ticks=self.preparation_stable_ticks,planned_root=self.anchor.tolist(),leg_correction=self.leg_correction.tolist())
        if evidence is not None:
            supported=evidence['board_vertical_load']>=.9*evidence['weight'] and evidence['bottom_margin']>=.005
            grasped=all(evidence['hand_contacts_by_side'][s]>0 for s in ('left','right'))
            if self.phase=='pick' and grasped and data.qpos[52]>self.states[0,52]+.05:
                self.phase='carry'
            if self.phase in {'carry','settle'} and not grasped:
                raise ControlRejected('bilateral_grasp_lost')
            if self.phase=='place':
                self.support_ticks=self.support_ticks+1 if supported and evidence['object_linear']<.02 else 0
                if self.path.finished and self.support_ticks>=10 and getattr(self,'regression_kind',None)!='place':self._release(data)
            if self.phase=='release':
                self.release_ticks=self.release_ticks+1 if supported and evidence['hand_contacts']==0 else 0
                if self.path.finished and self.release_ticks>=10:self.phase='hold'
        if self.phase=='settle':
            stable=np.linalg.norm(data.qvel[:3])<.08 and np.linalg.norm(data.qvel[3:6])<.18
            self.settle_ticks=self.settle_ticks+1 if stable else 0
            if self.settle_ticks>=30:self._placement(data)
        if self.phase not in {'settle','hold'}:
            meta=self._path_step(data)
        else:meta=dict(finished=self.path.finished,lag=None)
        planned=self._planned_state()
        nav=np.zeros(3)
        if self.phase in {'pick','carry'}:
            seg=min(self.path.segment,len(self.source_phases)-2)
            self.current_phase=float(self.source_phases[seg]*(1-self.path.u)+self.source_phases[seg+1]*self.path.u)
            if self.current_phase>=230:
                angle=yaw(data.qpos[3:7]);err=planned[:2]-data.qpos[:2]
                rotation=np.array([[np.cos(angle),np.sin(angle)],[-np.sin(angle),np.cos(angle)]])
                nav[:2]=rotation@(2.0*err)
                norm=np.linalg.norm(nav[:2])
                if norm>.18:nav[:2]*=.18/norm
                nav[2]=np.clip(2*wrap(yaw(planned[3:7])-angle),-.4,.4)
            if self.path.finished:
                if self.phase!='carry':raise ControlRejected('pickup_not_verified')
                self.phase='settle';self.anchor=data.qpos[:3].copy();nav[:]=0
        if self.phase=='place':
            self.leg_correction=planned[self.qmap[:12]]-self.placement_start[self.qmap[:12]]
        height=float(np.clip(planned[2]+self.height_bias,.70,.80))
        self.last_height_command=height
        goal=dict(navigate_cmd=nav,base_height_command=np.array([height]),target_upper_body_pose=self.last_goal_upper.copy())
        return goal,dict(phase=self.phase,source_phase=self.current_phase,progress=meta,planned_root=planned[:3].tolist(),leg_correction=self.leg_correction.tolist())

    def apply(self,native_command):
        command=native_command.copy()
        command[12:43]=self.last_goal_upper
        if self.phase in {'place','release','hold'}:
            command[:12]+=self.leg_correction
        self.last_command=command.copy()
        return command
