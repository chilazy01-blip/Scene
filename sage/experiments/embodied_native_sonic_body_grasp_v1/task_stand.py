"""After safe hand retraction, hand back to a stationary G1 motion reference."""
import numpy as np
from .task_probe_wait import Task as Previous
from sage.experiments.embodied_data_stability_v1 import sonic_native_dynamic_shadow as native


class Task(Previous):
    def change(self,stage,tick,data,metrics):
        super().change(stage,tick,data,metrics)
        if stage!='settle':return
        ids=native._model_ids(self.mujoco,self.model)
        self.path=None;self.joint_path=None
        # Reference writes only. The physical floating base and joints are untouched.
        self.q[tick:,:3]=data.qpos[:3]
        self.q[tick:,3:7]=data.qpos[3:7]
        self.q[tick:,7:19]=self.baseq[0,7:19]
        self.q[tick:,19:36]=data.qpos[ids['qpos_ids'][12:29]]
        self.v[tick:]=0.
        self.events.append(dict(kind='stationary_g1_reference_after_hand_retraction',tick=tick,
            original_settle_acceptance_unchanged=True,all29_body_joints_still_sonic=True,
            reference_upper_body_rad=self.q[tick,19:36].tolist(),reference_lower_body_rad=self.q[tick,7:19].tolist(),
            actual_base_and_joint_states_unchanged=True,world_VR_reference_removed_after_task_manipulation=True))
