"""Preserve the validated grasp pose during carry preparation and straight walking."""
import numpy as np
from .task_reserve import Task as Previous
from .carry_reference import capture
from .steady_carry_reference import targets
from .continuous_lift import make_path
from sage.experiments.embodied_native_sonic_transport_v1.task_ordered import Task as BodyTask

class Task(Previous):
    def move(self,tick,data,goal,rotation,duration=65):
        if self.stage=='tuck' and tick>=1362:
            p,R=self.desired(tick);self.path=make_path(tick,p,R,p,R,60);self.joint_path=None;self.events.append(dict(kind='cartesian_path',tick=tick,origin=p.tolist(),goal=p.tolist(),rotation=R.tolist(),duration=60,origin_source='validated_grasp_desired_pose',hold_carry_preparation_pose=True));self.synchronize(tick,data,force=True);return
        return super().move(tick,data,goal,rotation,duration)
    def walk(self,tick,data,loaded):
        if not loaded:return super().walk(tick,data,loaded)
        p,R=self.desired(tick);left,head=self.teleop_anchors;anchor=capture(data.qpos[:3],data.qpos[3:7],[(p,R),left,head]);BodyTask.walk(self,tick,data,loaded);self.carry_anchor=anchor;self.update_carry_reference(tick,data);self.events.append(dict(kind='loaded_walk_preserves_official_wrist_head_mode',tick=tick,wrist_reference_m=self.desired(tick)[0].tolist(),world_height_fixed=True,yaw_follows_base=False,lower12_original_walking_reference=True,all29_body_outputs_sonic=True))
    def update_carry_reference(self,tick,data):
        wrist,left,head=targets(self.carry_anchor,data.qpos[:3],data.qpos[3:7]);p,R=wrist;velocity=np.zeros(6);self.mujoco.mj_objectVelocity(self.model,data,self.mujoco.mjtObj.mjOBJ_BODY,self.model.body('pelvis').id,velocity,0);v=np.r_[velocity[3:5],0.];self.path=make_path(tick,p,R,p+v*.02,R,1);self.teleop_anchors=[left,head];self.joint_path=None
