"""A fixed reference-local carried pose, rather than compensating every actual root wobble."""
from types import SimpleNamespace
import numpy as np
from scipy.spatial.transform import Rotation
from .task_envelope import Task as Previous
from .wrist_smooth import SmoothReference
from sage.experiments.embodied_native_sonic_grasp_feedback_v1.continuous_lift import make_path
from sage.experiments.embodied_native_sonic_transport_v1.teleop_reference_ordered import RIGHT_OFFSET

def world_targets(position_local,quaternion_local,root_position,root_quat):
    root=Rotation.from_quat(np.asarray(root_quat)[[1,2,3,0]]).as_matrix()
    points=np.asarray(position_local).reshape(3,3)@root.T+np.asarray(root_position)
    quats=np.asarray(quaternion_local).reshape(3,4)
    rotations=np.array([root@Rotation.from_quat(q[[1,2,3,0]]).as_matrix() for q in quats])
    return points,rotations

class Task(Previous):
    def reference_blocks(self,tick,data,initial_quaternion):
        blocks=super().reference_blocks(tick,data,initial_quaternion)
        held=self.stage in ('carry','target_stop') and self.walk_start is not None and tick-self.walk_start>=70
        if held:
            if not hasattr(self,'fixed_local_vr') or self.fixed_local_vr is None:
                self.fixed_local_vr=(np.array(blocks['vr_3point_local_target']).copy(),np.array(blocks['vr_3point_local_orn_target']).copy())
                self.events.append(dict(kind='fixed_reference_local_loaded_pose',tick=tick,position_local=self.fixed_local_vr[0].tolist(),quaternion_local=self.fixed_local_vr[1].tolist(),reference_frame_not_renormalized_by_future_robot_root_wobble=True,first_input_unchanged=True))
            blocks['vr_3point_local_target']=self.fixed_local_vr[0].copy();blocks['vr_3point_local_orn_target']=self.fixed_local_vr[1].copy()
        return blocks

    def move(self,tick,data,goal,rotation,duration=65):
        if self.stage in ('place','retract'):
            active=getattr(self,'fixed_local_vr',None)
            if active is not None:
                points,rots=world_targets(*active,data.qpos[:3],data.qpos[3:7])
                position=points[1]-rots[1]@RIGHT_OFFSET;R=rots[1]
                self.teleop_anchors=[(points[0],rots[0]),(points[2],rots[2])]
                self.feedback=SmoothReference(SimpleNamespace(position=np.zeros(3),rotation=np.zeros(3)))
                self.feedback_tick=None;self.fixed_local_vr=None
            else:position,R=self.desired(tick)
            if self.stage=='place':
                goal=np.asarray(self.case['target_object_xyz_m'])-self.grasp_R@np.asarray(self.last_object_local);duration=60
            else:duration=35
            self.path=make_path(tick,position,R,goal,self.grasp_R,duration);self.joint_path=None
            self.events.append(dict(kind='cartesian_path',tick=tick,origin=position.tolist(),goal=np.asarray(goal).tolist(),rotation=self.grasp_R.tolist(),duration=duration,origin_source='actual_delivered_fixed_local_reference_or_prior_desired',original_world_object_goal_and_acceptance_unchanged=True))
            self.synchronize(tick,data,force=True);return
        return super().move(tick,data,goal,rotation,duration)
