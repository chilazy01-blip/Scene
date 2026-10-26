"""Treat probe age70 as minimum observation age, keeping all actual load gates."""
import numpy as np
from sage.experiments.embodied_sonic_command_integration_v1.task_envelope import Task as Previous
from sage.experiments.embodied_native_sonic_loaded_grasp_v1.quality import evaluate


class Task(Previous):
    def update(self,tick,data,m):
        if self.stage=='load_probe' and tick-self.start>=70 and not self.done and not self.failure:
            q=evaluate(self.mujoco,self.model,data);self.quality=q
            slip=float(np.linalg.norm(np.array(m['object_local_m'])-self.anchor))
            ready=bool(m['object_m'][2]-self.probe_origin[2]>=.006 and not m['desk_supported'] and q['hand_force_world_n'][2]>=.8*q['weight_n'] and q['qualified'] and slip<=.006)
            if not ready and tick-self.start<140 and slip<=.008:
                self.last_object_local=m['object_local_m'];self.last_object_local_world=np.array(m['object_m']);self.max_slip=max(self.max_slip,slip)
                self.force_update(tick,data,m)
                self.events.append(dict(kind='actual_wrench_quality',tick=tick,stage=self.stage,quality=q,group_closures=None))
                self.events.append(dict(kind='wait_for_original_probe_transfer_gates',tick=tick,age=tick-self.start,lift_delta_m=float(m['object_m'][2]-self.probe_origin[2]),required_lift_m=.006,relative_slip_m=slip,desk_supported=m['desk_supported'],actual_force_z_n=q['hand_force_world_n'][2],all_original_gates_unchanged=True))
                return
        return super().update(tick,data,m)
