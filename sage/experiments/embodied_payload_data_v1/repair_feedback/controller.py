"""Causal successor: measured bias feedback, latched braking, native actuators.

This implementation alone grants no new physical or production admission.
"""
import numpy as np
import mujoco
from ..repair_v2.controller import TaskController as FrozenController
from ..repair_v2.progress import ControlRejected
from ..control import TorqueAudit
from .progress import CoordinatedPath
from .feedback import BoundedBias


class FeedbackController(FrozenController):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        nominal=np.asarray(self.path.path).copy()
        tracking=np.asarray(self.path.tracking_path)
        # Historical moving-demo offsets are not equilibrium compensation after
        # retiming. Torso/arm position references use the planned actual pose;
        # native bias torque is already applied by TorqueAudit. Finger preload
        # remains explicit because it establishes grasp contact force.
        ordinary=[i for i,j in enumerate(self.upper) if j not in set(self.fingers)]
        nominal[:,ordinary]=tracking[:,ordinary]
        self.path=CoordinatedPath(nominal,tracking_waypoints=tracking)
        self.feedback=BoundedBias(self.last_goal_upper)
        self.feedback_meta={}
        self.actuator_audit=TorqueAudit(self.query.m,self.qmap,self.c['inspection'])
        self.actuator_query=mujoco.MjData(self.query.m)
        self.command_bounds=[]
        hands=set(map(int,self.actuator_audit.hands))
        for j in self.upper:
            aid=int(self.actuator_audit.act[j]);jid=int(np.flatnonzero(self.query.m.jnt_qposadr==self.qmap[j])[0])
            if j in hands and self.query.m.actuator_ctrllimited[aid]:
                bound=self.query.m.actuator_ctrlrange[aid].copy()
            elif self.query.m.jnt_limited[jid]:bound=self.query.m.jnt_range[jid].copy()
            else:bound=np.array([-np.inf,np.inf])
            self.command_bounds.append(tuple(map(float,bound)))

    def _new_measured_path(self,held):
        # Preserve the stable measured initial preload. Subsequent correction is
        # estimated from tracking error instead of forced linear preload decay.
        tracking=self.states[:,self.qmap[self.upper]]
        bias=np.asarray(held)-tracking[0]
        previous_velocity=self.feedback.velocity[:]
        same_command=np.max(np.abs(np.asarray(held)-self.feedback.last))<1e-10
        self.path=CoordinatedPath(tracking+bias,tracking_waypoints=tracking)
        self.last_goal_upper=np.asarray(held).copy()
        self.feedback=BoundedBias(held)
        if same_command:self.feedback.velocity=previous_velocity

    def begin_checkpoint(self,data,previous_command,kind):
        super().begin_checkpoint(data,previous_command,kind)
        self.feedback=BoundedBias(self.last_goal_upper)
        self.path=CoordinatedPath(self.path.path,tracking_waypoints=self.path.tracking_path)

    def _placement(self,data):
        held=self.last_goal_upper.copy()
        super()._placement(data)
        self._new_measured_path(held)

    def _release(self,data):
        held=self.last_goal_upper.copy()
        super()._release(data)
        self._new_measured_path(held)

    def _path_step(self,data):
        previous_expected=self.path.expected_actual.copy()
        meta=super()._path_step(data)
        actual=data.qpos[self.qmap[self.upper]].copy()
        query=self.actuator_query;m=self.query.m
        query.qpos[:]=data.qpos;query.qvel[:]=data.qvel
        mujoco.mj_forward(m,query)
        def safe(command):
            full=self.last_command.copy();full[12:43]=command
            self.actuator_audit.expected(query,full)
            for part,(ids,dofs,aids,kp,kd) in self.actuator_audit.parts.items():
                if part=='legs':continue
                pd=kp*(full[ids]-query.qpos[self.qmap[ids]])-kd*query.qvel[dofs]
                raw=self.actuator_audit.matrix[np.ix_(dofs,dofs)]@pd+query.qfrc_bias[dofs]
                if np.any(raw<m.actuator_ctrlrange[aids,0]) or np.any(raw>m.actuator_ctrlrange[aids,1]):
                    self.feedback_rejection=dict(part=part,raw=raw.tolist(),limits=m.actuator_ctrlrange[aids].tolist(),
                        nominal=self.last_goal_upper.tolist(),candidate=list(command),
                        actual=query.qpos[self.qmap[ids]].tolist(),velocity=query.qvel[dofs].tolist(),
                        expected_actual=list(self.path.expected_actual),source_phase=self.current_phase)
                    return False
            return True
        issued,feedback=self.feedback.step(self.last_goal_upper,previous_expected,actual,
            bounds=self.command_bounds,safe=safe)
        self.last_goal_upper=np.asarray(issued);self.feedback_meta=feedback
        meta.update(feedback=feedback,expected_actual=list(self.path.expected_actual),
            actual=list(actual),geometry_scope='Measured/reference stopping corridor; corrected-command dynamics require validation.')
        return meta
