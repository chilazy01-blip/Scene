"""Keep official ordered wrist/head control throughout loaded walking and braking."""
import numpy as np
from scipy.spatial.transform import Rotation
from .task_clearance import Task as Previous
from .carry_reference import capture,targets
from .continuous_lift import make_path

class Task(Previous):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.carry_anchor=None
    def walk(self,tick,data,loaded):
        if loaded:
            p,R=self.desired(tick);left,head=self.teleop_anchors;anchor=capture(data.qpos[:3],data.qpos[3:7],[(p,R),left,head])
        super().walk(tick,data,loaded)
        if loaded:
            self.carry_anchor=anchor;self.update_carry_reference(tick,data);self.events.append(dict(kind='loaded_walk_preserves_official_wrist_head_mode',tick=tick,wrist_reference_m=self.desired(tick)[0].tolist(),world_height_fixed=True,yaw_follows_base=True,lower12_original_walking_reference=True,all29_body_outputs_sonic=True))
    def update_carry_reference(self,tick,data):
        wrist,left,head=targets(self.carry_anchor,data.qpos[:3],data.qpos[3:7]);p,R=wrist;velocity=np.zeros(6);self.mujoco.mj_objectVelocity(self.model,data,self.mujoco.mjtObj.mjOBJ_BODY,self.model.body('pelvis').id,velocity,0);v=np.r_[velocity[3:5],0.];nextR=Rotation.from_euler('z',velocity[2]*.02).as_matrix()@R
        self.path=make_path(tick,p,R,p+v*.02,nextR,1);self.teleop_anchors=[left,head];self.joint_path=None
    def update(self,tick,data,m):
        if self.stage in ('carry','target_stop') and self.carry_anchor is not None:self.update_carry_reference(tick,data)
        return super().update(tick,data,m)
