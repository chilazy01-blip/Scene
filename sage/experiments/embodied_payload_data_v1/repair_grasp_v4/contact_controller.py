"""Measured-base waist/arm replanning at bounded rest-to-rest waypoints."""
import numpy as np
from scipy.spatial.transform import Rotation
from .controller import GraspController
from .alignment import solve_measured_upper,relative_targets,object_rotation
from .digit_corridor import digit_closure_corridor
from ..repair_v2.progress import ControlRejected


class ContactAnchoredController(GraspController):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.templates=self.states.copy()
        self.nominal_commands=np.asarray(self.path.path).copy()
        self.aligned_segments=set();self.alignment_reports=[]
        self.object_anchor=None
        self.force_envelope=None
        self.contact_anchors={}

    def observe_integrated(self,evidence):
        if self.force_envelope is None:raise ControlRejected('full_grasp_force_admission_required')
        self.current_force_guard=self.force_envelope.observe(evidence)

    def target(self,data,evidence=None):
        prior=self.phase
        goal,meta=super().target(data,evidence)
        if prior=='pick' and self.phase=='carry' and not (self.grasp_report or {}).get('allow_transport',False):
            raise ControlRejected('measured_load_transfer_required_before_transport')
        return goal,meta

    def _align_next(self,data):
        k=self.path.segment
        if self.phase not in {'pick','carry'} or k>=len(self.states)-1 or k in self.aligned_segments:return
        if self.source_phases[k+1]<140:return
        if self.path.u!=0 or self.path.speed!=0:raise ControlRejected('alignment_requires_waypoint_stop')
        self.check_deadline()
        previous,template=self.templates[k:k+2]
        seed=data.qpos.copy()
        # Preserve the reference root displacement for navigation, expressed
        # from the measured root. Feet are unchanged during stationary pickup.
        seed[:3]+=template[:3]-previous[:3]
        seed[self.qmap[:12]]+=template[self.qmap[:12]]-previous[self.qmap[:12]]
        base_rot=Rotation.from_quat(np.r_[data.qpos[4:7],data.qpos[3]])
        before_rot=Rotation.from_quat(np.r_[previous[4:7],previous[3]])
        after_rot=Rotation.from_quat(np.r_[template[4:7],template[3]])
        quat=(base_rot*before_rot.inv()*after_rot).as_quat();seed[3:7]=np.r_[quat[3],quat[:3]]
        # Keep expected joint evidence continuous across the handoff. Planning
        # from a measured base never resets observed torso/arm tracking errors.
        seed[self.qmap[self.upper]]=self.path.expected_actual
        if self.source_phases[k+1]<=210:
            target_object=data.qpos.copy()
        else:
            if self.object_anchor is None:self.object_anchor=(data.qpos.copy(),previous.copy())
            measured,anchor=self.object_anchor;delta=object_rotation(measured)@object_rotation(anchor).T
            target_object=template.copy();target_object[50:53]=measured[50:53]+delta@(template[50:53]-anchor[50:53])
            quat=Rotation.from_matrix(delta@object_rotation(template)).as_quat();target_object[53:57]=np.r_[quat[3],quat[:3]]
            if self.phase=='pick' and not (self.grasp_report or {}).get('allow_full_lift',False):
                target_object[52]=min(target_object[52],measured[52]+self.grasp_gate.limits.test_lift_distance)
        targets=relative_targets(self.arms,template,target_object)
        # Once a preloaded hand contacts the object, preserve its measured
        # object-relative palm transform. Re-imposing the demo palm transform
        # with already closed fingers can drive those fingers through the box.
        # This changes an IK target only, never live state or grasp/load gates.
        if self.grasp_evidence is not None:
            measured=self.arms.poses(data.qpos)
            observed_rotation=object_rotation(data.qpos)
            for side in ('left','right'):
                contacting=self.grasp_evidence['hand_contacts_by_side'][side]>0
                if self.hand_modes[side]=='contact_preload' and contacting and side not in self.contact_anchors:
                    position,rotation=measured[side]
                    self.contact_anchors[side]=(observed_rotation.T@(position-data.qpos[50:53]),observed_rotation.T@rotation)
        target_rotation=object_rotation(target_object)
        for side,(position,rotation) in self.contact_anchors.items():
            targets[side]=(target_object[50:53]+target_rotation@position,target_rotation@rotation)
        end,errors=solve_measured_upper(self.arms,seed,targets,self.check_deadline);self._validate(end,errors)
        end[50:57]=target_object[50:57]
        # A preload is not an achieved finger pose. Hold measured fingers in
        # the body sweep; separately inspect each digit's free closing motion.
        end[self.qmap[self.fingers]]=data.qpos[self.qmap[self.fingers]]
        start=data.qpos.copy();start[self.qmap[self.upper]]=self.path.expected_actual
        start[self.qmap[self.fingers]]=data.qpos[self.qmap[self.fingers]]
        sweep=self.query.sweep([data.qpos.copy(),start,end],self.phase,.003,source_supports=self.source_supports)
        self.alignment_reports.append(dict(segment=k,source_phase=float(self.source_phases[k+1]),errors=errors,sweep=sweep))
        if not sweep['passed']:raise ControlRejected('measured_upper_alignment_corridor')
        self.states[k],self.states[k+1]=start,end
        self.path.path[k]=self.path.last.copy()
        self.path.path[k+1]=end[self.qmap[self.upper]].tolist()
        for index in self.fingers:
            self.path.path[k+1][index-12]=float(self.nominal_commands[k+1,index-12])
        self.path.tracking_path[k]=self.path.expected_actual.copy()
        self.path.tracking_path[k+1]=end[self.qmap[self.upper]].tolist()
        self.aligned_segments.add(k)

    def _path_step(self,data):
        self._align_next(data)
        meta=super()._path_step(data)
        if self.phase=='pick' and any(mode=='contact_preload' for mode in self.hand_modes.values()):
            self.last_digit_sweep=digit_closure_corridor(self.query,data.qpos.copy(),self.last_goal_upper[self.fingers-12],self.fingers,self.source_supports)
            if not self.last_digit_sweep['passed']:raise ControlRejected('digit_closure_corridor')
        return meta
