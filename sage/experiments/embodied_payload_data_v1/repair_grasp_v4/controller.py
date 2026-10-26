"""Separate hand intent from measured torso/arm progress and load transfer.

The diagnostic controller retains native actuation and all integrated collision
gates. Production force/transient calibration is independently required.
"""
import numpy as np
import mujoco
from ..repair_feedback.controller import FeedbackController
from ..repair_v2.progress import ControlRejected
from .progress import CoordinatedPath
from .feedback import BoundedBias
from .intent import HandIntent, GraspGate
from .geometry import closure_corridor


class GraspController(FeedbackController):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.hand_indices={s:np.asarray(self.c['inspection']['groups'][s+'_hand'])-12 for s in ('left','right')}
        self.body_indices=tuple(int(i) for i in range(31) if i+12 not in self.fingers)
        self.path=CoordinatedPath(self.path.path,tracking_waypoints=self.path.tracking_path)
        self.feedback=BoundedBias(self.last_goal_upper)
        self.hand_modes={s:'position' for s in self.hand_indices}
        self.grasp_gate=GraspGate()
        self.grasp_origin=None
        self.grasp_evidence=None
        self.grasp_report=None
        self.initial_object_z=float(args[4].qpos[52])
        self.local_grasp_only=False
        self.grasp_ready_ticks=0
        self.current_force_guard=False
        self.source_supports=[n for n in self.c['names'] if n.startswith('table_collider_')]
        self.last_closure_pose=None

    def resume_local(self,data,previous_command,previous_velocity,source_phase):
        # Single initial state is assigned by the worker, never here. Preserve
        # the retained issued-command velocity through the new handoff.
        k=int(np.searchsorted(self.source_phases,source_phase,side='right'))
        states=np.concatenate([data.qpos[None,:],self.states[k:]])
        commands=np.concatenate([np.asarray(previous_command)[None,12:43],np.asarray(self.path.path)[k:]])
        self.source_phases=np.r_[source_phase,self.source_phases[k:]]
        self.states=states
        self.path=CoordinatedPath(commands,tracking_waypoints=states[:,self.qmap[self.upper]])
        self.last_goal_upper=np.asarray(previous_command)[12:43].copy()
        self.last_command=np.asarray(previous_command).copy()
        self.feedback=BoundedBias(self.last_goal_upper)
        self.feedback.velocity=list(np.asarray(previous_velocity)[12:43])
        self.current_phase=float(source_phase)
        self.local_grasp_only=True

    def _new_measured_path(self,held):
        tracking=self.states[:,self.qmap[self.upper]].copy()
        bias=np.asarray(held)-tracking[0]
        commands=tracking+bias
        if self.phase=='release':
            # Contact preload must disappear when releasing. Position targets
            # become the free-motion reference when each hand loses contact.
            for f,row in zip(np.linspace(0,1,len(commands)),commands):
                for ids in self.hand_indices.values():
                    row[ids]=np.asarray(held)[ids]*(1-f)+tracking[-1,ids]*f
            for ids in self.hand_indices.values():tracking[:,ids]=commands[:,ids]
        previous_velocity=self.feedback.velocity[:]
        self.path=CoordinatedPath(commands,tracking_waypoints=tracking)
        self.last_goal_upper=np.asarray(held).copy()
        self.feedback=BoundedBias(held)
        self.feedback.velocity=previous_velocity

    def _set_intents(self):
        end=min(self.path.segment+1,len(self.path.path)-1)
        nominal=np.asarray(self.path.path[end])
        active=list(self.body_indices)
        for side,ids in self.hand_indices.items():
            contacts=0 if self.grasp_evidence is None else self.grasp_evidence['hand_contacts_by_side'][side]
            if self.phase in {'carry','settle','place'}:
                mode='contact_preload'
            elif self.phase=='release':
                mode='contact_preload' if contacts else 'position'
            elif self.phase=='hold':mode='position'
            else:mode='contact_preload' if np.max(abs(nominal[ids]))>.02 else 'position'
            self.hand_modes[side]=mode
            intent=HandIntent(mode,tuple(nominal[ids]),tuple(nominal[ids]) if mode=='position' else None)
            enabled=intent.integral_error(nominal[ids]) is not None
            for i in ids:self.feedback.integration_enabled[int(i)]=enabled
            if enabled:
                active.extend(map(int,ids))
                # The planned command is the declared free-space reference.
                for command,tracking in zip(self.path.path,self.path.tracking_path):
                    for i in ids:tracking[int(i)]=command[int(i)]
        self.path.tracking_indices=tuple(active)

    def _path_step(self,data):
        self._set_intents()
        prior_expected=self.path.expected_actual.copy()
        segment=self.path.segment
        def safe(previous,command,stop):
            if segment>=len(self.states)-1:return True
            a,b=np.asarray(self.path.path[segment:segment+2]);delta=b-a;den=float(delta@delta)
            configs=[data.qpos.copy()]
            for value in (previous,command,stop):
                u=0. if den<1e-15 else float(np.clip((np.asarray(value)-a)@delta/den,0,1))
                configs.append(self._planned_state(segment,u))
            self.last_sweep=self.query.sweep(configs,self.phase,margin=.003,source_supports=self.source_supports)
            return self.last_sweep['passed']
        nominal,meta=self.path.step(data.qpos[self.qmap[self.upper]],safe)
        query=self.actuator_query;m=self.query.m
        query.qpos[:]=data.qpos;query.qvel[:]=data.qvel;mujoco.mj_forward(m,query)
        def actuator_safe(command):
            full=self.last_command.copy();full[12:43]=command
            self.actuator_audit.expected(query,full)
            for part,(ids,dofs,aids,kp,kd) in self.actuator_audit.parts.items():
                if part=='legs':continue
                pd=kp*(full[ids]-query.qpos[self.qmap[ids]])-kd*query.qvel[dofs]
                raw=self.actuator_audit.matrix[np.ix_(dofs,dofs)]@pd+query.qfrc_bias[dofs]
                if np.any(raw<m.actuator_ctrlrange[aids,0]) or np.any(raw>m.actuator_ctrlrange[aids,1]):
                    self.feedback_rejection=dict(part=part,raw=raw.tolist(),limits=m.actuator_ctrlrange[aids].tolist())
                    return False
            return True
        issued,feedback=self.feedback.step(nominal,prior_expected,data.qpos[self.qmap[self.upper]],bounds=self.command_bounds,safe=actuator_safe)
        if self.phase=='pick' and any(m=='contact_preload' for m in self.hand_modes.values()):
            # Recheck after each0.01rad hand target or2mm whole-pose movement;
            # unchanged cached envelopes are not counted as new observations.
            key=np.r_[data.qpos,np.asarray(issued)]
            changed=self.last_closure_pose is None or np.max(abs(key-self.last_closure_pose))>.002
            if changed:
                self.last_closure=closure_corridor(self.query,data.qpos.copy(),np.asarray(issued)[self.fingers-12],self.fingers,self.source_supports)
                if not self.last_closure['passed']:raise ControlRejected('finger_closure_corridor')
                self.last_closure_pose=key
        self.last_goal_upper=np.asarray(issued)
        meta.update(feedback=feedback,expected_actual=list(self.path.expected_actual),actual=data.qpos[self.qmap[self.upper]].tolist(),
            tracking_indices=list(self.path.tracking_indices),hand_modes=self.hand_modes.copy())
        return meta

    def target(self,data,evidence=None):
        self.grasp_evidence=evidence
        self.path.external_pause=False
        if evidence is not None and self.phase=='pick' and self.current_phase>=200:
            bilateral=all(evidence['hand_contacts_by_side'][s]>0 for s in self.hand_indices)
            error=max(abs(data.qpos[self.qmap[12+i]]-self.path.expected_actual[i]) for i in self.body_indices)
            self.grasp_ready_ticks=self.grasp_ready_ticks+1 if bilateral and error<=.02 else 0
            if self.grasp_origin is None and bilateral:
                self.grasp_origin={s:np.asarray(evidence['hand_object_relative'][s]['position']) for s in self.hand_indices}
                self.probe_origin_z=float(data.qpos[52])
            relative=0. if self.grasp_origin is None else max(np.linalg.norm(np.asarray(evidence['hand_object_relative'][s]['position'])-self.grasp_origin[s]) for s in self.hand_indices)
            speed=max(evidence['hand_object_relative'][s]['speed'] for s in self.hand_indices)
            if self.current_phase>=210:
                self.grasp_report=self.grasp_gate.observe(time=evidence['time'],semantics=evidence['force_semantics'],
                    contacts=evidence['hand_contacts_by_side'],upward_load=evidence['hand_vertical_load'],weight=evidence['weight'],
                    relative_displacement=float(relative),relative_speed=float(speed),
                    lift=max(0.,float(data.qpos[52])-getattr(self,'probe_origin_z',float(data.qpos[52]))),
                    arm_tracking_ok=error<=.02,corridor_passed=getattr(self,'last_sweep',{}).get('passed',False),
                    force_limits_passed=self.current_force_guard)
                # Until load transfers, the next planned motion may only be a
                # bounded probe. Local grasp diagnostics terminate before this.
                allowed=self.grasp_report['allow_full_lift'] or self.grasp_report['allow_probe']
                self.path.external_pause=not allowed
            if self.local_grasp_only:
                self.path.external_pause=True
        goal,meta=super().target(data,evidence)
        meta.update(hand_modes=self.hand_modes.copy(),grasp_ready_ticks=self.grasp_ready_ticks,grasp_gate=self.grasp_report)
        return goal,meta
