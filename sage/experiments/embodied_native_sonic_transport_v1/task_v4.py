"""Joint refs for walking/raise, official wrist targets for contact manipulation."""
import numpy as np
from scipy.spatial.transform import Rotation
from .task_v2 import Task as ParentTask
from .reference_feedback import ReferenceFeedback
from .teleop_reference import blocks,LEFT_OFFSET,RIGHT_OFFSET,HEAD_OFFSET
from sage.experiments.embodied_data_stability_v1 import sonic_native_dynamic_shadow as native


class Task(ParentTask):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.teleop_anchors=None;self.feedback=ReferenceFeedback();self.feedback_tick=None

    def walk(self,tick,data,loaded):
        super().walk(tick,data,loaded)
        self.teleop_anchors=None
        if loaded:
            ids=native._model_ids(self.mujoco,self.model)
            self.q[tick:,19:36]=data.qpos[ids['qpos_ids'][12:29]]
            self.v[tick:,12:29]=0

    def synchronize(self,tick,data,force=False):
        if self.path is None:return
        if self.teleop_anchors is None:
            captured=[]
            for name,offset in [('left_wrist_yaw_link',LEFT_OFFSET),('torso_link',HEAD_OFFSET)]:
                b=self.model.body(name).id;R=data.xmat[b].reshape(3,3).copy()
                captured.append((data.xpos[b].copy()+R@offset,R))
            self.teleop_anchors=captured
            self.events.append(dict(kind='official_teleop_anchor_capture',tick=tick,anchors=[dict(position=p.tolist(),rotation=R.tolist()) for p,R in captured]))
        if not force and tick%5:return
        if self.feedback_tick==tick:return
        pos,R=self.desired(tick)
        error=pos-data.xpos[self.wrist];rerror=Rotation.from_matrix(R@data.xmat[self.wrist].reshape(3,3).T).as_rotvec()
        dt=0 if self.feedback_tick is None else min(.1,max(0,(tick-self.feedback_tick)*.02))
        bias,rbias=self.feedback.update(error,rerror,dt);self.feedback_tick=tick
        self.events.append(dict(kind='direct_wrist_reference_feedback',tick=tick,position_error_m=error.tolist(),orientation_error_rad=rerror.tolist(),
            position_bias_m=bias.tolist(),rotation_bias_rad=rbias.tolist(),independent_motor_commands=False))

    def reference_blocks(self,tick,data,initial_quaternion):
        if self.path is None:
            return native.build_dynamic_g1_encoder_blocks(self.q,self.v,tick,initial_robot_quaternion_wxyz=initial_quaternion,current_robot_quaternion_wxyz=data.qpos[3:7])
        left,head=self.teleop_anchors
        pos,R=self.desired(tick);pos=pos+self.feedback.position
        R=Rotation.from_rotvec(self.feedback.rotation).as_matrix()@R
        points=np.array([left[0],pos+R@RIGHT_OFFSET,head[0]])
        rotations=np.array([left[1],R,head[1]])
        return blocks(self.q,self.v,tick,initial_quaternion,data.qpos[3:7],data.qpos[:3],points,rotations)
